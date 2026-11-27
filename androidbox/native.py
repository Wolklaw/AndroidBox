"""Everything that differs between Windows and Linux, so the rest of Androidbox never asks which one it is on.

Each function has a Windows branch (the original behaviour, moved here unchanged) and a Linux one."""
import contextlib
import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")

# creationflags for a child process that must not open a console window. Zero (accepted everywhere) elsewhere
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Where Linux keeps what it knows about processes. A variable so that tests can point it at made-up ones
PROC = Path("/proc")

if WINDOWS:
    from ctypes import wintypes


def exe(name):
    return f"{name}.exe" if WINDOWS else name


def child_options():
    """Popen/run options that keep a child from showing a console on Windows, and on Linux put it in a session
    of its own so that it and everything it starts can be ended together"""
    return {"creationflags": NO_WINDOW} if WINDOWS else {"start_new_session": True}


def quiet_options():
    """For a short command that is waited for: no console window on Windows, nothing special on Linux"""
    return {"creationflags": NO_WINDOW} if WINDOWS else {}


# --- processes -------------------------------------------------------------------------------------------------

def process_alive(pid):
    if WINDOWS:
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        # A process that has ended but not been collected yet is still listed, and is not running
        return _stat_fields(pid)[0] != "Z"
    except (OSError, IndexError):
        return True


def kill_tree(pid):
    """Ends a process and the ones it started"""
    if WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
        return
    try:
        group = os.getpgid(pid)
    except OSError:
        return
    try:
        # Only a group Androidbox started for the emulator: never its own, which would end Androidbox with it
        if group != os.getpgrp():
            os.killpg(group, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def set_priority(pid, eco):
    if WINDOWS:
        handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, pid)
        if handle:
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x4000 if eco else 0x20)
            ctypes.windll.kernel32.CloseHandle(handle)
        return
    try:
        _set_cpu_weight(pid, eco)
    except (OSError, ValueError):
        # No systemd user manager to ask. Raising a process's niceness is always allowed, lowering it again needs a
        # privilege a normal user hasn't got, so then Eco takes effect at once but is only undone for the next start
        with contextlib.suppress(OSError):
            os.setpriority(os.PRIO_PROCESS, pid, 10 if eco else 0)


SYSTEMD = ("org.freedesktop.systemd1", "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager")
ECO_WEIGHT, NORMAL_WEIGHT = 20, 100


def _set_cpu_weight(pid, eco):
    """Puts the process in a systemd scope of its own and sets that scope's share of the processor. Unlike
    niceness, the share can be raised again without root, so Eco can be turned off while Android runs"""
    from . import dbus
    from .dbus import Variant
    bus = dbus.session()
    name = f"androidbox-emulator-{pid}.scope"
    weight = [("CPUWeight", Variant("t", ECO_WEIGHT if eco else NORMAL_WEIGHT))]
    try:
        bus.call(*SYSTEMD, "SetUnitProperties", "sba(sv)", (name, True, weight))
    except dbus.DBusError as error:
        if error.name != "org.freedesktop.systemd1.NoSuchUnit":
            raise
        bus.call(*SYSTEMD, "StartTransientUnit", "ssa(sv)a(sa(sv))", (name, "fail", [
            ("Description", Variant("s", "Android started by Androidbox")),
            ("PIDs", Variant("au", [pid])), *weight], []))


def _stat_fields(pid):
    """The fields of /proc/<pid>/stat after the process name, which can contain spaces and brackets"""
    text = (PROC / str(pid) / "stat").read_text()
    return text[text.rindex(")") + 2:].split()


def process_times(pid):
    """Processor seconds the process has used so far, or None if it can't be read"""
    if WINDOWS:
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        try:
            ok = ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                                        ctypes.byref(kernel), ctypes.byref(user))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        if not ok:
            return None
        ticks = lambda value: (value.dwHighDateTime << 32 | value.dwLowDateTime) / 1e7
        return ticks(kernel) + ticks(user)
    try:
        fields = _stat_fields(pid)
        # Counted from the state field (index 0): utime and stime are the 12th and 13th after it
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return None


