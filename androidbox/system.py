import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import native, paths

if native.WINDOWS:
    import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Androidbox"
OLD_RUN_NAME = "DroidCore"
RESERVED_MEMORY = 4096
# What opens Androidbox at sign-in is called by this name in the settings, and a shortcut file ends like this
SIGN_IN_NAME = "Windows" if native.WINDOWS else "your desktop"
SHORTCUT_SUFFIX = ".lnk" if native.WINDOWS else ".desktop"
AUTOSTART_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "androidbox.desktop"

host_memory = native.host_memory
process_times = native.process_times
process_memory = native.process_memory


def host_cores():
    return os.cpu_count() or 4


def free_gigabytes(folder):
    """Free space on the drive a folder is (or would be) on, in GB; a huge number if it can't be told"""
    try:
        anchor = Path(folder)
        while not anchor.exists() and anchor != anchor.parent:
            anchor = anchor.parent
        return shutil.disk_usage(anchor).free / (1 << 30)
    except OSError:
        return 1 << 20


def suggested_hardware():
    # Half the PC's threads and a quarter of its memory leaves the PC plenty
    cores = max(2, min(8, host_cores() // 2 // 2 * 2))
    memory = host_memory()
    ram = 8192 if memory >= 24576 else 6144 if memory >= 16384 else 4096 if memory >= 8192 else 3072 if memory >= 6144 \
        else 2048
    return cores, ram


def core_options(current):
    options = {count for count in (1, 2, 3, 4, 6, 8, 10, 12, 16, 24, 32) if count <= host_cores()}
    return sorted(options | {current})


def memory_options(current):
    limit = max(host_memory() - RESERVED_MEMORY, 2048)
    options = {size for size in (2048, 3072, 4096, 6144, 8192, 12288, 16384, 24576, 32768) if size <= limit}
    return sorted(options | {current})


def launcher():
    # What starts Androidbox: its exe once installed, or pythonw and the script when run from source. On Linux it is
    # the `androidbox` command the install puts on the path (which says where it is in ANDROIDBOX_COMMAND),
    # or Python and the script
    if not native.WINDOWS and os.environ.get("ANDROIDBOX_COMMAND"):
        return os.environ["ANDROIDBOX_COMMAND"], ""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    if native.WINDOWS:
        python = Path(sys.executable).with_name("pythonw.exe")
        script = paths.BUNDLE / "Androidbox.pyw"
        return str(python if python.exists() else sys.executable), f'"{script}"'
    return sys.executable, shlex.quote(str(paths.BUNDLE / "Androidbox.pyw"))


def command(*arguments):
    target, prefix = launcher()
    if native.WINDOWS:
        return " ".join([f'"{target}"', *([prefix] if prefix else []), *arguments])
    return " ".join([shlex.quote(target), *([prefix] if prefix else []), *map(shlex.quote, arguments)])


def desktop_entry(name, exec_line, description, extra=""):
    # In an Exec line a literal percent sign is written twice, because a single one starts a field code
    return ("[Desktop Entry]\nType=Application\nVersion=1.0\n"
            f"Name={name}\nComment={description}\nExec={exec_line.replace('%', '%%')}\nIcon={paths.ICON}\n"
            f"Terminal=false\nCategories=Game;Emulator;\nStartupWMClass=Androidbox\n{extra}")


def starts_with_windows():
    if not native.WINDOWS:
        return AUTOSTART_FILE.is_file()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            try:
                winreg.QueryValueEx(key, RUN_NAME)
                return True
            except FileNotFoundError:
                winreg.QueryValueEx(key, OLD_RUN_NAME)
        # Set up under the DroidCore name: move it back to this one
        start_with_windows(True)
        return True
    except OSError:
        return False


def start_with_windows(enabled):
    if not native.WINDOWS:
        if enabled:
            paths.write_text(AUTOSTART_FILE, desktop_entry("Androidbox", command("--background"),
                                                          "Android on your PC", "X-GNOME-Autostart-enabled=true\n"),
                             encoding="utf-8")
        else:
            AUTOSTART_FILE.unlink(missing_ok=True)
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command("--background"))
        for name in ((OLD_RUN_NAME,) if enabled else (RUN_NAME, OLD_RUN_NAME)):
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def shortcut(file, arguments, description):
    if not native.WINDOWS:
        file = Path(file)
        paths.write_text(file, desktop_entry(file.stem, command(*arguments), description), encoding="utf-8")
        # A desktop only trusts a launcher left on it once it is marked as runnable
        file.chmod(0o755)
        return
    target, prefix = launcher()
    script = ("$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SHORTCUT_FILE); "
              "$link.TargetPath = $env:SHORTCUT_TARGET; $link.Arguments = $env:SHORTCUT_ARGUMENTS; "
              "$link.Description = $env:SHORTCUT_TEXT; $link.IconLocation = $env:SHORTCUT_ICON; "
              "$link.WorkingDirectory = $env:SHORTCUT_FOLDER; $link.Save()")
    # Passed as environment variables so that no quoting can break a path or a game's name
    settings = {"SHORTCUT_FILE": str(file), "SHORTCUT_TARGET": target,
                "SHORTCUT_ARGUMENTS": " ".join([prefix, *arguments]).strip(), "SHORTCUT_TEXT": description,
                "SHORTCUT_ICON": str(paths.ICON), "SHORTCUT_FOLDER": str(Path(target).parent)}
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            text=True, env={**os.environ, **settings}, creationflags=native.NO_WINDOW)
    if result.returncode:
        raise OSError(result.stderr.strip() or "Windows couldn't create the shortcut")


