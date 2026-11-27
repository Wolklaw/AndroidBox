"""A small D-Bus client, enough to talk to the desktop portal and to systemd on Linux.

It speaks the wire protocol itself (https://dbus.freedesktop.org/doc/dbus-specification.html): it signs in with
the EXTERNAL method, writes and reads messages, and a thread reads replies and signals as they come in. Methods
are called with an explicit signature, and a variant is written as Variant(signature, value). Read back, a
variant is just its value."""
import itertools
import os
import socket
import struct
import threading
from pathlib import Path

APP_ID = "dev.wolklaw.Androidbox"
BUS = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")
PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"

CALL, RETURN, ERROR, SIGNAL = 1, 2, 3, 4
NO_REPLY_EXPECTED = 0x1
PATH, INTERFACE, MEMBER, ERROR_NAME, REPLY_SERIAL, DESTINATION, SENDER, SIGNATURE = range(1, 9)
FIELD_TYPES = {PATH: "o", INTERFACE: "s", MEMBER: "s", ERROR_NAME: "s", REPLY_SERIAL: "u", DESTINATION: "s",
               SENDER: "s", SIGNATURE: "g"}
ALIGN = {"y": 1, "b": 4, "n": 2, "q": 2, "i": 4, "u": 4, "x": 8, "t": 8, "d": 8, "h": 4, "s": 4, "o": 4, "g": 1,
         "a": 4, "(": 8, "{": 8, "v": 1}
FIXED = {"y": "B", "b": "I", "n": "h", "q": "H", "i": "i", "u": "I", "x": "q", "t": "Q", "d": "d", "h": "I"}
MAX_MESSAGE = 1 << 27


class DBusError(OSError):
    def __init__(self, name, text=""):
        super().__init__(f"{name}: {text}" if text else name)
        self.name = name


class Variant:
    __slots__ = ("signature", "value")

    def __init__(self, signature, value):
        self.signature = signature
        self.value = value

    def __repr__(self):
        return f"Variant({self.signature!r}, {self.value!r})"


def type_end(signature, start):
    """Where the single complete type that starts at `start` ends"""
    char = signature[start]
    if char == "a":
        return type_end(signature, start + 1)
    if char in "({":
        close = ")" if char == "(" else "}"
        index = start + 1
        while signature[index] != close:
            index = type_end(signature, index)
        return index + 1
    if char not in ALIGN:
        raise ValueError(f"Unknown D-Bus type {char!r} in {signature!r}")
    return start + 1


def split(signature):
    """A signature such as 'sa{sv}u' as its complete types: ['s', 'a{sv}', 'u']"""
    types, index = [], 0
    while index < len(signature):
        end = type_end(signature, index)
        types.append(signature[index:end])
        index = end
    return types


class Writer:
    """Marshals values little-endian. Alignment counts from the start of the buffer, which is the start of the
    message for the header and an 8-aligned place for the body, so both come out right"""

    def __init__(self):
        self.data = bytearray()

    def pad(self, size):
        self.data += bytes(-len(self.data) % size)

    def put(self, signature, value):
        char = signature[0]
        if char in FIXED:
            self.pad(ALIGN[char])
            self.data += struct.pack("<" + FIXED[char], int(bool(value)) if char == "b" else value)
        elif char in "so":
            raw = value.encode()
            self.pad(4)
            self.data += struct.pack("<I", len(raw)) + raw + b"\0"
        elif char == "g":
            raw = value.encode()
            self.data += bytes([len(raw)]) + raw + b"\0"
        elif char == "v":
            self.put("g", value.signature)
            self.put(value.signature, value.value)
        elif char == "(":
            self.pad(8)
            members = split(signature[1:-1])
            if len(members) != len(value):
                raise ValueError(f"{signature} needs {len(members)} values, not {len(value)}")
            for member, item in zip(members, value):
                self.put(member, item)
        elif char == "a":
            item = signature[1:]
            self.pad(4)
            length_at = len(self.data)
            self.data += bytes(4)
            # The padding before the first element is not counted in the array's length
            self.pad(ALIGN[item[0]])
            start = len(self.data)
            if item[0] == "{":
                key, val = split(item[1:-1])
                for name, entry in value.items():
                    self.pad(8)
                    self.put(key, name)
                    self.put(val, entry)
            else:
                for element in value:
                    self.put(item, element)
            struct.pack_into("<I", self.data, length_at, len(self.data) - start)
        else:
            raise ValueError(f"Can't write D-Bus type {signature!r}")


