"""A tiny local HTTP proxy that forwards everything through a SOCKS5 proxy.

The Android emulator can only be pointed at an HTTP proxy (-http-proxy). Many providers, and apps like v2rayNG,
hand out SOCKS5 proxies instead, so Androidbox runs one of these on 127.0.0.1 and gives the emulator that address.
"""
import base64
import socket
import struct
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

CONNECT_TIMEOUT = 20
HEAD_LIMIT = 1 << 16
SOCKS_REPLIES = {1: "general failure", 2: "not allowed by the proxy's rules", 3: "network unreachable",
                 4: "host unreachable", 5: "connection refused", 6: "timed out", 7: "command not supported",
                 8: "address type not supported"}


class ProxyError(OSError):
    """The proxy answered, but not in a way that gets traffic through"""


def recv_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ProxyError("the proxy closed the connection")
        data += chunk
    return data


def socks5_handshake(sock, target_host, target_port, user="", password=""):
    """Asks the SOCKS5 proxy on an open socket to tunnel to target_host:target_port"""
    methods = b"\x00\x02" if user else b"\x00"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    version, method = recv_exact(sock, 2)
    if version != 5:
        raise ProxyError("that isn't a SOCKS5 proxy (it didn't answer like one)")
    if method == 0xFF:
        raise ProxyError("the proxy refused every login method")
    if method == 2:
        name, secret = user.encode(), password.encode()
        if len(name) > 255 or len(secret) > 255:
            raise ProxyError("the proxy login is too long")
        sock.sendall(b"\x01" + bytes([len(name)]) + name + bytes([len(secret)]) + secret)
        if recv_exact(sock, 2)[1] != 0:
            raise ProxyError("the proxy rejected the username or password")
    elif method != 0:
        raise ProxyError("the proxy wants a login method Androidbox doesn't support")
    sock.sendall(b"\x05\x01\x00" + address(target_host) + struct.pack(">H", target_port))
    head = recv_exact(sock, 4)
    if head[1] != 0:
        raise ProxyError(f"the proxy couldn't reach {target_host}:{target_port} ({SOCKS_REPLIES.get(head[1], 'error')}, "
                         f"code {head[1]})")
    skip = {1: 4, 4: 16}.get(head[3])
    if skip is None:
        skip = recv_exact(sock, 1)[0]
    recv_exact(sock, skip + 2)


def socks5_connect(host, port, target_host, target_port, user="", password=""):
    """An open socket to target_host:target_port tunnelled through the SOCKS5 proxy at host:port"""
    sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
    try:
        socks5_handshake(sock, target_host, target_port, user, password)
        sock.settimeout(None)
        return sock
    except BaseException:
        sock.close()
        raise


def http_connect(sock, target_host, target_port, user="", password=""):
    """Asks the HTTP proxy on an open socket to tunnel to target_host:target_port"""
    login = ""
    if user:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        login = f"Proxy-Authorization: Basic {token}\r\n"
    sock.sendall(f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n{login}\r\n"
                 .encode())
    reply = sock.recv(4096).decode("latin-1")
    status = reply.split(" ", 2)[1] if reply.startswith("HTTP/") and " " in reply else ""
    if status == "200":
        return
    if status == "407":
        raise ProxyError("the proxy rejected the username or password")
    if reply[:1] == "\x05":
        raise ProxyError("that is a SOCKS5 proxy: enter it as socks5://user:pass@host:port")
    if not reply:
        raise ProxyError("the proxy closed the connection")
    raise ProxyError(f"the proxy answered with an error ({status or 'not an HTTP reply'})")


def speaks_socks5(host, port, timeout=5):
    """True if the proxy at host:port answers a SOCKS5 greeting. Lets a SOCKS5 proxy typed as http://... (an easy
    slip, since apps like v2rayNG only show the host and port) still work. False when it can't be reached or is HTTP"""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"\x05\x01\x00")
            reply = sock.recv(2)
        return len(reply) == 2 and reply[0] == 5
    except OSError:
        return False


@dataclass
class Step:
    key: str
    ok: bool
    name: str
    detail: str


def describe(error, host, port, timeout):
    """One plain sentence for why a connection to host:port failed"""
    if isinstance(error, socket.gaierror):
        return f"{host} can't be looked up ({error.strerror or error})"
    if isinstance(error, TimeoutError):
        return f"no answer from {host}:{port} after {timeout} seconds"
    if isinstance(error, ConnectionRefusedError):
        return f"{host}:{port} refused the connection, so nothing is listening there"
    return str(error)


