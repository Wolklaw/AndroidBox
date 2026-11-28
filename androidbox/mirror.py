"""Your own phone in Androidbox: its screen streamed into the phone view, and Androidbox's touches, keys, keymaps,
gamepad and macros sent back to it.

It uses scrcpy's server (https://github.com/Genymobile/scrcpy, Apache 2.0), a small Java program adb runs on the
phone. It records the screen with the phone's own video encoder and takes input over a second socket. The H.264
stream it sends is decoded with PyAV (ffmpeg's decoder, which its wheels bundle) into plain RGB frames, the same
kind the emulator's own stream hands over."""
import contextlib
import hashlib
import queue
import random
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request

import av

from . import emulator, native, paths
from .proto import emulator_controller_pb2 as pb

SERVER_VERSION = "5.0.1"
SERVER_URL = f"https://github.com/Genymobile/scrcpy/releases/download/v{SERVER_VERSION}/scrcpy-server-v{SERVER_VERSION}"
SERVER_SHA256 = "764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536"
SERVER_SIZE = 733930
REMOTE_SERVER = "/data/local/tmp/androidbox-scrcpy-server.jar"
# The long side of the stream. The phone's full size (2992 on a Pixel 8 Pro) costs a lot to decode and copy for
# a window that is rarely that tall
MAX_SIZE = 1920
MAX_FPS = 60
CONNECT_WAIT = 15

# Control messages, from scrcpy's ControlMessage.java
INJECT_KEYCODE = 0
INJECT_TEXT = 1
INJECT_TOUCH = 2
INJECT_SCROLL = 3
GET_CLIPBOARD = 8
SET_CLIPBOARD = 9
SET_DISPLAY_POWER = 10
ROTATE_DEVICE = 11
TEXT_LIMIT = 300
# MotionEvent and KeyEvent actions
ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
# Messages the phone sends back
DEVICE_CLIPBOARD, DEVICE_ACK_CLIPBOARD, DEVICE_UHID_OUTPUT = 0, 1, 2

# Androidbox's key names (the emulator's, which follow the browser's KeyboardEvent.key) as Android key codes
KEYCODES = {
    "Enter": 66, "Backspace": 67, "Tab": 61, "Escape": 111, "Delete": 112,
    "ArrowLeft": 21, "ArrowRight": 22, "ArrowUp": 19, "ArrowDown": 20,
    "Home": 122, "End": 123, "PageUp": 92, "PageDown": 93, " ": 62,
    "Shift": 59, "Control": 113, "Alt": 57,
    "GoBack": 4, "GoHome": 3, "AppSwitch": 187, "Power": 26,
    "AudioVolumeUp": 24, "AudioVolumeDown": 25, "AudioVolumeMute": 164,
    **{chr(ord("a") + index): 29 + index for index in range(26)},
    **{str(digit): 7 + digit for digit in range(10)},
}
# What a held modifier adds to a key's meta state: the general flag and the left-hand key's
META = {"Shift": 0x41, "Control": 0x3000, "Alt": 0x12}


def server_file():
    return paths.DATA / f"scrcpy-server-v{SERVER_VERSION}"