class Reader:
    def __init__(self, data, endian="<", offset=0):
        self.data = data
        self.endian = endian
        self.at = offset

    def pad(self, size):
        self.at += -self.at % size

    def take(self, size):
        if self.at + size > len(self.data):
            raise ValueError("D-Bus message ends early")
        chunk = self.data[self.at:self.at + size]
        self.at += size
        return chunk

    def get(self, signature):
        char = signature[0]
        if char in FIXED:
            self.pad(ALIGN[char])
            fmt = self.endian + FIXED[char]
            (value,) = struct.unpack(fmt, self.take(struct.calcsize(fmt)))
            return bool(value) if char == "b" else value
        if char in "so":
            self.pad(4)
            (size,) = struct.unpack(self.endian + "I", self.take(4))
            text = bytes(self.take(size)).decode("utf-8", "replace")
            self.take(1)
            return text
        if char == "g":
            size = self.take(1)[0]
            text = bytes(self.take(size)).decode("ascii", "replace")
            self.take(1)
            return text
        if char == "v":
            return self.get(self.get("g"))
        if char == "(":
            self.pad(8)
            return tuple(self.get(member) for member in split(signature[1:-1]))
        if char == "a":
            self.pad(4)
            (size,) = struct.unpack(self.endian + "I", self.take(4))
            item = signature[1:]
            self.pad(ALIGN[item[0]])
            end = self.at + size
            if end > len(self.data):
                raise ValueError("D-Bus message ends early")
            if item[0] == "{":
                key, val = split(item[1:-1])
                entries = {}
                while self.at < end:
                    self.pad(8)
                    name = self.get(key)
                    entries[name] = self.get(val)
                return entries
            elements = []
            while self.at < end:
                elements.append(self.get(item))
            return elements
        raise ValueError(f"Can't read D-Bus type {signature!r}")


def encode(kind, serial, fields, signature="", body=(), flags=0):
    """A whole message. `fields` is {field code: value}"""
    payload = Writer()
    types = split(signature)
    if len(types) != len(body):
        raise ValueError(f"{signature!r} needs {len(types)} arguments, not {len(body)}")
    for kind_of, value in zip(types, body):
        payload.put(kind_of, value)
    if signature:
        fields = {**fields, SIGNATURE: signature}
    header = Writer()
    header.data += struct.pack("<cBBBII", b"l", kind, flags, 1, len(payload.data), serial)
    header.put("a(yv)", [(code, Variant(FIELD_TYPES[code], value)) for code, value in fields.items()])
    header.pad(8)
    return bytes(header.data + payload.data)


class Message:
    __slots__ = ("kind", "flags", "serial", "fields", "body")

    def __init__(self, kind, flags, serial, fields, body):
        self.kind, self.flags, self.serial, self.fields, self.body = kind, flags, serial, fields, body

    path = property(lambda self: self.fields.get(PATH))
    interface = property(lambda self: self.fields.get(INTERFACE))
    member = property(lambda self: self.fields.get(MEMBER))
    sender = property(lambda self: self.fields.get(SENDER))


def decode(data):
    endian = {ord("l"): "<", ord("B"): ">"}.get(data[0])
    if not endian:
        raise ValueError("Not a D-Bus message")
    kind, flags, _, _, serial = struct.unpack(endian + "BBBII", bytes(data[1:12]))
    reader = Reader(data, endian, 12)
    fields = dict(reader.get("a(yv)"))
    reader.pad(8)
    body = [reader.get(kind_of) for kind_of in split(fields.get(SIGNATURE, ""))]
    return Message(kind, flags, serial, fields, body)


def message_size(head):
    """The full size of a message from its first 16 bytes"""
    endian = {ord("l"): "<", ord("B"): ">"}.get(head[0])
    if not endian:
        raise ValueError("Not a D-Bus message")
    body, _, fields = struct.unpack(endian + "III", bytes(head[4:16]))
    size = 16 + fields
    size += -size % 8
    return size + body


