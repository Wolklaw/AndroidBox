"""The androidbox command: start, stop and use instances from a terminal or a script.

With the window open, starting and stopping is handed to it, so it shows what happens. Without it, the command
starts the emulator itself, the same way the window would, and leaves it running when it exits; the window picks
it up the next time it opens. Everything else (installing, screenshots, macros) talks to Android directly."""
import argparse
import html
import json
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import VERSION, emulator, installer, instances, macros, native, paths

TITLE = "Androidbox"
REQUESTS = "Androidbox-requests"
COMMANDS = ("list", "groups", "start", "stop", "wait", "install", "launch", "apps", "shell", "screenshot", "record",
            "macro")
BOOT_TIMEOUT = 300
STOP_TIMEOUT = 90
RECORD_LIMIT = 180


class Failure(Exception):
    """A problem worth one line on the terminal and an exit code of 1, not a traceback"""


def wanted(arguments):
    """Whether these command-line arguments are a command for this module rather than options for the window"""
    return bool(arguments) and (arguments[0] in COMMANDS or arguments[0] in ("help", "-h", "--help", "--version"))


def say(text):
    print(text, flush=True)


def window_open():
    return native.window_running(TITLE)


def send(request):
    """Hands a request to the open window, as a second copy of Androidbox would. False if it didn't answer"""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket
    QCoreApplication.instance() or QCoreApplication([])
    socket = QLocalSocket()
    socket.connectToServer(REQUESTS)
    if not socket.waitForConnected(3000):
        return False
    socket.write(json.dumps(request).encode())
    socket.waitForBytesWritten(3000)
    socket.disconnectFromServer()
    return True


def everything():
    # Only read: recovering lost instances and saving the list is the window's job
    return instances.load(repair=False)


def find(name, known=None):
    known = everything() if known is None else known
    wanted_name = name.lower()
    found = next((instance for instance in known if wanted_name in (instance.id.lower(), instance.name.lower())),
                 None)
    if not found:
        names = ", ".join(instance.name for instance in known) or "none yet"
        raise Failure(f"There's no instance called {name}. Instances: {names}")
    return found


def chosen(args):
    """The instances a start, stop or wait command is about: by name, by group, or all of them"""
    known = everything()
    if args.all:
        return known
    if args.group:
        members = [instance for instance in known if instance.group.lower() == args.group.lower()]
        if not members:
            groups = ", ".join(sorted({instance.group for instance in known if instance.group})) or "none yet"
            raise Failure(f"No instance is in a group called {args.group}. Groups: {groups}")
        return members
    if not args.names:
        raise Failure("Name an instance, or use --group or --all")
    return [find(name, known) for name in args.names]


def machine(instance):
    return emulator.Emulator(instance)


def phone_connected(instance):
    code, output = emulator.run([str(paths.ADB), "-s", instance.serial, "get-state"], timeout=10)
    return code == 0 and output.strip() == "device"


def state(instance):
    if instance.real:
        return "connected" if phone_connected(instance) else "not connected"
    running = machine(instance)
    if not running.running():
        return "off"
    return "on" if running.booted() else "starting"


def require_on(instance):
    if instance.real:
        if not phone_connected(instance):
            raise Failure(f"{instance.name} isn't connected")
        return machine(instance)
    running = machine(instance)
    if not running.running():
        raise Failure(f"{instance.name} is off. Start it with: androidbox start {quoted(instance.name)}")
    if not running.booted():
        raise Failure(f"{instance.name} is still starting. Wait for it with: androidbox wait {quoted(instance.name)}")
    return running


def quoted(name):
    return shlex.quote(name) if not native.WINDOWS else (f'"{name}"' if " " in name else name)


def after_boot(running):
    """What the window does once Android is up, for an instance the command started without it"""
    instance = running.instance
    if instance.api == installer.LEGACY_API:
        running.map_gamepad()
    running.keep_awake()
    if instance.block_ads:
        running.block_ads(True)
    if instance.eco:
        running.set_priority(True)
    if instance.cpu_limit:
        running.set_cpu_limit(instance.cpu_limit)
    if instance.network:
        running.set_network(instance.network)
    if instance.muted:
        running.set_music_muted(True)


