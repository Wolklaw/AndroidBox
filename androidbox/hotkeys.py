"""Shortcuts that work while another program has the keyboard: the boss key and macros set to work in any program.

On Windows they are registered with RegisterHotKey. On Linux the first of these that works is used:

- the desktop's GlobalShortcuts portal (KDE Plasma, GNOME 48 and later, Hyprland and others). The desktop owns the
  shortcut, and may ask the user to confirm it or let them pick other keys in its settings
- in an X11 session, a key grab on the root window, the way X11 programs have always done it
- the keyboards themselves, /dev/input, when this user may read them (members of the `input` group). This works
  under any Wayland desktop, but the key also still reaches the program in front

Where none works, every shortcut is refused and the ones inside Androidbox's own windows still work."""
import contextlib
import ctypes
import ctypes.util
import os
import re
import select
import struct
import threading
import time
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence

from .native import LINUX, WINDOWS

if WINDOWS:
    from ctypes import wintypes

WM_HOTKEY = 0x0312
NO_REPEAT = 0x4000
FIRST_ID = 0x4A00
MODIFIERS = {Qt.KeyboardModifier.AltModifier: 0x1, Qt.KeyboardModifier.ControlModifier: 0x2,
             Qt.KeyboardModifier.ShiftModifier: 0x4, Qt.KeyboardModifier.MetaModifier: 0x8}
SPECIAL_KEYS = {Qt.Key.Key_Backspace: 0x08, Qt.Key.Key_Tab: 0x09, Qt.Key.Key_Return: 0x0D, Qt.Key.Key_Enter: 0x0D,
                Qt.Key.Key_Escape: 0x1B, Qt.Key.Key_Space: 0x20, Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22,
                Qt.Key.Key_End: 0x23, Qt.Key.Key_Home: 0x24, Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26,
                Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28, Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Delete: 0x2E}

# Why shortcuts were refused, sent with the refused list
TAKEN = "taken"              # the system said no: the keys are taken, or need Ctrl, Alt, Shift or Win/Super
UNSUPPORTED = "unsupported"  # nothing on this desktop lets a program listen for them
DECLINED = "declined"        # the desktop asked the user, and they said no


def virtual_key(key):
    code = int(key)
    if 0x30 <= code <= 0x39 or 0x41 <= code <= 0x5A:
        return code
    if int(Qt.Key.Key_F1) <= code <= int(Qt.Key.Key_F24):
        return 0x70 + code - int(Qt.Key.Key_F1)
    return SPECIAL_KEYS.get(key, 0)


def parse(text):
    """A shortcut such as Ctrl+Alt+B as Windows' modifiers and virtual key, or None if Windows can't take it"""
    sequence = QKeySequence(text)
    if sequence.isEmpty():
        return None
    combo = sequence[0]
    modifiers = sum(flag for modifier, flag in MODIFIERS.items() if combo.keyboardModifiers() & modifier)
    code = virtual_key(combo.key())
    return (modifiers, code) if code and modifiers else None


# --- the same shortcut in Linux's terms --------------------------------------------------------------------------

CTRL, ALT, SHIFT, SUPER = "CTRL", "ALT", "SHIFT", "LOGO"
QT_MODIFIERS = {Qt.KeyboardModifier.ControlModifier: CTRL, Qt.KeyboardModifier.AltModifier: ALT,
                Qt.KeyboardModifier.ShiftModifier: SHIFT, Qt.KeyboardModifier.MetaModifier: SUPER}
# X11 keysyms and their names for the keys a shortcut can use (the same keys as on Windows)
SPECIAL_KEYSYMS = {Qt.Key.Key_Backspace: (0xFF08, "BackSpace"), Qt.Key.Key_Tab: (0xFF09, "Tab"),
                   Qt.Key.Key_Return: (0xFF0D, "Return"), Qt.Key.Key_Enter: (0xFF0D, "Return"),
                   Qt.Key.Key_Escape: (0xFF1B, "Escape"), Qt.Key.Key_Space: (0x20, "space"),
                   Qt.Key.Key_PageUp: (0xFF55, "Page_Up"), Qt.Key.Key_PageDown: (0xFF56, "Page_Down"),
                   Qt.Key.Key_End: (0xFF57, "End"), Qt.Key.Key_Home: (0xFF50, "Home"),
                   Qt.Key.Key_Left: (0xFF51, "Left"), Qt.Key.Key_Up: (0xFF52, "Up"),
                   Qt.Key.Key_Right: (0xFF53, "Right"), Qt.Key.Key_Down: (0xFF54, "Down"),
                   Qt.Key.Key_Insert: (0xFF63, "Insert"), Qt.Key.Key_Delete: (0xFFFF, "Delete")}