def checksum(file):
    digest = hashlib.sha256()
    with open(file, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_server():
    """scrcpy's server, downloaded once from its GitHub release and checked against the checksum it was released
    with, so a file changed on the way never reaches the phone"""
    file = server_file()
    if file.exists() and file.stat().st_size == SERVER_SIZE and checksum(file) == SERVER_SHA256:
        return file
    file.parent.mkdir(parents=True, exist_ok=True)
    partial = file.with_name(file.name + ".part")
    request = urllib.request.Request(SERVER_URL, headers={"User-Agent": "Androidbox"})
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
        shutil.copyfileobj(response, out)
    if partial.stat().st_size != SERVER_SIZE or checksum(partial) != SERVER_SHA256:
        partial.unlink(missing_ok=True)
        raise OSError("The download of scrcpy's server didn't match its checksum")
    partial.replace(file)
    return file


# Encoding the control messages. Everything is big-endian, as Java's DataInputStream reads it

def keycode_message(action, keycode, repeat=0, meta=0):
    return struct.pack(">BBiii", INJECT_KEYCODE, action, keycode, repeat, meta)


def text_messages(text):
    """Text in pieces the server takes (300 bytes of UTF-8 each), never splitting a character"""
    messages = []
    piece = b""
    for char in text:
        encoded = char.encode("utf-8")
        if len(piece) + len(encoded) > TEXT_LIMIT:
            messages.append(piece)
            piece = b""
        piece += encoded
    if piece:
        messages.append(piece)
    return [struct.pack(">BI", INJECT_TEXT, len(piece)) + piece for piece in messages]


def touch_message(action, pointer, x, y, width, height, pressure):
    fixed = 0xffff if pressure >= 1 else max(0, round(pressure * 0x10000))
    return struct.pack(">BBqiiHHHii", INJECT_TOUCH, action, pointer, round(x), round(y), width, height, fixed, 0, 0)


def set_clipboard_message(text, paste=False):
    data = text.encode("utf-8")
    return struct.pack(">BqBI", SET_CLIPBOARD, 0, int(paste), len(data)) + data


def display_power_message(on):
    return struct.pack(">BB", SET_DISPLAY_POWER, int(on))


def rotate_message():
    return bytes([ROTATE_DEVICE])


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            return None
        data += chunk
    return bytes(data)


def read_device_message(stream):
    """(kind, value) for one message the phone sent on the control socket, or None once it closed"""
    head = read_exact(stream, 1)
    if head is None:
        return None
    kind = head[0]
    if kind == DEVICE_CLIPBOARD:
        size = read_exact(stream, 4)
        if size is None:
            return None
        text = read_exact(stream, struct.unpack(">i", size)[0])
        return None if text is None else (kind, text.decode("utf-8", "replace"))
    if kind == DEVICE_ACK_CLIPBOARD:
        sequence = read_exact(stream, 8)
        return None if sequence is None else (kind, struct.unpack(">q", sequence)[0])
    if kind == DEVICE_UHID_OUTPUT:
        header = read_exact(stream, 4)
        if header is None:
            return None
        _, size = struct.unpack(">HH", header)
        data = read_exact(stream, size)
        return None if data is None else (kind, data)
    raise ValueError(f"Unknown message from the phone: {kind}")


def packed_rows(data, stride, width, height):
    """Pixel rows without the padding a decoder leaves at the end of each one"""
    if stride == width * 3:
        return bytes(data[:stride * height])
    view = memoryview(data)
    return b"".join(view[line * stride:line * stride + width * 3] for line in range(height))


def rgb_frame(frame):
    rgb = frame.reformat(format="rgb24")
    plane = rgb.planes[0]
    return packed_rows(plane, plane.line_size, rgb.width, rgb.height), rgb.width, rgb.height


def fit(width, height, most_width, most_height):
    """The largest size with the frame's shape that fits inside most_width by most_height"""
    factor = min(most_width / width, most_height / height)
    return max(1, round(width * factor)), max(1, round(height * factor))


def scale(data, width, height, new_width, new_height):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    image = QImage(data, width, height, width * 3, QImage.Format.Format_RGB888)
    scaled = image.scaled(new_width, new_height, Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    if scaled.bytesPerLine() != new_width * 3:
        scaled = scaled.convertToFormat(QImage.Format.Format_RGB888)
    rows = bytes(scaled.constBits())
    stride = scaled.bytesPerLine()
    if stride != new_width * 3:
        rows = b"".join(rows[line * stride:line * stride + new_width * 3] for line in range(new_height))
    return rows, new_width, new_height


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def adb_command(serial, *args):
    return [str(paths.ADB), "-s", serial, *args]


class Session:
    """One run of scrcpy's server on the phone, with its video and control sockets"""

    def __init__(self, serial, log=None):
        self.serial = serial
        self.log = log
        self.scid = random.randrange(1, 0x7fffffff)
        self.port = None
        self.server = None
        self.video = None
        self.control = None
        self.closed = False
        self.write_lock = threading.Lock()

    def adb(self, *args, timeout=30):
        return emulator.run(adb_command(self.serial, *args), timeout)

    def start(self):
        local = fetch_server()
        code, output = self.adb("push", str(local), REMOTE_SERVER, timeout=60)
        if code != 0:
            raise OSError(f"Couldn't copy scrcpy's server to the phone: {emulator.last_line(output)}")
        self.port = free_port()
        name = f"localabstract:scrcpy_{self.scid:08x}"
        code, output = self.adb("forward", f"tcp:{self.port}", name, timeout=10)
        if code != 0:
            raise OSError(f"adb couldn't forward a port to the phone: {emulator.last_line(output)}")
        options = [f"scid={self.scid:08x}", "log_level=info", "tunnel_forward=true", "audio=false",
                   "control=true", "cleanup=true", f"max_size={MAX_SIZE}", f"max_fps={MAX_FPS}",
                   "video_codec=h264", "send_device_meta=false", "send_frame_meta=false",
                   "send_stream_meta=false", "clipboard_autosync=true", "stay_awake=true", "power_on=true"]
        log = open(self.log, "ab") if self.log else subprocess.DEVNULL
        try:
            self.server = subprocess.Popen(
                adb_command(self.serial, "shell", f"CLASSPATH={REMOTE_SERVER}", "app_process", "/",
                            "com.genymobile.scrcpy.Server", SERVER_VERSION, *options),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=emulator.environment(),
                **native.quiet_options())
        finally:
            if log is not subprocess.DEVNULL:
                log.close()
        self.video = self.connect_video()
        self.control = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.control.settimeout(None)
        self.control.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def connect_video(self):
        # adb accepts the connection before the server is listening and then drops it, so a connection only counts
        # once the server's first byte arrives
        deadline = time.monotonic() + CONNECT_WAIT
        while time.monotonic() < deadline and not self.closed:
            if self.server and self.server.poll() is not None:
                break
            connection = None
            try:
                connection = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                if connection.recv(1) == b"\x00":
                    connection.settimeout(None)
                    return connection
            except OSError:
                pass
            if connection:
                connection.close()
            time.sleep(0.2)
        raise OSError("scrcpy's server didn't start on the phone. Unlock it and check that USB debugging is "
                      "still allowed")

    def send(self, message):
        if self.closed or not self.control:
            return
        with self.write_lock:
            with contextlib.suppress(OSError):
                self.control.sendall(message)

    def stream(self, on_frame):
        """Decodes the video until the session ends, handing each frame to on_frame(rgb, width, height). Each
        frame keeps the size the phone sent, so turning it sideways makes wider frames instead of squashed ones"""
        decoder = av.CodecContext.create("h264", "r")
        decoder.flags |= av.codec.context.Flags.low_delay
        try:
            while not self.closed:
                chunk = self.video.recv(1 << 16)
                if not chunk:
                    break
                for packet in decoder.parse(chunk):
                    for frame in decoder.decode(packet):
                        on_frame(*rgb_frame(frame))
        except (OSError, ValueError, av.error.FFmpegError):
            pass

    def listen(self, on_message):
        stream = self.control.makefile("rb")
        try:
            while not self.closed:
                message = read_device_message(stream)
                if message is None:
                    break
                on_message(*message)
        except (OSError, ValueError):
            pass

    def close(self):
        self.closed = True
        for connection in (self.video, self.control):
            if connection:
                with contextlib.suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)
                connection.close()
        if self.server and self.server.poll() is None:
            self.server.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.server.wait(timeout=3)
            if self.server.poll() is None:
                self.server.kill()
        if self.port:
            self.adb("forward", "--remove", f"tcp:{self.port}", timeout=5)


class PhoneBridge:
    """What Bridge is to an emulator, for a real phone. The phone view, the controller, keymaps and macros talk to
    it the same way: input arrives as the emulator's own InputEvents, which also lets sync input and recorded
    macros work unchanged"""

    def __init__(self, instance, log=None):
        self.instance = instance
        self.outbox = queue.Queue()
        self.recording = None
        self.mirrors = []
        self.closed = False
        self.on_frame = None
        self.wanted = None
        self.target = None
        self.on_clipboard = None
        self.latest = None
        self.frame_size = (instance.width, instance.height)
        self.held = {}
        self.meta = 0
        self.failure = None
        # Set once the stream stops on its own: the phone was unplugged or locked adb out, or the server quit
        self.ended = False
        self.session = Session(instance.serial, log)
        self.ready = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()
        threading.Thread(target=self.deliver, daemon=True).start()

    def run(self):
        try:
            self.session.start()
        except Exception as error:
            self.failure = str(error)
            self.ended = True
            self.ready.set()
            return
        self.ready.set()
        threading.Thread(target=lambda: self.session.listen(self.message), daemon=True).start()
        self.session.stream(self.frame)
        self.ended = True

    def frame(self, data, width, height):
        self.frame_size = (width, height)
        self.latest = (data, width, height)
        self.show(data, width, height)

    def show(self, data, width, height):
        on_frame, wanted, target = self.on_frame, self.wanted, self.target
        if not on_frame or (wanted and not wanted()):
            return
        # The phone view draws a frame at the size it arrives, the way the emulator sends it: fitted to the view
        fitted = fit(width, height, *target) if target else (width, height)
        if fitted != (width, height):
            data, width, height = scale(data, width, height, *fitted)
        on_frame(data, width, height, 0, 3)

    def message(self, kind, value):
        if kind == DEVICE_CLIPBOARD and self.on_clipboard:
            self.on_clipboard(value)

    # Input, the way Bridge takes it

    def send(self, event, record=True):
        self.outbox.put(event)
        if record and self.recording is not None:
            self.recording.append((time.monotonic(), event.SerializeToString()))
        for mirror in self.mirrors:
            mirror.outbox.put(event)

    def replay(self, payload):
        event = pb.InputEvent()
        event.ParseFromString(payload)
        self.send(event, record=False)

    def touch(self, *touches):
        points = [pb.Touch(x=round(x), y=round(y), identifier=identifier, pressure=1 if down else 0)
                  for identifier, x, y, down in touches]
        self.send(pb.InputEvent(touch_event=pb.TouchEvent(touches=points)))

    def key(self, key, kind=pb.KeyboardEvent.keypress):
        self.send(pb.InputEvent(key_event=pb.KeyboardEvent(key=key, eventType=kind)))

    def text(self, text):
        self.send(pb.InputEvent(key_event=pb.KeyboardEvent(text=text, eventType=pb.KeyboardEvent.keypress)))

    def type(self, text):
        self.send(pb.InputEvent(key_event=pb.KeyboardEvent(text=text)))

    def deliver(self):
        self.ready.wait()
        while not self.closed:
            event = self.outbox.get()
            if event is None:
                return
            for message in self.translate(event):
                self.session.send(message)

    def translate(self, event):
        """The scrcpy control messages for one of the emulator's InputEvents"""
        kind = event.WhichOneof("type")
        if kind == "touch_event":
            return self.touch_messages(event.touch_event)
        if kind == "key_event":
            return self.key_messages(event.key_event)
        return []

    def touch_messages(self, touch):
        messages = []
        width, height = self.frame_size
        for point in touch.touches:
            # The phone view places touches in the instance's own size; the stream may be smaller or turned
            x = point.x / max(self.instance.width, 1) * width
            y = point.y / max(self.instance.height, 1) * height
            x, y = min(max(x, 0), width - 1), min(max(y, 0), height - 1)
            if point.pressure > 0:
                action = ACTION_MOVE if point.identifier in self.held else ACTION_DOWN
                self.held[point.identifier] = (x, y)
                messages.append(touch_message(action, point.identifier, x, y, width, height, 1.0))
            elif point.identifier in self.held:
                last = self.held.pop(point.identifier)
                # A release reported at 0,0 (the mouse letting go) lifts the finger where it was
                if point.x == 0 and point.y == 0:
                    x, y = last
                messages.append(touch_message(ACTION_UP, point.identifier, x, y, width, height, 0.0))
        return messages

    def key_messages(self, key):
        if key.text and not key.key:
            return text_messages(key.text)
        code = KEYCODES.get(key.key) or KEYCODES.get(key.key.lower() if len(key.key) == 1 else "")
        if code is None:
            return text_messages(key.key) if len(key.key) == 1 and key.eventType != pb.KeyboardEvent.keyup else []
        messages = []
        if key.eventType in (pb.KeyboardEvent.keydown, pb.KeyboardEvent.keypress):
            if key.key in META:
                self.meta |= META[key.key]
            messages.append(keycode_message(ACTION_DOWN, code, meta=self.meta))
        if key.eventType in (pb.KeyboardEvent.keyup, pb.KeyboardEvent.keypress):
            if key.key in META:
                self.meta &= ~META[key.key]
            messages.append(keycode_message(ACTION_UP, code, meta=self.meta))
        return messages

    # The screen

    def watch(self, width, height, on_frame, wanted=None):
        # One stream runs for as long as the phone is connected. A new viewer just starts receiving it, beginning
        # with the last frame so a still screen isn't blank
        self.target = (width, height)
        self.wanted = wanted
        self.on_frame = on_frame
        latest = self.latest
        if latest:
            threading.Thread(target=lambda: self.show(*latest), daemon=True).start()

    def unwatch(self):
        self.on_frame = None
        self.wanted = None
        self.target = None

    def screencap(self, timeout=20):
        result = subprocess.run(adb_command(self.instance.serial, "exec-out", "screencap", "-p"),
                                capture_output=True, timeout=timeout, env=emulator.environment(),
                                **native.quiet_options())
        if result.returncode != 0 or not result.stdout.startswith(b"\x89PNG"):
            raise OSError("The phone didn't send a screenshot")
        return result.stdout

    def screenshot(self):
        return self.screencap()

    def scaled(self, width, height):
        """The last streamed frame, scaled to fit width by height, as a QImage"""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
        latest = self.latest
        if not latest:
            image = QImage()
            image.loadFromData(self.screencap(8))
        else:
            data, frame_width, frame_height = latest
            image = QImage(data, frame_width, frame_height, frame_width * 3, QImage.Format.Format_RGB888).copy()
        return image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)

    def thumbnail(self, width, height):
        from PySide6.QtCore import QBuffer, QIODevice
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.scaled(width, height).save(buffer, "PNG")
        return bytes(buffer.data())

    def pixels(self, width, height):
        from PySide6.QtGui import QImage
        image = self.scaled(width, height).convertToFormat(QImage.Format.Format_RGB888)
        rows = b"".join(bytes(image.constScanLine(line))[:image.width() * 3] for line in range(image.height()))
        return rows, image.width(), image.height()

    # The rest of what Bridge offers

    def rotate(self, degrees):
        self.session.send(rotate_message())

    def rotation(self):
        width, height = self.frame_size
        return 90 if width > height else 0

    def tilt(self, pitch, turn, base):
        # A real phone has its own motion sensors; there is nothing to fake
        pass

    def shake(self):
        pass

    def locate(self, latitude, longitude, speed=0.0, bearing=0.0):
        # A real phone has its own GPS
        pass

    def set_clipboard(self, text):
        self.session.send(set_clipboard_message(text))

    def watch_clipboard(self, on_text):
        self.on_clipboard = on_text

    def screen_off(self):
        """Turns the phone's own screen off while it keeps streaming"""
        self.session.send(display_power_message(False))

    def close(self):
        self.closed = True
        self.unwatch()
        self.outbox.put(None)
        threading.Thread(target=self.session.close, daemon=True).start()


