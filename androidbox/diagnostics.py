import dataclasses
import platform
import re
import zipfile

from . import VERSION, instances, socks_relay

# What to look for in the device log, in order of how likely it is to explain a game that crashes or closes
FINDINGS = [
    ("ARM translator crash",
     ("Cannot process signal 11", "libndk_translation_proxy_libc", "libproxy_arm64_to_x86_64_libc",
      "Forwarding signal 11"),
     "An ARM game crashed inside Android's ARM-to-x86 translator, usually while copying memory it had just "
     "protected. No newer Android image fixes this, so the game itself has to avoid it."),
    ("App crash", ("FATAL EXCEPTION", "AndroidRuntime: Shutting down VM"),
     "An app threw an error it didn't handle and closed. The lines around it name the app and the error."),
    ("App not responding", ("ANR in ",), "An app froze for several seconds and Android offered to close it."),
    ("Out of memory", ("OutOfMemoryError", "lowmemorykiller", "Out of memory: Kill"),
     "Android ran out of memory and closed an app. Give this instance more memory in its Settings."),
    ("Graphics trouble", ("EGL_BAD_", "GLES: Failed", "Failed to create GL", "eglMakeCurrent"),
     "Something went wrong with the graphics. Try Automatic or Software graphics in this instance's Settings."),
    ("Missing Play certification", ("not Play Protect certified", "DEVICE_NOT_CERTIFIED"),
     "Google doesn't consider this image certified. Redownloading the image in Settings sometimes fixes it."),
]
# What the emulator's own log says when Android never starts or the emulator dies, in order of likelihood. These
# need no running Android, so they can explain a crash after the fact
START_FINDINGS = [
    ("Windows' virtualization isn't working",
     ("whpx: failed", "failed to create whpx", "whpx is not", "no hypervisor", "hypervisor is not",
      "haxm is not", "cannot find a hypervisor", "failed to start the hypervisor"),
     "Android needs Windows Hypervisor Platform. Turn it on in Windows Features, restart the PC, and check that "
     "virtualization is enabled in the BIOS. Other virtual machine software can also take it over."),
    ("The drive is full",
     ("no space left on device", "not enough disk space", "insufficient disk space", "disk is full",
      "enospc"),
     "There isn't enough free space on the drive that holds this instance. Free some space, or move the instance "
     "to another drive in Settings."),
    ("The PC ran out of memory",
     ("std::bad_alloc", "failed to allocate", "unable to allocate", "cannot allocate memory", "not enough memory",
      "out of memory", "insufficient memory"),
     "Windows couldn't give this instance the memory it asked for. Close other programs or lower its Memory in "
     "Settings, especially if other instances are running."),
    ("Graphics couldn't start",
     ("failed to initialize opengles", "initialize gfxstream failed", "vkcreateinstance failed",
      "vkcreatedevice failed", "failed to create egl", "eglinitialize failed", "failed to create gl context",
      "no suitable vulkan"),
     "The graphics card or its driver failed. Update your graphics driver, or choose Automatic or Software "
     "graphics in this instance's Settings."),
    ("The Android image is damaged or missing",
     ("cannot find system image", "could not open system image", "unknown avd name", "cannot open kernel",
      "invalid system image", "kernel image not found"),
     "A file Android needs to start is missing or damaged. Download the Android image again from Settings."),
    ("Another copy of this instance is running",
     ("another emulator instance running", "running multiple emulators with the same avd",
      "multiinstance.lock"),
     "This instance is still open somewhere, maybe in a window that is shutting down. Wait a moment, or end "
     "qemu-system-x86_64 in Task Manager, then start it again."),
    ("The emulator crashed",
     ("access violation", "unhandled exception", "stack overflow", "emulator: crash", "has crashed",
      "fatal error"),
     "The emulator program itself crashed. Try Automatic or Software graphics in this instance's Settings, and "
     "update your graphics driver."),
]
START_PATTERN = re.compile("|".join(re.escape(needle) for _, needles, _ in START_FINDINGS for needle in needles))
LOG_TAIL = 2 << 20
# What a failed step of reaching the proxy usually means, by the step that failed
PROXY_ADVICE = {
    "lookup": "This PC can't find the proxy's address. Check how it is spelled, or type its IP address instead. "
              "Androidbox looks the address up on Windows, not inside Android.",
    "connect": "This PC can't connect to the proxy. Androidbox connects from Windows, while an app like v2rayNG "
               "connects from inside Android, so one can work when the other doesn't. Check the port and any "
               "firewall, and ask the provider whether it only accepts connections from certain places or needs "
               "a relay.",
    "proxy": "The proxy answered but wouldn't carry traffic. Check the kind (a plain address is HTTP, "
             "socks5://user:pass@host:port is SOCKS5) and the username and password.",
    "target": "The proxy accepted the login but couldn't open a connection through to the Internet. The provider "
              "may be blocking it or the plan may be out of traffic.",
}
# Checks run inside Android, with their timeouts. The output goes into network.txt as it is
ANDROID_CHECKS = (
    ("Proxy set inside Android", ("shell", "settings", "get", "global", "http_proxy"), 10),
    ("Network interfaces", ("shell", "ls", "/sys/class/net"), 10),
    ("Ping example.com", ("shell", "ping", "-c", "1", "-W", "3", "example.com"), 20),
)
VPN_INTERFACES = ("tun", "ppp", "wg", "tap")
DNS_FAILURES = ("unknown host", "bad address", "name or service not known", "could not resolve",
                "temporary failure in name resolution", "unknown name")