def keysym(key):
    """The X11 keysym and its name for a Qt key, or None. Letters are the lowercase ones, which is what an
    unshifted key gives"""
    code = int(key)
    if 0x41 <= code <= 0x5A:
        return code + 0x20, chr(code + 0x20)
    if 0x30 <= code <= 0x39:
        return code, chr(code)
    if int(Qt.Key.Key_F1) <= code <= int(Qt.Key.Key_F24):
        number = code - int(Qt.Key.Key_F1)
        return 0xFFBE + number, f"F{number + 1}"
    return SPECIAL_KEYSYMS.get(key)


class Combo:
    """One shortcut: the text the settings keep, its modifiers, and its key"""
    __slots__ = ("text", "modifiers", "keysym", "name", "label")

    def __init__(self, text, modifiers, symbol, name, label):
        self.text, self.modifiers, self.keysym, self.name, self.label = text, modifiers, symbol, name, label

    @property
    def trigger(self):
        """As the XDG shortcuts specification writes it, such as CTRL+ALT+b"""
        return "+".join([*(flag for flag in (CTRL, ALT, SHIFT, SUPER) if flag in self.modifiers), self.name])

    @property
    def identifier(self):
        # Stays the same between sessions, so the desktop keeps what the user chose for it
        return re.sub(r"[^a-z0-9]+", "-", self.trigger.lower())


def combo(text, label=""):
    """A shortcut in Linux's terms, or None if it has no Ctrl, Alt, Shift or Super, or its key can't be used"""
    sequence = QKeySequence(text)
    if sequence.isEmpty():
        return None
    first = sequence[0]
    modifiers = frozenset(name for modifier, name in QT_MODIFIERS.items() if first.keyboardModifiers() & modifier)
    symbol = keysym(first.key())
    if not (modifiers and symbol):
        return None
    return Combo(text, modifiers, symbol[0], symbol[1], label or text)


# --- the desktop portal ------------------------------------------------------------------------------------------

GLOBAL_SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"


class PortalShortcuts:
    kind = "portal"
    passive = False
    tick = None

    def __init__(self, pressed):
        from . import dbus
        self.dbus = dbus
        self.bus = dbus.portal()
        # Raises if this desktop's portal has no GlobalShortcuts
        self.bus.get_property(dbus.PORTAL, dbus.PORTAL_PATH, GLOBAL_SHORTCUTS, "version")
        self.pressed = pressed
        self.session = None
        self.names = {}
        self.subscription = self.bus.subscribe(self.activated, GLOBAL_SHORTCUTS, "Activated")

    def activated(self, message):
        session, identifier = message.body[0], message.body[1]
        if session == self.session and identifier in self.names:
            self.pressed(self.names[identifier])

    def fds(self):
        return []

    def handle(self, ready):
        pass

    def close_session(self):
        session, self.session = self.session, None
        self.names = {}
        if session:
            with contextlib.suppress(OSError):
                self.bus.call(self.dbus.PORTAL, session, "org.freedesktop.portal.Session", "Close", timeout=2)

    def bind(self, combos):
        # A session's shortcuts are bound once, so a changed list gets a new session
        self.close_session()
        if not combos:
            return [], TAKEN
        everything = [item.text for item in combos]
        variant = self.dbus.Variant
        response, results = self.bus.portal_request(
            self.dbus.PORTAL_PATH, GLOBAL_SHORTCUTS, "CreateSession", "a{sv}",
            ({"session_handle_token": variant("s", f"androidbox{os.getpid()}")},), timeout=30)
        if response != 0 or "session_handle" not in results:
            return everything, DECLINED if response == 1 else TAKEN
        self.session = results["session_handle"]
        entries = [(item.identifier, {"description": variant("s", item.label),
                                      "preferred_trigger": variant("s", item.trigger)}) for item in combos]
        # The desktop may show a dialog here, so the user has time to answer
        response, results = self.bus.portal_request(
            self.dbus.PORTAL_PATH, GLOBAL_SHORTCUTS, "BindShortcuts", "oa(sa{sv})sa{sv}",
            (self.session, entries, "", {}), timeout=300)
        if response != 0:
            self.close_session()
            return everything, DECLINED if response == 1 else TAKEN
        bound = {entry[0] for entry in results.get("shortcuts", [])}
        self.names = {item.identifier: item.text for item in combos if item.identifier in bound}
        return [item.text for item in combos if item.identifier not in bound], TAKEN

    def close(self):
        self.close_session()
        with contextlib.suppress(OSError):
            self.bus.unsubscribe(self.subscription)


