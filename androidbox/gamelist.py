"""The shared game list: one file per game in the repository's games folder, saying how well it runs, which Android to
use, a frame rate and a controls layout. Androidbox reads the list's index from GitHub and keeps a copy, so it still
works offline. Nothing is sent anywhere unless you send a game's entry yourself."""
import json
import re
import time
import urllib.request
from dataclasses import asdict, fields
from urllib.parse import urlencode

from . import REPOSITORY, installer, keymap, paths, profiles

FORMAT = 1
FOLDER = "games"
INDEX = "index.json"
URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/{FOLDER}/{INDEX}"
CONTRIBUTE = f"https://github.com/{REPOSITORY}/tree/main/{FOLDER}#readme"
CACHE = paths.DATA / "gamelist.json"
FRESH_FOR = 24 * 60 * 60
WORKS = {"yes": "Works", "partly": "Partly works", "no": "Doesn't work"}
FRAME_RATES = (30, 60, 90, 120, 144, 240)
NAME_LIMIT = 60
NOTES_LIMIT = 300
CONTROLS_LIMIT = 40
# A macro control plays one of your own recorded macros, which nobody else has, so those stay out of the list
SHARED_KINDS = tuple(kind for kind in keymap.KINDS if kind != "macro")
PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
FIELDS = ("package", "name", "works", "android", "fps", "notes", "controls")

cache = {}


def problems(entry):
    """What is wrong with one game's entry, as sentences a contributor can act on. Empty when it is fine"""
    if not isinstance(entry, dict):
        return ["The entry must be a JSON object"]
    found = []
    unknown = sorted(set(entry) - set(FIELDS))
    if unknown:
        found.append(f"Unknown fields: {', '.join(unknown)}")
    package = entry.get("package")
    if not isinstance(package, str) or not PACKAGE.match(package):
        found.append("package must be the app's package name, such as com.example.game")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > NAME_LIMIT:
        found.append(f"name must be the game's name, up to {NAME_LIMIT} characters")
    if entry.get("works") not in WORKS:
        found.append(f"works must be one of {', '.join(WORKS)}")
    if "android" in entry and entry["android"] not in installer.ANDROID_VERSIONS:
        found.append(f"android must be one of {', '.join(installer.ANDROID_VERSIONS)} (the API level, as text)")
    if "fps" in entry and entry["fps"] not in FRAME_RATES:
        found.append(f"fps must be one of {', '.join(map(str, FRAME_RATES))}")
    notes = entry.get("notes", "")
    if not isinstance(notes, str) or len(notes) > NOTES_LIMIT:
        found.append(f"notes must be text, up to {NOTES_LIMIT} characters")
    controls = entry.get("controls", [])
    if not isinstance(controls, list) or len(controls) > CONTROLS_LIMIT:
        found.append(f"controls must be a list of up to {CONTROLS_LIMIT} controls")
    else:
        found += control_problems(controls)
    return found


def control_problems(controls):
    known = {item.name for item in fields(keymap.Control)}
    found = []
    for number, control in enumerate(controls, 1):
        if not isinstance(control, dict) or control.get("kind") not in SHARED_KINDS:
            found.append(f"Control {number} must have a kind: {', '.join(SHARED_KINDS)}")
            continue
        extra = sorted(set(control) - known)
        if extra:
            found.append(f"Control {number} has unknown fields: {', '.join(extra)}")
        for axis in ("x", "y", "x2", "y2"):
            value = control.get(axis)
            if value is None and axis in ("x2", "y2"):
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                found.append(f"Control {number}: {axis} must be a fraction of the screen, from 0 to 1")
    return found


def valid(entry):
    return not problems(entry)


def parse(text):
    """The games in an index file, keyed by package. Entries that don't check out are left out, so one bad entry
    can't hide the rest"""
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("games"), list):
        raise ValueError("Not a game list this version of Androidbox can read")
    return {entry["package"]: entry for entry in data["games"] if valid(entry)}


def build(entries):
    """The index file's text for a set of entries, as the repository keeps it"""
    games = sorted(entries, key=lambda entry: entry["package"])
    return json.dumps({"format": FORMAT, "games": games}, indent=1, ensure_ascii=False) + "\n"


def saved():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def games():
    """The list as last downloaded, without going online"""
    if "games" not in cache:
        try:
            cache["games"] = parse(json.dumps(saved().get("index", {})))
        except (ValueError, TypeError):
            cache["games"] = {}
    return cache["games"]


def checked():
    """When the list was last read from GitHub, as a timestamp, or 0 if never"""
    stamp = saved().get("checked", 0)
    return stamp if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else 0


def stale(now=None):
    return (now or time.time()) - checked() > FRESH_FOR


def download(opener=urllib.request.urlopen):
    request = urllib.request.Request(URL, headers={"User-Agent": "Androidbox"})
    with opener(request, timeout=15) as response:
        text = response.read().decode("utf-8")
    found = parse(text)
    paths.write_text(CACHE, json.dumps({"checked": time.time(), "index": json.loads(text)}), encoding="utf-8")
    cache["games"] = found
    return found


def refresh(force=False, opener=urllib.request.urlopen):
    """Downloads the list at most once a day unless forced. Offline, it keeps the copy it has"""
    if force or stale():
        try:
            return download(opener)
        except (OSError, ValueError):
            pass
    return games()


def play_link(package):
    if not PACKAGE.match(package):
        raise ValueError("Not a package name")
    return f"market://details?id={package}"


def entry(package):
    return games().get(package)