def start_here(instance):
    """Starts one emulator from this process. Returns it, or raises Failure saying why it can't be"""
    if instance.real:
        raise Failure(f"{instance.name} is a phone. Connect it from the Androidbox window")
    if not installer.runnable(instance.api):
        raise Failure(f"{installer.ANDROID_VERSIONS.get(instance.api, 'Its Android version')} isn't downloaded. "
                      "Open Androidbox once to get it")
    parsed = instances.effective_proxy(instance.proxy)
    if parsed and parsed[0] == "socks":
        # The relay that turns SOCKS into the HTTP proxy the emulator speaks lives in the process that started it
        raise Failure(f"{instance.name} uses a SOCKS proxy, which needs the Androidbox window open to work")
    wipe = False
    if instance.wipe_next:
        wipe = True
        saved = instances.load(repair=False)
        for each in saved:
            if each.id == instance.id:
                each.wipe_next = False
        instances.save(saved)
    running = machine(instance)
    running.start(wipe)
    return running


def wait_until(instances_list, ready, timeout, what):
    deadline = time.monotonic() + timeout
    waiting = list(instances_list)
    while waiting and time.monotonic() < deadline:
        for instance in list(waiting):
            if ready(instance):
                waiting.remove(instance)
                say(f"{instance.name} {what}")
        if waiting:
            time.sleep(1)
    if waiting:
        raise Failure(f"Gave up after {timeout} seconds: {', '.join(i.name for i in waiting)} still not {what}")


def booted(instance):
    if instance.real:
        return phone_connected(instance)
    running = machine(instance)
    return running.running() and running.booted()


def stopped(instance):
    return instance.real or machine(instance).fully_stopped()


# The commands. Each takes the parsed arguments and returns an exit code, or raises Failure

def run_list(args):
    rows = [{"name": i.name, "id": i.id, "state": state(i), "android": i.android, "group": i.group,
             "serial": i.serial, "display": f"{i.width}x{i.height}", "cores": i.cores, "ram": i.ram,
             "cpu_limit": i.cpu_limit} for i in everything()]
    if args.json:
        say(json.dumps(rows, indent=2))
        return 0
    if not rows:
        say("No instances yet. Make one in the Androidbox window")
        return 0
    columns = [("name", "NAME"), ("state", "STATE"), ("android", "ANDROID"), ("group", "GROUP"), ("serial", "SERIAL")]
    widths = {key: max(len(title), *(len(str(row[key])) for row in rows)) for key, title in columns}
    say("  ".join(f"{title:<{widths[key]}}" for key, title in columns).rstrip())
    for row in rows:
        say("  ".join(f"{row[key] or '-':<{widths[key]}}" for key, _ in columns).rstrip())
    return 0


def run_groups(args):
    groups = {}
    for instance in everything():
        if instance.group:
            groups.setdefault(instance.group, []).append(instance.name)
    if not groups:
        say("No groups yet. Give instances a group in their settings")
    for group, members in sorted(groups.items(), key=lambda item: item[0].lower()):
        say(f"{group}: {', '.join(members)}")
    return 0


def run_start(args):
    targets = chosen(args)
    waiting = [instance for instance in targets if not booted(instance)]
    for instance in targets:
        if instance not in waiting:
            say(f"{instance.name} is already on")
    if not waiting:
        return 0
    started = []
    problems = []
    if window_open():
        for instance in waiting:
            if not send({"instance": instance.id, "background": True}):
                raise Failure("The Androidbox window didn't answer")
            say(f"Asked the window to start {instance.name}")
            started.append(instance)
    else:
        for instance in waiting:
            if not instance.real and machine(instance).running():
                say(f"{instance.name} is already starting")
                started.append(instance)
                continue
            try:
                start_here(instance)
            except Failure as problem:
                problems.append(str(problem))
                continue
            say(f"Starting {instance.name}")
            started.append(instance)
    for problem in problems:
        print(problem, file=sys.stderr, flush=True)
    if args.no_wait or not started:
        return 1 if problems else 0
    wait_until(started, booted, args.timeout, "is on")
    if not window_open():
        for instance in started:
            if not instance.real:
                after_boot(machine(instance))
    return 1 if problems else 0


