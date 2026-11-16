"""A tiny local HTTP proxy that forwards everything through a SOCKS5 proxy.

The Android emulator can only be pointed at an HTTP proxy (-http-proxy). Many providers, and apps like v2rayNG,
hand out SOCKS5 proxies instead, so Androidbox runs one of these on 127.0.0.1 and gives the emulator that address.
"""
import socket
import struct
import threading
from urllib.parse import urlsplit

CONNECT_TIMEOUT = 20
HEAD_LIMIT = 1 << 16


class SocksError(OSError):
    pass


def recv_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise SocksError("the proxy closed the connection")
        data += chunk
    return data


def socks5_connect(host, port, target_host, target_port, user="", password=""):
    """An open socket to target_host:target_port tunnelled through the SOCKS5 proxy at host:port"""
    sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
    try:
        methods = b"\x00\x02" if user else b"\x00"
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
        version, method = recv_exact(sock, 2)
        if version != 5 or method == 0xFF:
            raise SocksError("the proxy refused every login method")
        if method == 2:
            name, secret = user.encode(), password.encode()
            if len(name) > 255 or len(secret) > 255:
                raise SocksError("the proxy login is too long")
            sock.sendall(b"\x01" + bytes([len(name)]) + name + bytes([len(secret)]) + secret)
            if recv_exact(sock, 2)[1] != 0:
                raise SocksError("the proxy rejected the username or password")
        elif method != 0:
            raise SocksError("the proxy wants a login method Androidbox doesn't support")
        sock.sendall(b"\x05\x01\x00" + address(target_host) + struct.pack(">H", target_port))
        head = recv_exact(sock, 4)
        if head[1] != 0:
            raise SocksError(f"the proxy couldn't reach {target_host}:{target_port} (code {head[1]})")
        skip = {1: 4, 4: 16}.get(head[3])
        if skip is None:
            skip = recv_exact(sock, 1)[0]
        recv_exact(sock, skip + 2)
        sock.settimeout(None)
        return sock
    except BaseException:
        sock.close()
        raise


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