# Finding phones

def devices():
    """[(serial, description)] for every phone adb can use, emulators left out"""
    code, output = emulator.run([str(paths.ADB), "devices", "-l"], 15)
    if code != 0:
        return []
    found = []
    for line in output.splitlines():
        parts = line.split()
        # adb also prints a heading and, when its server wasn't running, lines about starting it
        if len(parts) < 2 or line.startswith(("*", "List of")) or parts[0].startswith("emulator-"):
            continue
        serial, state = parts[0], parts[1]
        details = dict(part.split(":", 1) for part in parts[2:] if ":" in part)
        name = details.get("model", serial).replace("_", " ")
        found.append((serial, state, name))
    return found


def connect(address):
    """(ok, message) for adb connecting to a phone over Wi-Fi at host:port"""
    address = address.strip()
    if ":" not in address:
        address += ":5555"
    code, output = emulator.run([str(paths.ADB), "connect", address], 20)
    ok = code == 0 and ("connected to" in output) and "failed" not in output and "cannot" not in output
    return ok, emulator.last_line(output)


def pair(address, code):
    """(ok, message) for Android 11+'s wireless debugging pairing, with the six-digit code the phone shows"""
    result, output = emulator.run([str(paths.ADB), "pair", address.strip(), code.strip()], 30)
    return result == 0 and "Successfully paired" in output, emulator.last_line(output)