def reach(host, port, what, timeout=10):
    """([steps], socket or None): looks host up, then connects to it, one step for each so a failure says which"""
    steps = []
    try:
        found = sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except OSError as problem:
        return [Step("lookup", False, f"Look up {what}", describe(problem, host, port, timeout))], None
    steps.append(Step("lookup", True, f"Look up {what}", ", ".join(found[:4]) or host))
    started = time.monotonic()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as problem:
        steps.append(Step("connect", False, f"Connect to {what}", describe(problem, host, port, timeout)))
        return steps, None
    steps.append(Step("connect", True, f"Connect to {what}", f"{(time.monotonic() - started) * 1000:.0f} ms"))
    return steps, sock


def probe(kind, host, port, user="", password="", target=("example.com", 443), timeout=10):
    """The steps Android's traffic takes through a proxy, up to the first that fails: finding the proxy, reaching
    it, and asking it to open a connection to a well-known HTTPS host. A wrong login, a dead address and a wrong
    kind of proxy each fail at a different step"""
    steps, sock = reach(host, port, "the proxy", timeout)
    if not sock:
        return steps
    name = f"Ask the proxy for {target[0]}:{target[1]}"
    with sock:
        sock.settimeout(timeout)
        try:
            if kind == "socks":
                socks5_handshake(sock, *target, user, password)
            else:
                http_connect(sock, *target, user, password)
        except OSError as problem:
            key = "target" if "couldn't reach" in str(problem) else "proxy"
            detail = describe(problem, host, port, timeout) if isinstance(problem, TimeoutError) else str(problem)
            steps.append(Step(key, False, name, detail))
        else:
            steps.append(Step("target", True, name, "connected"))
    return steps


def check(kind, host, port, user="", password="", timeout=10):
    """(ok, message): can traffic get out through this proxy? Each failure gets its own message"""
    steps = probe(kind, host, port, user, password, timeout=timeout)
    failed = next((step for step in steps if not step.ok), None)
    if not failed:
        return True, f"The proxy works ({'SOCKS5' if kind == 'socks' else 'HTTP'})"
    if failed.key in ("lookup", "connect"):
        return False, f"Couldn't use the proxy: {failed.detail}"
    return False, failed.detail[:1].upper() + failed.detail[1:]


def address(host):
    for family, kind in ((socket.AF_INET, 1), (socket.AF_INET6, 4)):
        try:
            return bytes([kind]) + socket.inet_pton(family, host)
        except (OSError, ValueError):
            pass
    name = host.encode("idna")
    return b"\x03" + bytes([len(name)]) + name


def pump(source, target):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass
    for sock, how in ((target, socket.SHUT_WR), (source, socket.SHUT_RD)):
        try:
            sock.shutdown(how)
        except OSError:
            pass


def tunnel(a, b):
    other = threading.Thread(target=pump, args=(b, a), daemon=True)
    other.start()
    pump(a, b)
    other.join(timeout=5)


def split_host_port(text, default):
    host, separator, port = text.rpartition(":")
    if not separator or not port.isdigit():
        return text.strip("[]"), default
    return host.strip("[]"), int(port)


class Relay:
    def __init__(self, host, port, user="", password=""):
        self.upstream = (host, port, user, password)
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(64)
        self.port = self.server.getsockname()[1]
        self.closed = False
        threading.Thread(target=self.accept, daemon=True).start()

    @property
    def address(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.closed = True
        try:
            self.server.close()
        except OSError:
            pass

    def accept(self):
        while not self.closed:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(client,), daemon=True).start()

    def serve(self, client):
        remote = None
        try:
            client.settimeout(CONNECT_TIMEOUT)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(8192)
                if not chunk or len(data) > HEAD_LIMIT:
                    return
                data += chunk
            head, _, rest = data.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            parts = lines[0].split()
            if len(parts) < 3:
                return
            method, target, version = parts[0], parts[1], parts[2]
            if method.upper() == "CONNECT":
                host, port = split_host_port(target, 443)
                forward = None
            else:
                url = urlsplit(target)
                if not url.hostname:
                    client.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                    return
                host, port = url.hostname, url.port or 80
                path = (url.path or "/") + (f"?{url.query}" if url.query else "")
                kept = [line for line in lines[1:] if not line.lower().startswith(("proxy-", "connection:"))]
                forward = "\r\n".join([f"{method} {path} {version}", *kept, "Connection: close"]).encode("latin-1") \
                    + b"\r\n\r\n" + rest
            try:
                remote = socks5_connect(*self.upstream[:2], host, port, *self.upstream[2:])
            except OSError as problem:
                reason = str(problem).encode("ascii", "replace")
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: " + str(len(reason)).encode()
                               + b"\r\nConnection: close\r\n\r\n" + reason)
                return
            client.settimeout(None)
            if forward is None:
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if rest:
                    remote.sendall(rest)
            else:
                remote.sendall(forward)
            tunnel(client, remote)
        except OSError:
            pass
        finally:
            for sock in (client, remote):
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