SIGNATURES = re.compile("|".join(re.escape(needle) for _, needles, _ in FINDINGS for needle in needles))
LOG_COMMANDS = {
    "logcat.txt": ("logcat", "-d", "-b", "all", "-v", "threadtime"),
    "properties.txt": ("shell", "getprop"),
    "memory.txt": ("shell", "dumpsys", "meminfo"),
    "crashes.txt": ("shell", "dumpsys", "dropbox", "--print", "data_app_crash"),
}


def findings(logcat):
    # The log can run to tens of megabytes, so one regex pass over it finds every signature at once
    matches = {title: [] for title, _, _ in FINDINGS}
    for line in logcat.splitlines():
        if SIGNATURES.search(line):
            for title, needles, _ in FINDINGS:
                if any(needle in line for needle in needles):
                    matches[title].append(line.strip())
    return [(title, advice, matches[title]) for title, _, advice in FINDINGS if matches[title]]


def startup_findings(text):
    """(title, advice, line) for each known problem the emulator's own log mentions, likeliest first"""
    lowered = {}
    for line in text.splitlines():
        lower = line.lower()
        if START_PATTERN.search(lower):
            for title, needles, _ in START_FINDINGS:
                if title not in lowered and any(needle in lower for needle in needles):
                    lowered[title] = line.strip()[:240]
    return [(title, advice, lowered[title]) for title, _, advice in START_FINDINGS if title in lowered]