# --- X11 ---------------------------------------------------------------------------------------------------------

X_SHIFT, X_LOCK, X_CONTROL, X_MOD1, X_MOD2, X_MOD4 = 1, 2, 4, 8, 16, 64
X_MASKS = {SHIFT: X_SHIFT, CTRL: X_CONTROL, ALT: X_MOD1, SUPER: X_MOD4}
X_RELEVANT = X_SHIFT | X_CONTROL | X_MOD1 | X_MOD4
# Caps Lock and Num Lock change the modifier state, so each shortcut is also grabbed with them on
X_IGNORED = (0, X_LOCK, X_MOD2, X_LOCK | X_MOD2)
X_KEY_PRESS = 2
X_GRAB_ASYNC = 1


class XKeyEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
                ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong), ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("x_root", ctypes.c_int), ("y_root", ctypes.c_int), ("state", ctypes.c_uint),
                ("keycode", ctypes.c_uint), ("same_screen", ctypes.c_int)]


class XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xkey", XKeyEvent), ("pad", ctypes.c_long * 24)]


class XErrorEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("display", ctypes.c_void_p), ("resourceid", ctypes.c_ulong),
                ("serial", ctypes.c_ulong), ("error_code", ctypes.c_ubyte), ("request_code", ctypes.c_ubyte),
                ("minor_code", ctypes.c_ubyte)]


X_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))


def x11_session():
    """A real X11 session. Under Wayland, XWayland sees only the keys meant for X11 windows, so a grab there
    would only work while one of those is in front"""
    kind = os.environ.get("XDG_SESSION_TYPE", "")
    if kind == "x11":
        return True
    return kind != "wayland" and bool(os.environ.get("DISPLAY")) and not os.environ.get("WAYLAND_DISPLAY")


class X11Shortcuts:
    kind = "x11"
    passive = False
    tick = None

    def __init__(self, pressed):
        if not x11_session():
            raise OSError("Not an X11 session")
        x = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int]
        x.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x.XSetErrorHandler.restype = ctypes.c_void_p
        x.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        x.XPending.argtypes = [ctypes.c_void_p]
        x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
        x.XConnectionNumber.argtypes = [ctypes.c_void_p]
        x.XkbSetDetectableAutoRepeat.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.x = x
        # A connection of its own, used only from this thread, so Qt's is never touched
        self.display = x.XOpenDisplay(None)
        if not self.display:
            raise OSError("Couldn't open the X11 display")
        self.root = x.XDefaultRootWindow(self.display)
        # A held key then sends one press, not one every few milliseconds
        x.XkbSetDetectableAutoRepeat(self.display, 1, None)
        self.pressed = pressed
        self.grabs = {}

    def fds(self):
        return [self.x.XConnectionNumber(self.display)]

    def ungrab_all(self):
        for keycode, mask in self.grabs:
            for extra in X_IGNORED:
                self.x.XUngrabKey(self.display, keycode, mask | extra, self.root)
        self.x.XSync(self.display, 0)
        self.grabs = {}

    def grab(self, keycode, mask):
        """Grabs one key with every lock combination. False if another program already has it"""
        errors = []

        def failed(display, error):
            errors.append(error.contents.error_code)
            return 0

        handler = X_ERROR_HANDLER(failed)
        previous = self.x.XSetErrorHandler(ctypes.cast(handler, ctypes.c_void_p))
        try:
            for extra in X_IGNORED:
                self.x.XGrabKey(self.display, keycode, mask | extra, self.root, 0, X_GRAB_ASYNC, X_GRAB_ASYNC)
            self.x.XSync(self.display, 0)
        finally:
            self.x.XSetErrorHandler(previous)
        if errors:
            for extra in X_IGNORED:
                self.x.XUngrabKey(self.display, keycode, mask | extra, self.root)
            self.x.XSync(self.display, 0)
            return False
        return True

    def bind(self, combos):
        self.ungrab_all()
        refused = []
        for item in combos:
            keycode = self.x.XKeysymToKeycode(self.display, item.keysym)
            mask = sum(X_MASKS[name] for name in item.modifiers)
            if keycode and (keycode, mask) not in self.grabs and self.grab(keycode, mask):
                self.grabs[(keycode, mask)] = item.text
            else:
                refused.append(item.text)
        return refused, TAKEN

    def handle(self, ready):
        event = XEvent()
        while self.x.XPending(self.display):
            self.x.XNextEvent(self.display, ctypes.byref(event))
            if event.type == X_KEY_PRESS:
                text = self.grabs.get((event.xkey.keycode, event.xkey.state & X_RELEVANT))
                if text:
                    self.pressed(text)

    def close(self):
        with contextlib.suppress(OSError):
            self.ungrab_all()
        self.x.XCloseDisplay(self.display)