def unescape(text):
    """Values in a bus address escape bytes as %xx"""
    out, index = bytearray(), 0
    while index < len(text):
        if text[index] == "%":
            out.append(int(text[index + 1:index + 3], 16))
            index += 3
        else:
            out += text[index].encode()
            index += 1
    return out.decode()


def session_address():
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if address:
        return address
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if (Path(runtime) / "bus").exists():
        return f"unix:path={runtime}/bus"
    raise DBusError("org.freedesktop.DBus.Error.NoServer", "There is no session bus")


def connect(address):
    """A socket to the first address in the list that answers. Only Unix sockets: that's what desktops use"""
    failure = None
    for entry in address.split(";"):
        transport, _, rest = entry.partition(":")
        if transport != "unix":
            continue
        keys = dict(pair.split("=", 1) for pair in rest.split(",") if "=" in pair)
        if "path" in keys:
            target = unescape(keys["path"])
        elif "abstract" in keys:
            target = "\0" + unescape(keys["abstract"])
        else:
            continue
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(5)
            sock.connect(target)
            return sock
        except OSError as error:
            sock.close()
            failure = error
    raise failure or DBusError("org.freedesktop.DBus.Error.BadAddress", f"No usable address in {address!r}")


class Pending:
    __slots__ = ("event", "reply")

    def __init__(self):
        self.event = threading.Event()
        self.reply = None