def startup_reason(instance):
    """The most likely reason this instance stopped, from the end of its emulator log, or None"""
    try:
        with open(instance.log, "rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - LOG_TAIL))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return None
    found = startup_findings(text)
    return found[0] if found else None


def ping_verdict(output):
    """"found" if the ping got an answer, "dns" if the name couldn't be looked up, "silent" otherwise"""
    lowered = output.lower()
    if any(text in lowered for text in DNS_FAILURES):
        return "dns"
    if "bytes from" in lowered or " 1 received" in lowered or "1 packets received" in lowered:
        return "found"
    return "silent"


def vpn_interfaces(listing):
    return [name for name in listing.split() if name.startswith(VPN_INTERFACES)]


def mark(step):
    return f"  {'ok  ' if step.ok else 'FAIL'} {step.name}: {step.detail}"


def network_report(instance, adb=None):
    """(text, problems): what the PC and Android can reach, for bug reports about a game or app that can't get
    online. adb is the instance's adb function, or None when Android isn't running. problems are
    (title, advice, lines) like the log findings, and nothing in here carries the proxy login"""
    lines = []
    problems = []
    blank = not (instance.proxy or "").strip()
    proxy = None if blank else instances.effective_proxy(instance.proxy)
    lines.append(f"Proxy setting: {'none' if blank else instances.proxy_label(instance.proxy)}")
    if proxy:
        typed = instances.parse_proxy(instance.proxy)
        if typed[0] != proxy[0]:
            lines.append("It was typed as an HTTP proxy but answers as SOCKS5, so Androidbox relays it through a "
                         "small SOCKS5 relay on this PC.")
        elif proxy[0] == "socks":
            lines.append("Androidbox relays it through a small SOCKS5 relay on this PC.")
        steps = socks_relay.probe(*proxy)
        lines += ["", "From this PC, through the proxy:", *(mark(step) for step in steps)]
        failed = next((step for step in steps if not step.ok), None)
        if failed:
            problems.append(("The proxy doesn't work from this PC", PROXY_ADVICE[failed.key],
                             [f"{failed.name}: {failed.detail}"]))
    elif not blank:
        problems.append(("The proxy setting isn't understood",
                         "Type it as host:port, user:pass@host:port, host:port:user:pass or "
                         "socks5://user:pass@host:port.", [instances.proxy_label(instance.proxy)]))

    steps, sock = socks_relay.reach("example.com", 443, "example.com")
    if sock:
        sock.close()
    lines += ["", "From this PC, straight to the Internet (no proxy):", *(mark(step) for step in steps)]
    if not sock and blank:
        failed = next(step for step in steps if not step.ok)
        problems.append(("This PC can't reach the Internet",
                         "Android uses this PC's connection, so it can't get online either. Check the PC's "
                         "connection, firewall and any VPN or DNS setting on Windows.",
                         [f"{failed.name}: {failed.detail}"]))

    lines += ["", "Inside Android:"]
    if adb is None:
        lines.append("  Android wasn't running, so nothing was checked inside it.")
        return "\n".join(lines) + "\n", problems
    results = {}
    for name, command, timeout in ANDROID_CHECKS:
        try:
            _, output = adb(*command, timeout=timeout)
        except Exception as problem:
            output = str(problem)
        results[name] = output.strip()
        lines.append(f"  {name}: {' '.join(output.split()) or '(nothing)'}")
    tunnels = vpn_interfaces(results["Network interfaces"])
    if tunnels:
        lines.append(f"  A VPN or tunnel is active inside Android ({', '.join(tunnels)}). Its app carries the "
                     "traffic, which can behave differently from the proxy setting above.")
    verdict = ping_verdict(results["Ping example.com"])
    lines.append({"found": "  Android can look up and reach example.com.",
                  "dns": "  Android can't look up example.com.",
                  "silent": "  Android got no ping reply. Some networks, and proxies, don't carry ping, so this "
                            "alone doesn't mean it is offline."}[verdict])
    if verdict == "dns":
        problems.append(("Android can't look up web addresses",
                         "Android looks names up through this PC, so check that the PC can (see above), restart "
                         "Android, and turn off any VPN or DNS changer running inside Android to compare.",
                         [f"Ping example.com: {' '.join(results['Ping example.com'].split())[:240]}"]))
    return "\n".join(lines) + "\n", problems


def summary(instance, running, logcat, found=None, network_problems=()):
    lines = [f"Androidbox {VERSION} on {platform.platform()}", f"Instance: {instance.name} ({instance.id}), "
             f"{instance.android}, {'running' if running else 'not running'}", ""]
    if found is None:
        found = findings(logcat) if logcat else []
    reasons = startup_reason(instance)
    if reasons:
        lines += [f"== From the emulator's own log: {reasons[0]}", reasons[1], f"   {reasons[2]}", ""]
    for title, advice, details in network_problems:
        lines += [f"== Network: {title}", advice, *(f"   {line}" for line in details), "   See network.txt.", ""]
    if not logcat:
        lines.append("No device log: Android wasn't running when this was collected.")
    elif not found:
        lines.append("No known problem signatures in the device log.")
    for title, advice, matches in found:
        lines += [f"== {title} ({len(matches)} lines)", advice, *(f"   {line[:240]}" for line in matches[:5]), ""]
    return "\n".join(lines)


def collect(emulator, destination):
    """Zips the device log, the emulator's own log, this instance's settings and a network check, plus a plain
    summary of what looks wrong. Returns the number of problems it recognised."""
    instance = emulator.instance
    running = emulator.running()
    outputs = {}
    if running:
        for name, command in LOG_COMMANDS.items():
            code, output = emulator.adb(*command, timeout=90)
            if code == 0 or output:
                outputs[name] = output
    logcat = outputs.get("logcat.txt", "")
    found = findings(logcat) if logcat else []
    try:
        network, network_problems = network_report(instance, emulator.adb if running else None)
    except Exception as problem:
        # A network check that breaks mustn't cost the rest of the bundle
        network, network_problems = f"The network check failed: {problem}\n", []
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("summary.txt", summary(instance, running, logcat, found, network_problems))
        bundle.writestr("network.txt", network)
        for name, text in outputs.items():
            bundle.writestr(name, text)
        # A proxy address can carry a login, and this file is meant to be shared
        settings = {**dataclasses.asdict(instance), "proxy": instances.proxy_label(instance.proxy)}
        bundle.writestr("instance.txt", "\n".join(f"{key}={value}" for key, value in settings.items()))
        for name, path in (("emulator.log", instance.log), ("config.ini", instance.folder / "config.ini")):
            try:
                bundle.write(path, name)
            except OSError:
                pass
    return len(found) + len(network_problems)