def run_stop(args):
    targets = [instance for instance in chosen(args) if not instance.real]
    on = [instance for instance in targets if machine(instance).running()]
    for instance in targets:
        if instance not in on:
            say(f"{instance.name} is already off")
    if not on:
        return 0
    if window_open():
        for instance in on:
            if not send({"instance": instance.id, "stop": True, "background": True}):
                raise Failure("The Androidbox window didn't answer")
            say(f"Asked the window to stop {instance.name}")
        if not args.no_wait:
            wait_until(on, stopped, STOP_TIMEOUT, "is off")
        return 0
    threads = []
    for instance in on:
        say(f"Stopping {instance.name}")
        thread = threading.Thread(target=machine(instance).stop)
        thread.start()
        threads.append((instance, thread))
    for instance, thread in threads:
        thread.join()
        say(f"{instance.name} is off")
    return 0


def run_wait(args):
    wait_until(chosen(args), booted, args.timeout, "is on")
    return 0


def run_install(args):
    running = require_on(find(args.name))
    failed = False
    for file in args.files:
        path = Path(file)
        if not path.is_file():
            print(f"{file}: no such file", file=sys.stderr, flush=True)
            failed = True
            continue
        if path.suffix.lower() not in emulator.APP_PACKAGES:
            print(f"{file}: not an app package ({', '.join(sorted(emulator.APP_PACKAGES))})", file=sys.stderr)
            failed = True
            continue
        say(f"Installing {path.name}…")
        ok, message = running.install(path)
        say(f"{path.name}: {'installed' if ok else message or 'failed'}")
        failed = failed or not ok
    return 1 if failed else 0


def run_launch(args):
    running = require_on(find(args.name))
    if args.package not in running.apps():
        raise Failure(f"{args.package} isn't installed on {running.instance.name}. See: androidbox apps "
                      f"{quoted(running.instance.name)}")
    running.launch(args.package)
    say(f"Opened {args.package}")
    return 0


def run_apps(args):
    for package in require_on(find(args.name)).apps():
        say(package)
    return 0


def run_shell(args):
    if not args.command:
        raise Failure("Give a command to run, like: androidbox shell Pixel getprop ro.build.version.release")
    code, output = require_on(find(args.name)).adb("shell", *args.command, timeout=args.timeout)
    if output:
        say(output)
    return 0 if code == 0 else 1


def screen_png(instance):
    result = subprocess.run([str(paths.ADB), "-s", instance.serial, "exec-out", "screencap", "-p"],
                            capture_output=True, timeout=30, env=emulator.environment(), **native.quiet_options())
    if result.returncode != 0 or not result.stdout.startswith(b"\x89PNG"):
        raise Failure(f"Couldn't take a screenshot of {instance.name}")
    return result.stdout


def default_file(instance, suffix):
    return Path(f"{instance.name}-{time.strftime('%Y%m%d-%H%M%S')}{suffix}")


def run_screenshot(args):
    instance = require_on(find(args.name)).instance
    file = Path(args.file) if args.file else default_file(instance, ".png")
    file.write_bytes(screen_png(instance))
    say(str(file))
    return 0


def run_record(args):
    running = require_on(find(args.name))
    if running.instance.real:
        raise Failure("Recording a phone is only in the window for now")
    seconds = max(1, min(RECORD_LIMIT, args.seconds))
    file = Path(args.file) if args.file else default_file(running.instance, ".webm")
    if not running.start_recording():
        raise Failure("Couldn't start recording")
    say(f"Recording {running.instance.name} for {seconds} seconds…")
    try:
        time.sleep(seconds)
    finally:
        saved = running.stop_recording(file)
    if not saved:
        raise Failure("The recording couldn't be saved")
    say(str(file))
    return 0


def find_macro(name):
    known = macros.load()
    found = next((macro for macro in known if macro["name"].lower() == name.lower()), None)
    if not found:
        raise Failure(f"There's no macro called {name}. Macros: {', '.join(m['name'] for m in known) or 'none yet'}")
    return found