def process_memory(pid):
    """Bytes of memory the process holds in RAM, or None"""
    if WINDOWS:
        class ProcessMemory(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD), ("peak", ctypes.c_size_t),
                        ("working_set", ctypes.c_size_t), ("pool_peak", ctypes.c_size_t), ("pool", ctypes.c_size_t),
                        ("nonpaged_peak", ctypes.c_size_t), ("nonpaged", ctypes.c_size_t),
                        ("pagefile", ctypes.c_size_t), ("pagefile_peak", ctypes.c_size_t)]

        handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
        if not handle:
            return None
        counters = ProcessMemory()
        counters.size = ctypes.sizeof(counters)
        try:
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.size)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        return counters.working_set if ok else None
    try:
        return int((PROC / str(pid) / "statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        return None


def host_memory():
    """The PC's memory in MB"""
    if WINDOWS:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD), ("total", ctypes.c_ulonglong),
                        ("free", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                        ("page_free", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                        ("virtual_free", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.total // (1 << 20)
    try:
        for line in (PROC / "meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 8192


# --- Windows crash boxes (there is nothing like them on Linux) -------------------------------------------------

@contextlib.contextmanager
def without_crash_dialogs():
    # Child processes inherit the error mode: a qemu crash then ends the process instead of
    # leaving a "Fail Fast Exception" box that nobody can see waiting behind the windows
    if not WINDOWS:
        yield
        return
    kernel32 = ctypes.windll.kernel32
    previous = kernel32.SetErrorMode(0)
    kernel32.SetErrorMode(previous | 0x0003)  # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX
    try:
        yield
    finally:
        kernel32.SetErrorMode(previous)


def close_crash_dialogs():
    """Closes any Windows crash box that a qemu process has left on screen. Windows shows one for a fail fast
    crash whatever the error mode says, and the process stays frozen behind it until somebody clicks OK"""
    if not WINDOWS:
        return False
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(window, _):
        if user32.IsWindowVisible(window):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(window, title, 256)
            if title.value.lower().startswith("qemu-system"):
                found.append(window)
        return True

    user32.EnumWindows(visit, 0)
    for window in found:
        user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE
    return bool(found)


def exclude_from_error_reporting():
    # The emulator installs its own crash handler, which can undo the error mode above, so also tell Windows
    # not to show its error dialog for qemu (per user, no admin needed)
    if not WINDOWS:
        return
    try:
        wer = ctypes.windll.wer
        for name in ("qemu-system-x86_64-headless.exe", "qemu-system-x86_64.exe"):
            wer.WerAddExcludedApplication(name, False)
    except (OSError, AttributeError):
        pass


def short_path(path):
    """A path without spaces or non-ASCII letters, for the emulator's console, which takes one word"""
    if not WINDOWS:
        return str(path)
    buffer = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value or str(path)


# --- the desktop -----------------------------------------------------------------------------------------------

def animations_allowed():
    if not WINDOWS:
        return _desktop_animations()
    on = ctypes.c_int(1)
    try:
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)  # SPI_GETCLIENTAREAANIMATION
    except (AttributeError, OSError):
        pass
    return bool(on.value)


# The desktop's animation setting, read through the portal on a thread so a slow portal never holds up a window.
# The first time it waits a moment for the answer. Wherever the desktop doesn't say, animations are on
_animations = {"on": True, "asked": None}
ANIMATIONS_RECHECK = 30
FIRST_ANSWER_WAIT = 0.5


def _desktop_animations():
    now = time.monotonic()
    first = _animations["asked"] is None
    if first or now - _animations["asked"] > ANIMATIONS_RECHECK:
        _animations["asked"] = now
        reader = threading.Thread(target=_read_desktop_animations, name="animations", daemon=True)
        reader.start()
        if first:
            reader.join(FIRST_ANSWER_WAIT)
    return _animations["on"]


def _read_desktop_animations():
    try:
        from . import dbus
        bus = dbus.portal()
    except (OSError, ValueError):
        return
    # GNOME and desktops that follow its settings, then KDE, where a duration factor of 0 means no animations
    for namespace, key, means_on in (("org.gnome.desktop.interface", "enable-animations", bool),
                                     ("org.kde.kdeglobals.KDE", "AnimationDurationFactor", lambda factor: factor > 0)):
        try:
            value = bus.call(dbus.PORTAL, dbus.PORTAL_PATH, "org.freedesktop.portal.Settings", "ReadOne", "ss",
                             (namespace, key), timeout=5)[0]
            _animations["on"] = bool(means_on(value))
            return
        except (OSError, ValueError, TypeError):
            continue


def raise_window(handle):
    """Brings a top level window to the front. On Linux the window manager decides, and Qt's own raise does it"""
    if WINDOWS:
        ctypes.windll.user32.SetForegroundWindow(int(handle))


def style_title_bar(handle, color):
    """Dark title bar in the theme's colour on Windows. Elsewhere the desktop draws the title bar"""
    if not WINDOWS:
        return
    for attribute, value in ((20, 1), (35, color.red() | color.green() << 8 | color.blue() << 16)):
        data = ctypes.c_int(value)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(handle), attribute, ctypes.byref(data), ctypes.sizeof(data))


def open_file(path):
    """Opens a file in whatever the desktop uses for it"""
    if WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", str(path)], start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


_lock_file = None


def another_copy_running(name):
    """True if another Androidbox already holds this name. The lock lasts as long as this process does"""
    global _lock_file
    if WINDOWS:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW(None, False, f"Local\\{name}")
        return ctypes.get_last_error() == 183
    import fcntl
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    try:
        _lock_file = open(runtime / f"{name}-{os.getuid()}.lock", "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    return False


def show_existing_window(title):
    """Brings another running copy's window to the front when it can't be reached any other way"""
    if WINDOWS:
        window = ctypes.windll.user32.FindWindowW(None, title)
        if window:
            ctypes.windll.user32.ShowWindow(window, 9)
            ctypes.windll.user32.SetForegroundWindow(window)


def name_process(app, title):
    """Gives the taskbar the name and icon to group this app's windows under"""
    if WINDOWS:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(title)
    else:
        # Wayland names the window after this, and the desktop finds the icon by the .desktop file of the same name
        app.setDesktopFileName("dev.wolklaw.Androidbox")
        # Asks the desktop about animations now, before the first window needs the answer
        animations_allowed()


def show_error_box(title, text):
    if WINDOWS:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
        return
    for command in (["kdialog", "--error", text, "--title", title], ["zenity", "--error", "--text", text,
                                                                     "--title", title]):
        try:
            subprocess.run(command, timeout=300)
            return
        except (OSError, subprocess.SubprocessError):
            continue
    print(f"{title}: {text}", file=sys.stderr)