# --- the keyboards themselves ------------------------------------------------------------------------------------

INPUT = Path("/dev/input")
DEVICES = Path("/proc/bus/input/devices")
EVENT = struct.Struct("llHHi")
EV_KEY = 1
KEY_A = 30
KEY_MODIFIERS = {29: CTRL, 97: CTRL, 42: SHIFT, 54: SHIFT, 56: ALT, 100: ALT, 125: SUPER, 126: SUPER}
RESCAN = 5.0
# Linux key codes of keys that are in the same place on every layout, and of a US layout's letters and digits,
# for when libxkbcommon can't say where the user's layout has them
FIXED_CODES = {0xFF08: 14, 0xFF09: 15, 0xFF0D: 28, 0xFF1B: 1, 0x20: 57, 0xFF55: 104, 0xFF56: 109, 0xFF57: 107,
               0xFF50: 102, 0xFF51: 105, 0xFF52: 103, 0xFF53: 106, 0xFF54: 108, 0xFF63: 110, 0xFFFF: 111,
               **{0xFFBE + number: 59 + number for number in range(10)}, 0xFFC8: 87, 0xFFC9: 88,
               **{0xFFCA + number: 183 + number for number in range(12)}}
US_CODES = {**{ord(letter): code for row, first in (("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44))
               for code, letter in enumerate(row, first)},
            **{ord(digit): code for code, digit in enumerate("1234567890", 2)}}


def keyboards(devices=DEVICES):
    """The event files of the devices that are keyboards: they type, so they have an A key"""
    found = []
    try:
        text = devices.read_text()
    except OSError:
        return found
    word = struct.calcsize("l") * 8
    for block in text.split("\n\n"):
        handlers, keys = [], 0
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].split()
            elif line.startswith("B: KEY="):
                for part in line.split("=", 1)[1].split():
                    keys = (keys << word) | int(part, 16)
        if "kbd" in handlers and keys >> KEY_A & 1:
            found += [INPUT / name for name in handlers if name.startswith("event")]
    return found


def layout_names():
    """The keyboard layout the way libxkbcommon takes it: from its own variables, else the system's setting"""
    names = {key: os.environ.get(f"XKB_DEFAULT_{key.upper()}") for key in ("rules", "model", "layout", "variant",
                                                                          "options")}
    if not names["layout"]:
        with contextlib.suppress(OSError):
            config = Path("/etc/X11/xorg.conf.d/00-keyboard.conf").read_text()
            for key, option in (("layout", "XkbLayout"), ("variant", "XkbVariant"), ("model", "XkbModel"),
                                ("options", "XkbOptions")):
                found = re.search(rf'Option\s+"{option}"\s+"([^"]*)"', config)
                if found:
                    names[key] = found.group(1)
    return names


class RuleNames(ctypes.Structure):
    _fields_ = [(name, ctypes.c_char_p) for name in ("rules", "model", "layout", "variant", "options")]


def layout_codes():
    """{keysym: Linux key code} for the user's layout, from libxkbcommon. Empty if it isn't there"""
    codes = {}
    try:
        xkb = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
    except OSError:
        return codes
    xkb.xkb_context_new.restype = ctypes.c_void_p
    xkb.xkb_context_new.argtypes = [ctypes.c_int]
    xkb.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    xkb.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.POINTER(RuleNames), ctypes.c_int]
    xkb.xkb_keymap_min_keycode.restype = xkb.xkb_keymap_max_keycode.restype = ctypes.c_uint32
    xkb.xkb_keymap_min_keycode.argtypes = xkb.xkb_keymap_max_keycode.argtypes = [ctypes.c_void_p]
    xkb.xkb_keymap_key_get_syms_by_level.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                                     ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32))]
    xkb.xkb_keymap_unref.argtypes = xkb.xkb_context_unref.argtypes = [ctypes.c_void_p]
    context = xkb.xkb_context_new(0)
    if not context:
        return codes
    try:
        names = RuleNames(**{key: value.encode() if value else None for key, value in layout_names().items()})
        keymap = xkb.xkb_keymap_new_from_names(context, ctypes.byref(names), 0)
        if not keymap:
            return codes
        try:
            symbols = ctypes.POINTER(ctypes.c_uint32)()
            # The unshifted symbols first, so a key's own symbol wins over one it only gives with Shift
            for level in (0, 1):
                for keycode in range(xkb.xkb_keymap_min_keycode(keymap), xkb.xkb_keymap_max_keycode(keymap) + 1):
                    count = xkb.xkb_keymap_key_get_syms_by_level(keymap, keycode, 0, level, ctypes.byref(symbols))
                    for index in range(max(count, 0)):
                        # X11 key codes are Linux's plus 8
                        codes.setdefault(symbols[index], keycode - 8)
        finally:
            xkb.xkb_keymap_unref(keymap)
    finally:
        xkb.xkb_context_unref(context)
    return codes