def screen_size(serial):
    """(width, height, density) of the phone in its natural (portrait) orientation"""
    code, output = emulator.run(adb_command(serial, "shell", "wm size && wm density"), 15)
    if code != 0:
        return None
    sizes = [line.split(":")[-1].strip() for line in output.splitlines() if "size" in line.lower()]
    densities = [line.split(":")[-1].strip() for line in output.splitlines() if "density" in line.lower()]
    if not sizes:
        return None
    # An "Override size" line comes after the physical one and is what the screen really uses
    width, _, height = sizes[-1].partition("x")
    density = densities[-1] if densities else "420"
    try:
        width, height, density = int(width), int(height), int(density)
    except ValueError:
        return None
    return min(width, height), max(width, height), density


def android_version(serial):
    code, output = emulator.run(adb_command(serial, "shell", "getprop", "ro.build.version.release"), 10)
    return output.strip() if code == 0 else ""


class RealPhone(emulator.Emulator):
    """The part of Emulator a real phone can do. Everything that goes through adb works as it is; what needs the
    emulator's console or its process (snapshots, network shaping, ad blocking by DNS, eco mode) does nothing"""
    REMOTE_RECORDING = "/sdcard/androidbox-recording.mp4"

    def __init__(self, instance):
        super().__init__(instance)
        self.active = False
        self.recorder = None

    @property
    def wireless(self):
        return ":" in self.instance.device

    def start(self, wipe=False, fresh=False):
        self.active = True
        self.started = time.monotonic()
        if self.wireless:
            threading.Thread(target=lambda: connect(self.instance.device), daemon=True).start()

    def stop(self):
        self.active = False
        self.stop_screen_recorder()
        if self.wireless:
            emulator.run([str(paths.ADB), "disconnect", self.instance.device], 10)

    def running(self):
        if not self.active:
            return False
        code, output = self.adb("get-state", timeout=5)
        return code == 0 and output.strip() == "device"

    def booted(self):
        code, output = self.adb("shell", "getprop", "sys.boot_completed", timeout=5)
        return code == 0 and output.strip() == "1"

    def fully_stopped(self):
        return not self.active

    def crashed(self):
        return False

    def stuck(self):
        return False

    def grpc_token(self):
        return "phone" if self.active else None

    def usage(self):
        return None

    def set_priority(self, eco):
        pass

    def set_network(self, profile):
        return False

    def block_ads(self, enabled):
        # Ad blocking changes the phone's private DNS, which is the owner's own setting on a real phone
        pass

    def map_gamepad(self):
        pass

    def set_frame_rate(self, fps):
        # The phone's refresh rate is its owner's setting too
        pass

    def keep_awake(self):
        self.adb("shell", "input", "keyevent", "KEYCODE_WAKEUP", timeout=10)

    def snapshots(self):
        return []

    def save_snapshot(self, name):
        return False

    def load_snapshot(self, name):
        return False

    def delete_snapshot(self, name):
        return False

    def kill(self):
        pass

    def qemu_pid(self):
        return None

    @property
    def recording(self):
        return paths.DATA / f"{self.instance.id}.mp4"

    def start_recording(self):
        self.stop_screen_recorder()
        self.adb("shell", "rm", "-f", self.REMOTE_RECORDING, timeout=10)
        self.recorder = subprocess.Popen(
            adb_command(self.instance.serial, "shell", "screenrecord", "--time-limit", "180", self.REMOTE_RECORDING),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=emulator.environment(), **native.quiet_options())
        time.sleep(1)
        return self.recorder.poll() in (None, 0)

    def stop_screen_recorder(self):
        recorder, self.recorder = self.recorder, None
        if recorder and recorder.poll() is None:
            # screenrecord only finishes the file when it is interrupted, not when adb is killed
            self.adb("shell", "pkill", "-INT", "screenrecord", timeout=10)
            with contextlib.suppress(subprocess.TimeoutExpired):
                recorder.wait(timeout=10)
            if recorder.poll() is None:
                recorder.kill()

    def stop_recording(self, destination):
        self.stop_screen_recorder()
        time.sleep(0.5)
        ok, _ = self.pull(self.REMOTE_RECORDING, destination)
        self.adb("shell", "rm", "-f", self.REMOTE_RECORDING, timeout=10)
        return ok and destination.exists()