def android_name(api):
    return installer.ANDROID_VERSIONS.get(api, f"Android API {api}").split(" (")[0]


def summary(found, api=None):
    """One short line for the Apps page: how well it runs, where, and whether there is a setup to use"""
    text = WORKS[found["works"]]
    wanted = found.get("android")
    if wanted:
        text += f" on {android_name(wanted)}"
    if wanted and api and wanted != api:
        return f"{text}, this is {android_name(api)}"
    if found.get("fps") or found.get("controls"):
        text += "  ·  has a setup"
    return text


def apply(found):
    """Uses an entry's frame rate and controls for this game in the current profile. Returns what changed"""
    changed = []
    if found.get("fps"):
        profiles.set_game(found["package"], fps=found["fps"])
        changed.append("frame rate")
    if found.get("controls"):
        keymap.save(found["package"], keymap.parse(found["controls"]))
        changed.append("controls")
    return changed


def entry_for(package, name, works, notes="", android="", fps=0):
    """An entry made from how this game is set up here, ready to add to the list"""
    made = {"package": package, "name": name.strip()[:NAME_LIMIT], "works": works}
    if android:
        made["android"] = android
    if fps:
        made["fps"] = fps
    if notes.strip():
        made["notes"] = notes.strip()[:NOTES_LIMIT]
    controls = [{key: value for key, value in asdict(control).items() if value not in (None, "")}
                for control in keymap.load(package) if control.kind in SHARED_KINDS]
    if controls:
        made["controls"] = controls
    return made


# Drafting reports while you play, if you turn it on: Androidbox notes how long each game was in front and how often
# Android closed it with a crash or an "isn't responding" dialog, and once a game has had a fair run it offers to
# make that game's entry. The notes stay in this file; an entry only reaches GitHub if you send it yourself
PLAYED = paths.DATA / "played.json"
REPORT_AFTER = 10 * 60
CRASH_LINE = re.compile(r"\b(am_crash|am_anr)\s*:\s*\[(.*)\]")
SEEN_LIMIT = 40
NEW_FILE = f"https://github.com/{REPOSITORY}/new/main/{FOLDER}"


def played():
    try:
        data = json.loads(PLAYED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def play_record(package, api):
    found = played().get(f"{api}:{package}")
    return found if isinstance(found, dict) else None


def crash_lines(text, package):
    """The crash and "isn't responding" lines for one package in Android's event log"""
    found = []
    for line in text.splitlines():
        match = CRASH_LINE.search(line)
        if match and package in (part.strip() for part in match.group(2).split(",")):
            found.append(line.strip())
    return found


def record_play(package, api, seconds, crashes=()):
    """Adds one stretch of play. Crash lines already counted in an earlier stretch aren't counted again, because
    Android keeps them in its log until it fills up"""
    data = played()
    key = f"{api}:{package}"
    record = data.get(key) if isinstance(data.get(key), dict) else {}
    seen = list(record.get("seen", []))
    new = [line for line in dict.fromkeys(crashes) if line not in seen]
    record.update(package=package, api=api, seconds=record.get("seconds", 0) + max(0, round(seconds)),
                  sessions=record.get("sessions", 0) + 1, crashes=record.get("crashes", 0) + len(new),
                  seen=(seen + new)[-SEEN_LIMIT:], last=time.time())
    data[key] = record
    paths.write_text(PLAYED, json.dumps(data), encoding="utf-8")
    return record


def mark(package, api, flag):
    """Notes that a game's draft was offered (the bar at the bottom shows once) or is done with (sent, saved or
    dismissed, so it leaves the Game list page)"""
    data = played()
    record = data.get(f"{api}:{package}")
    if isinstance(record, dict):
        record[flag] = True
        paths.write_text(PLAYED, json.dumps(data), encoding="utf-8")


def worth_reporting(record):
    """Whether a game has been played enough to say how it runs, and the list doesn't already say so for this
    Android version. A game that crashes straight away counts too, after a few tries"""
    if not record or record.get("done"):
        return False
    listed = entry(record["package"])
    if listed and listed.get("android") in (None, record["api"]):
        return False
    return record.get("seconds", 0) >= REPORT_AFTER or (record.get("crashes", 0) >= 3 and
                                                         record.get("sessions", 0) >= 3)


def to_report(api=None):
    """Played games waiting for their entry, most recently played first"""
    found = [record for record in played().values() if isinstance(record, dict) and "package" in record
             and (api is None or record.get("api") == api) and worth_reporting(record)]
    return sorted(found, key=lambda record: -record.get("last", 0))


def duration(seconds):
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    hours = round(seconds / 3600)
    return f"{hours} hours"


def guess_works(record):
    """A starting answer for how well it runs, from what was seen. You change it before anything is sent"""
    crashes = record.get("crashes", 0)
    if not crashes:
        return "yes"
    if record.get("seconds", 0) < 2 * 60:
        return "no"
    return "partly"


def guess_notes(record):
    crashes = record.get("crashes", 0)
    if not crashes:
        return ""
    if guess_works(record) == "no":
        return "Closes by itself as soon as it opens."
    return "Closed by itself once while playing." if crashes == 1 else \
        f"Closed by itself {crashes} times while playing."


def propose_link(found):
    """GitHub's page for adding a file, filled in with this entry. It forks the repository for you if needed and
    ends in a pull request, under your own GitHub account"""
    text = json.dumps(found, indent=1, ensure_ascii=False) + "\n"
    return f"{NEW_FILE}?{urlencode({'filename': found['package'] + '.json', 'value': text})}"