class Bus:
    def __init__(self, address):
        self.sock = connect(address)
        self.closed = False
        self.serials = itertools.count(1)
        self.tokens = itertools.count(1)
        self.send_lock = threading.Lock()
        self.waiting = {}
        self.handlers = []
        try:
            self.authenticate()
        except Exception:
            self.sock.close()
            raise
        self.sock.settimeout(None)
        threading.Thread(target=self.read_loop, name="dbus", daemon=True).start()
        self.name = self.call(*BUS, "Hello")[0]

    def authenticate(self):
        self.sock.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
        line = self.read_line()
        if not line.startswith(b"OK"):
            raise DBusError("org.freedesktop.DBus.Error.AuthFailed", line.decode(errors="replace"))
        self.sock.sendall(b"BEGIN\r\n")

    def read_line(self):
        line = bytearray()
        while not line.endswith(b"\r\n"):
            chunk = self.sock.recv(1)
            if not chunk or len(line) > 4096:
                raise DBusError("org.freedesktop.DBus.Error.AuthFailed", "The bus hung up while signing in")
            line += chunk
        return bytes(line)

    def receive_exactly(self, size):
        data = bytearray()
        while len(data) < size:
            chunk = self.sock.recv(min(size - len(data), 1 << 16))
            if not chunk:
                raise ConnectionError("The bus hung up")
            data += chunk
        return data

    def read_loop(self):
        try:
            while True:
                head = self.receive_exactly(16)
                size = message_size(head)
                if size > MAX_MESSAGE:
                    raise ConnectionError("A D-Bus message was too big")
                self.dispatch(decode(head + self.receive_exactly(size - 16)))
        except (OSError, ValueError, struct.error):
            pass
        finally:
            self.closed = True
            for pending in list(self.waiting.values()):
                pending.event.set()
            self.waiting.clear()

    def dispatch(self, message):
        if message.kind in (RETURN, ERROR):
            pending = self.waiting.pop(message.fields.get(REPLY_SERIAL), None)
            if pending:
                pending.reply = message
                pending.event.set()
        elif message.kind == SIGNAL:
            for path, interface, member, callback in list(self.handlers):
                if message.interface == interface and message.member == member and path in (None, message.path):
                    try:
                        callback(message)
                    except Exception:
                        pass
        elif message.kind == CALL and not message.flags & NO_REPLY_EXPECTED and message.sender:
            # Nothing is offered on this connection
            with Unanswered():
                self.send(encode(ERROR, next(self.serials), {
                    REPLY_SERIAL: message.serial, DESTINATION: message.sender,
                    ERROR_NAME: "org.freedesktop.DBus.Error.UnknownMethod"}))

    def send(self, data):
        if self.closed:
            raise ConnectionError("The bus connection is closed")
        with self.send_lock:
            self.sock.sendall(data)

    def call(self, destination, path, interface, member, signature="", args=(), timeout=5.0):
        """Calls a method and returns its reply's values as a list. Raises DBusError if it answers with an error"""
        serial = next(self.serials)
        pending = Pending()
        self.waiting[serial] = pending
        fields = {PATH: path, MEMBER: member, DESTINATION: destination}
        if interface:
            fields[INTERFACE] = interface
        try:
            self.send(encode(CALL, serial, fields, signature, args))
        except Exception:
            self.waiting.pop(serial, None)
            raise
        if not pending.event.wait(timeout):
            self.waiting.pop(serial, None)
            raise DBusError("org.freedesktop.DBus.Error.NoReply", f"{interface}.{member} didn't answer")
        reply = pending.reply
        if reply is None:
            raise DBusError("org.freedesktop.DBus.Error.Disconnected", "The bus connection closed")
        if reply.kind == ERROR:
            text = reply.body[0] if reply.body and isinstance(reply.body[0], str) else ""
            raise DBusError(reply.fields.get(ERROR_NAME, "org.freedesktop.DBus.Error.Failed"), text)
        return reply.body

    def get_property(self, destination, path, interface, name, timeout=5.0):
        return self.call(destination, path, "org.freedesktop.DBus.Properties", "Get", "ss", (interface, name),
                         timeout)[0]

    def subscribe(self, callback, interface, member, path=None):
        """Calls callback(message) on the reading thread for each matching signal. Returns what unsubscribe takes"""
        rule = f"type='signal',interface='{interface}',member='{member}'" + (f",path='{path}'" if path else "")
        handler = (path, interface, member, callback)
        self.handlers.append(handler)
        try:
            self.call(*BUS, "AddMatch", "s", (rule,))
        except Exception:
            self.handlers.remove(handler)
            raise
        return handler, rule

    def unsubscribe(self, subscription):
        handler, rule = subscription
        if handler in self.handlers:
            self.handlers.remove(handler)
        with Unanswered():
            self.call(*BUS, "RemoveMatch", "s", (rule,), timeout=2)

    def portal_request(self, path, interface, member, signature, args, timeout=120.0):
        """Calls a portal method that answers later through a Request object, and returns (response, results).
        The last argument must be the options dictionary: the request's handle token is added to it. A response
        of 0 is success, 1 means the user cancelled, 2 any other failure"""
        token = f"androidbox{os.getpid()}_{next(self.tokens)}"
        sender = self.name.lstrip(":").replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        done = threading.Event()
        answer = []

        def responded(message):
            answer.extend(message.body)
            done.set()

        # Subscribed before the call, so even an instant answer is caught
        subscription = self.subscribe(responded, "org.freedesktop.portal.Request", "Response", handle)
        try:
            options = {**args[-1], "handle_token": Variant("s", token)}
            self.call(PORTAL, path, interface, member, signature, (*args[:-1], options))
            if not done.wait(timeout):
                with Unanswered():
                    self.call(PORTAL, handle, "org.freedesktop.portal.Request", "Close", timeout=2)
                raise DBusError("org.freedesktop.DBus.Error.NoReply", f"{interface}.{member} didn't answer")
            if len(answer) < 2:
                raise DBusError("org.freedesktop.DBus.Error.Disconnected", "The portal's answer was lost")
            return answer[0], answer[1]
        finally:
            self.unsubscribe(subscription)

    def close(self):
        self.closed = True
        with Unanswered():
            self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()


class Unanswered:
    """Ignores a failure of something that is only a courtesy"""

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        return kind is not None and issubclass(kind, (OSError, ValueError))


_lock = threading.Lock()
_session = None
_registered = None


def session():
    """The shared connection to the session bus, opened the first time. Raises OSError if there is none"""
    global _session, _registered
    with _lock:
        if _session is None or _session.closed:
            _session = Bus(session_address())
            _registered = None
        return _session


def portal():
    """The session bus, after telling the portal which app this is. That has to come before any other portal call
    on the connection, and a portal too old to know about it is fine without it"""
    global _registered
    bus = session()
    with _lock:
        if _registered is not bus:
            with Unanswered():
                bus.call(PORTAL, PORTAL_PATH, "org.freedesktop.host.portal.Registry", "Register", "sa{sv}",
                         (APP_ID, {}), timeout=10)
            _registered = bus
    return bus