def run_macro(args):
    if args.action == "list":
        if not macros.load():
            say("No macros yet. Record one in the window with the macro button")
        for macro in macros.load():
            display = macro.get("display") or ["?", "?"]
            say(f"{macro['name']}  ({macro.get('duration', 0):.0f} s, recorded on {display[0]}×{display[1]})")
        return 0
    if not args.name or not args.macro:
        raise Failure("Use: androidbox macro play INSTANCE MACRO")
    running = require_on(find(args.name))
    instance = running.instance
    macro = find_macro(args.macro)
    display = macro.get("display")
    if display and list(display) != [instance.width, instance.height]:
        raise Failure(f"{macro['name']} was recorded on a {display[0]}×{display[1]} display and {instance.name} "
                      f"is {instance.width}×{instance.height}, so its taps would land in the wrong places")
    if instance.real:
        raise Failure("Macros on a phone are only in the window for now")
    token = running.grpc_token()
    if not token:
        raise Failure(f"Couldn't reach {instance.name}'s controls")
    from .bridge import Bridge
    channel = Bridge(instance.grpc_port, token)
    report = Path(args.report) if args.report else None
    if report:
        report.mkdir(parents=True, exist_ok=True)
    crashes_before = crash_lines(running)
    runs = []
    try:
        for number in range(1, args.times + 1):
            began = time.time()
            done = threading.Event()
            notes = []
            player = macros.Player(channel, macro, loops=1, on_done=done.set, on_note=notes.append)
            try:
                while not done.wait(0.5):
                    pass
            except KeyboardInterrupt:
                player.stop()
                done.wait(5)
                raise
            entry = {"run": number, "seconds": round(time.time() - began, 1), "app": running.foreground_app(),
                     "notes": notes}
            crashes = crash_lines(running)
            entry["crashes"] = [line for line in crashes if line not in crashes_before]
            crashes_before = crashes
            if report:
                picture = report / f"run-{number}.png"
                try:
                    picture.write_bytes(screen_png(instance))
                    entry["screenshot"] = picture.name
                except (Failure, OSError, subprocess.TimeoutExpired):
                    entry["screenshot"] = None
            runs.append(entry)
            result = f"{len(entry['crashes'])} crash{'es' if len(entry['crashes']) != 1 else ''}" \
                if entry["crashes"] else "no crashes"
            say(f"Run {number} of {args.times}: {entry['seconds']} s, {result}"
                + (f", {'; '.join(notes)}" if notes else ""))
    except KeyboardInterrupt:
        say("Stopped")
    finally:
        channel.close()
    if report:
        write_report(report, instance, macro, runs)
        say(f"Report: {report / 'report.html'}")
    return 1 if any(run["crashes"] for run in runs) else 0


def crash_lines(running):
    return [line for line in running.crash_log().splitlines() if "am_crash" in line or "am_anr" in line]


def write_report(folder, instance, macro, runs):
    summary = {"instance": instance.name, "android": instance.android, "macro": macro["name"],
               "finished": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": runs,
               "crashed_runs": sum(1 for run in runs if run["crashes"]), "androidbox": VERSION}
    (folder / "report.json").write_text(json.dumps(summary, indent=2))
    cards = []
    for run in runs:
        crashes = "".join(f"<pre>{html.escape(line)}</pre>" for line in run["crashes"])
        picture = f"<img src='{html.escape(run['screenshot'])}' alt='Screen after run {run['run']}'>" \
            if run.get("screenshot") else ""
        status = f"<b class='bad'>{len(run['crashes'])} crash(es)</b>" if run["crashes"] else "<b>No crashes</b>"
        cards.append(f"<section><h2>Run {run['run']}</h2><p>{status} · {run['seconds']} s · "
                     f"{html.escape(run.get('app') or 'no app in front')}</p>{crashes}{picture}</section>")
    (folder / "report.html").write_text(f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(macro['name'])} on {html.escape(instance.name)}</title>