def after_exit(script, settings, patience=120):
    """Runs commands once this process has ended, so they never meet its single-instance lock.

    If this process is still around after `patience` seconds (a hung shutdown), it's ended so the commands still run.
    On Windows these are PowerShell commands, and DETACHED_PROCESS would stop PowerShell from starting at all, and
    the helper doesn't need it to outlive us. On Linux they are shell commands."""
    environment = {**os.environ, "ANDROIDBOX_WAIT_FOR": str(os.getpid()), **settings}
    if not native.WINDOWS:
        wait = ('n=0; while kill -0 "$ANDROIDBOX_WAIT_FOR" 2>/dev/null && [ "$n" -lt ' + str(patience * 5) + ' ]; '
                'do sleep 0.2; n=$((n + 1)); done; kill -9 "$ANDROIDBOX_WAIT_FOR" 2>/dev/null; ')
        subprocess.Popen(["sh", "-c", wait + script], env=environment, close_fds=True, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
                      f"Wait-Process -Id $env:ANDROIDBOX_WAIT_FOR -Timeout {patience} -ErrorAction SilentlyContinue; "
                      "Stop-Process -Id $env:ANDROIDBOX_WAIT_FOR -Force -ErrorAction SilentlyContinue; " + script],
                     env=environment, close_fds=True,
                     creationflags=native.NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)


START_AGAIN = ("if ($env:RELAUNCH_ARGUMENTS) "
               "{ Start-Process -FilePath $env:RELAUNCH_TARGET -ArgumentList $env:RELAUNCH_ARGUMENTS } "
               "else { Start-Process -FilePath $env:RELAUNCH_TARGET }")
# The arguments are already shell-quoted by launcher(), so they are left for the shell to split again
START_AGAIN_SH = 'eval "exec \\"\\$RELAUNCH_TARGET\\" $RELAUNCH_ARGUMENTS" >/dev/null 2>&1'


def restart(relaunch=None):
    target, prefix = relaunch or launcher()
    after_exit(START_AGAIN if native.WINDOWS else START_AGAIN_SH,
               {"RELAUNCH_TARGET": target, "RELAUNCH_ARGUMENTS": prefix})


def can_update():
    # Only the installed Windows app updates itself. A copy run from source is updated with git, and on Linux
    # the system (SparkOS, or a package) brings new versions
    return native.WINDOWS and bool(getattr(sys, "frozen", False))


def install_update(installer, relaunch=None):
    """Once this copy has quit, runs the new installer and starts Androidbox again.

    Windows asks permission when Androidbox is in Program Files. If that's refused, or the install fails, the
    copy that was already there starts again, and the update is offered next time."""
    if not native.WINDOWS:
        raise OSError("Androidbox updates itself only on Windows")
    target, prefix = relaunch or launcher()
    install = ("Start-Process -FilePath $env:UPDATE_INSTALLER -ArgumentList '/SILENT','/SUPPRESSMSGBOXES','/NORESTART' "
               "-Wait -ErrorAction SilentlyContinue; ")
    after_exit(install + START_AGAIN, {"UPDATE_INSTALLER": str(installer), "RELAUNCH_TARGET": target,
                                       "RELAUNCH_ARGUMENTS": prefix}, patience=45)
