import os
import sys
import tempfile
from pathlib import Path

from . import native
from .native import WINDOWS, exe

# Where per-user program data lives: %LOCALAPPDATA% on Windows, ~/.local/share (XDG) on Linux
if WINDOWS:
    LOCAL = Path(os.environ["LOCALAPPDATA"])
else:
    LOCAL = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
DEFAULT_HOME = LOCAL / "Androidbox"
# 1.9.0 and 1.9.1 were briefly released as DroidCore. Their folder is renamed back in place (instant on one
# drive), so nothing downloaded or created under that name is lost. If it is locked, it keeps being used
_RENAMED_HOME = LOCAL / "DroidCore"
MIGRATED = False
if not DEFAULT_HOME.exists() and _RENAMED_HOME.is_dir():
    try:
        _RENAMED_HOME.rename(DEFAULT_HOME)
        MIGRATED = True
    except OSError:
        DEFAULT_HOME = _RENAMED_HOME
# The folder Androidbox keeps its files in can be moved to another drive. Where it went is written here,
# and this one file always stays in the default folder
LOCATION = DEFAULT_HOME / "location.txt"
CLEANUP = DEFAULT_HOME / "cleanup.txt"


def chosen_home():
    # ANDROIDBOX_HOME is for development and tests
    override = os.environ.get("ANDROIDBOX_HOME")
    if override:
        return Path(override)
    try:
        text = LOCATION.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_HOME
    return Path(text) if text else DEFAULT_HOME


HOME = chosen_home()
SDK = HOME / "sdk"
DATA = HOME / "data"
DOWNLOADS = HOME / "downloads"

AVD_HOME = DATA / "avd"
LOGS = DATA / "logs"
PROFILES = DATA / "profiles"
PROFILE_STATE = DATA / "profile.json"
LEGACY_KEYMAPS = DATA / "keymaps"
LEGACY_MACROS = DATA / "macros"
INSTANCES = DATA / "instances.json"
SETTINGS = DATA / "settings.json"
CRASH_LOG = DATA / "crash.log"
# Screen frames shared with the emulator. Emulator 37.3 refuses shared memory outside its own temp folder
FRAMES = Path(tempfile.gettempdir()) / "AndroidEmulator"

EMULATOR = SDK / "emulator" / exe("emulator")
LEGACY_EMULATOR = SDK / "emulator-legacy" / exe("emulator")
ADB = SDK / "platform-tools" / exe("adb")


def discovery_folders():
    """Where a running emulator leaves its pid_*.ini file, with the port and gRPC token Androidbox looks for"""
    found = {Path(tempfile.gettempdir()) / "avd" / "running"}
    if native.WINDOWS:
        found.add(LOCAL / "Temp" / "avd" / "running")
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime:
            found.add(Path(runtime) / "avd" / "running")
        found.add(Path(f"/tmp/android-{os.environ.get('USER') or os.getuid()}") / "avd" / "running")
        found.add(Path.home() / ".android" / "avd" / "running")
    return found


DISCOVERY = discovery_folders()
CONSOLE_TOKEN = Path.home() / ".emulator_console_auth_token"

BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ICON = BUNDLE / "assets" / ("androidbox.ico" if WINDOWS else "androidbox.png")


def write_text(path, text, encoding=None):
    # Written beside the file and swapped in, so a crash or a full disk half way never leaves it cut short
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding=encoding)
    temporary.replace(path)


def moved():
    return HOME != DEFAULT_HOME


def home_missing():
    return moved() and not HOME.is_dir()