def key_code(symbol, layout):
    return FIXED_CODES.get(symbol) or layout.get(symbol) or US_CODES.get(symbol)


class KeyboardShortcuts:
    kind = "keyboard"
    passive = True
    tick = RESCAN

    def __init__(self, pressed):
        self.pressed = pressed
        self.devices = {}
        self.held = set()
        self.table = {}
        self.scanned = 0.0
        self.layout = None
        # Every keyboard has to be readable. A device or two can be readable on its own (a gaming mouse's keys,
        # given to the user for its settings tool), and listening to just those would look like it works
        if self.rescan() or not self.devices:
            self.close()
            raise OSError("Not every keyboard can be read. Members of the input group can")

    def rescan(self):
        """Opens keyboards plugged in since, and lets go of ones that are gone. Returns how many couldn't be opened"""
        self.scanned = time.monotonic()
        present = set(keyboards())
        for path in list(self.devices):
            if path not in present:
                self.drop(path)
        unreadable = 0
        for path in present - set(self.devices):
            try:
                self.devices[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                unreadable += 1
        return unreadable

    def drop(self, path):
        with contextlib.suppress(OSError):
            os.close(self.devices.pop(path))

    def fds(self):
        return list(self.devices.values())

    def bind(self, combos):
        if self.layout is None:
            self.layout = layout_codes()
        table, refused = {}, []
        for item in combos:
            code = key_code(item.keysym, self.layout)
            if code and (item.modifiers, code) not in table:
                table[(item.modifiers, code)] = item.text
            else:
                refused.append(item.text)
        self.table = table
        return refused, TAKEN

    def handle(self, ready):
        for path, fd in list(self.devices.items()):
            if fd in ready:
                self.read(path, fd)
        if time.monotonic() - self.scanned > RESCAN:
            self.rescan()

    def read(self, path, fd):
        try:
            data = os.read(fd, EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            # Unplugged
            self.drop(path)
            return
        for _, _, kind, code, value in EVENT.iter_unpack(data[:len(data) - len(data) % EVENT.size]):
            if kind != EV_KEY:
                continue
            if code in KEY_MODIFIERS:
                if value == 1:
                    self.held.add(code)
                elif value == 0:
                    self.held.discard(code)
            elif value == 1:
                # 1 is a press, 0 a release and 2 the key repeating while held
                text = self.table.get((frozenset(KEY_MODIFIERS[held] for held in self.held), code))
                if text:
                    self.pressed(text)

    def close(self):
        for path in list(self.devices):
            self.drop(path)


BACKENDS = (PortalShortcuts, X11Shortcuts, KeyboardShortcuts)


class LinuxWorker:
    """A thread that picks the way to listen, applies each new list of shortcuts, and waits for key presses"""

    def __init__(self, pressed, done):
        self.pressed = pressed
        self.done = done
        self.backend = None
        self.chosen = False
        self.wanted = None
        self.lock = threading.Lock()
        self.wake_read, self.wake_write = os.pipe()
        os.set_blocking(self.wake_read, False)
        self.thread = None

    def request(self, combos):
        with self.lock:
            self.wanted = combos
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name="hotkeys", daemon=True)
                self.thread.start()
        os.write(self.wake_write, b"!")

    def choose(self):
        for backend in BACKENDS:
            try:
                return backend(self.pressed)
            except (OSError, ValueError, AttributeError):
                continue
        return None

    def apply(self, combos):
        if not self.chosen:
            self.backend = self.choose()
            self.chosen = True
        if not self.backend:
            return [item.text for item in combos], UNSUPPORTED
        try:
            return self.backend.bind(combos)
        except (OSError, ValueError):
            # The portal went away, say: the next list starts over with whatever works then
            with contextlib.suppress(OSError, ValueError):
                self.backend.close()
            self.backend, self.chosen = None, False
            return [item.text for item in combos], TAKEN

    def run(self):
        while True:
            watched = [self.wake_read, *(self.backend.fds() if self.backend else [])]
            try:
                ready, _, _ = select.select(watched, [], [], self.backend.tick if self.backend else None)
            except (OSError, ValueError):
                # A keyboard closed under us: look again
                ready = []
            if self.wake_read in ready:
                with contextlib.suppress(OSError):
                    while os.read(self.wake_read, 64):
                        pass
                with self.lock:
                    combos, self.wanted = self.wanted, None
                if combos is not None:
                    self.done(*self.apply(combos))
            if self.backend:
                try:
                    self.backend.handle(ready)
                except (OSError, ValueError):
                    pass


class WindowsHotkeys(QAbstractNativeEventFilter):
    def __init__(self, pressed):
        super().__init__()
        self.pressed = pressed
        self.names = {}

    def set(self, texts):
        """Registers the shortcuts, and returns the ones Windows refused, usually because they're taken"""
        for identifier in self.names:
            ctypes.windll.user32.UnregisterHotKey(None, identifier)
        self.names = {}
        refused = []
        for number, text in enumerate(texts):
            parsed = parse(text)
            identifier = FIRST_ID + number
            if parsed and ctypes.windll.user32.RegisterHotKey(None, identifier, parsed[0] | NO_REPEAT, parsed[1]):
                self.names[identifier] = text
            else:
                refused.append(text)
        return refused

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            event = wintypes.MSG.from_address(int(message))
            if event.message == WM_HOTKEY and event.wParam in self.names:
                self.pressed(self.names[event.wParam])
                return True, 0
        return False, 0


class Hotkeys(QObject):
    """set() takes {shortcut: callback}. The answer comes as refused(shortcuts that couldn't be taken, why), right
    away on Windows and once the desktop has answered on Linux. The callbacks run on the GUI thread"""
    refused = Signal(list, str)
    pressed = Signal(str)
    finished = Signal(list, str)

    def __init__(self, app):
        super().__init__()
        self.actions = {}
        self.windows = None
        self.linux = None
        self.invalid = []
        self.pressed.connect(self.fire)
        self.finished.connect(self.report)
        if WINDOWS:
            self.windows = WindowsHotkeys(self.pressed.emit)
            app.installNativeEventFilter(self.windows)
        elif LINUX:
            self.linux = LinuxWorker(self.pressed.emit, self.finished.emit)

    @property
    def kind(self):
        """How the shortcuts are listened for: windows, portal, x11, keyboard, or "" for not at all (or not yet)"""
        if self.windows:
            return "windows"
        backend = self.linux and self.linux.backend
        return backend.kind if backend else ""

    @property
    def passive(self):
        """The key also reaches the program in front, Androidbox included"""
        backend = self.linux and self.linux.backend
        return bool(backend and backend.passive)

    def set(self, wanted, labels=None):
        self.actions = dict(wanted)
        labels = labels or {}
        if self.windows:
            self.refused.emit(self.windows.set(list(wanted)), TAKEN)
        elif self.linux:
            combos = [combo(text, labels.get(text, "")) for text in wanted]
            self.invalid = [text for text, item in zip(wanted, combos) if item is None]
            if self.linux.thread is None and not wanted:
                # Nothing to listen for, and nothing listening yet: no thread, no portal, no answer to wait for
                self.refused.emit([], TAKEN)
                return
            self.linux.request([item for item in combos if item])
        else:
            self.refused.emit(list(wanted), UNSUPPORTED)

    def report(self, refused, why):
        if self.invalid and why != UNSUPPORTED:
            why = TAKEN
        self.refused.emit([*self.invalid, *refused], why)

    def fire(self, text):
        action = self.actions.get(text)
        if action:
            action()