<style>
body {{ background: #04090b; color: #d4f1ec; font: 14px Consolas, monospace; margin: 32px; }}
h1 {{ font-size: 20px; text-shadow: 2px 0 #ff2e88, -2px 0 #22d8ff; }}
h2 {{ font-size: 14px; text-transform: uppercase; color: #3de8c8; margin: 0 0 6px; }}
p {{ color: #6f9f98; margin: 0 0 10px; }}
b {{ color: #3de8c8; }} b.bad {{ color: #ff4d8d; }}
main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }}
section {{ background: #0a1517; border: 1px solid #143a3d; border-radius: 3px; padding: 12px; }}
img {{ width: 100%; border-radius: 3px; }}
pre {{ white-space: pre-wrap; color: #ff4d8d; font-size: 12px; }}
</style>
<h1>{html.escape(macro['name'])} on {html.escape(instance.name)}</h1>
<p>{len(runs)} run(s), {summary['crashed_runs']} with crashes · {html.escape(instance.android)} ·
{summary['finished']} · Androidbox {VERSION}</p>
<main>{''.join(cards)}</main>
""")


def parser():
    top = argparse.ArgumentParser(prog="androidbox", description="Start, stop and use Androidbox's instances. "
                                  "With no command, opens the window.")
    top.add_argument("--version", action="version", version=f"Androidbox {VERSION}")
    commands = top.add_subparsers(dest="command", metavar="COMMAND")

    def command(name, text, handler):
        sub = commands.add_parser(name, help=text, description=text)
        sub.set_defaults(handler=handler)
        return sub

    def several(sub):
        sub.add_argument("names", nargs="*", metavar="INSTANCE", help="names or ids")
        sub.add_argument("--group", help="every instance in this group")
        sub.add_argument("--all", action="store_true", help="every instance")

    sub = command("list", "Show every instance and whether it's on", run_list)
    sub.add_argument("--json", action="store_true", help="as JSON, for scripts")
    command("groups", "Show the groups and who is in them", run_groups)
    sub = command("start", "Start instances and wait until Android is up", run_start)
    several(sub)
    sub.add_argument("--no-wait", action="store_true", help="return as soon as they are starting")
    sub.add_argument("--timeout", type=int, default=BOOT_TIMEOUT, help="seconds to wait (default %(default)s)")
    sub = command("stop", "Stop instances, saving their state", run_stop)
    several(sub)
    sub.add_argument("--no-wait", action="store_true", help="with the window open, return without waiting")
    sub = command("wait", "Wait until instances are up", run_wait)
    several(sub)
    sub.add_argument("--timeout", type=int, default=BOOT_TIMEOUT, help="seconds to wait (default %(default)s)")
    sub = command("install", "Install apps (.apk, .apks, .xapk, .apkm)", run_install)
    sub.add_argument("name", metavar="INSTANCE")
    sub.add_argument("files", nargs="+", metavar="FILE")
    sub = command("launch", "Open an app", run_launch)
    sub.add_argument("name", metavar="INSTANCE")
    sub.add_argument("package", metavar="PACKAGE")
    sub = command("apps", "List the apps you installed", run_apps)
    sub.add_argument("name", metavar="INSTANCE")
    sub = command("shell", "Run a command inside Android", run_shell)
    sub.add_argument("name", metavar="INSTANCE")
    sub.add_argument("command", nargs=argparse.REMAINDER, metavar="COMMAND")
    sub.add_argument("--timeout", type=int, default=60, help=argparse.SUPPRESS)
    sub = command("screenshot", "Save a picture of the screen as PNG", run_screenshot)
    sub.add_argument("name", metavar="INSTANCE")
    sub.add_argument("file", nargs="?", metavar="FILE")
    sub = command("record", f"Record the screen as WebM, up to {RECORD_LIMIT} seconds", run_record)
    sub.add_argument("name", metavar="INSTANCE")
    sub.add_argument("seconds", type=int, metavar="SECONDS")
    sub.add_argument("file", nargs="?", metavar="FILE")
    sub = command("macro", "List macros, or play one and report on each run", run_macro)
    sub.add_argument("action", choices=("list", "play"))
    sub.add_argument("name", nargs="?", metavar="INSTANCE")
    sub.add_argument("macro", nargs="?", metavar="MACRO")
    sub.add_argument("--times", type=int, default=1, help="how many runs (default 1)")
    sub.add_argument("--report", metavar="FOLDER", help="save a screenshot per run, report.json and report.html")
    return top


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else list(arguments)
    if arguments and arguments[0] == "help":
        arguments = [*arguments[1:], "--help"]
    args = parser().parse_args(arguments)
    if not getattr(args, "handler", None):
        parser().print_help()
        return 0
    if paths.home_missing():
        print(f"Androidbox's files aren't there ({paths.HOME}). Open the window to fix it", file=sys.stderr)
        return 1
    try:
        return args.handler(args)
    except Failure as problem:
        print(problem, file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
