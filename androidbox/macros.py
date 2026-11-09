import base64
import json
import re
import threading
import time

from . import profiles, vision
from .proto import emulator_controller_pb2 as pb

SPEEDS = (0.5, 1.0, 2.0, 4.0)
LOOPS = ((1, "Once"), (2, "2 times"), (5, "5 times"), (10, "10 times"), (25, "25 times"), (50, "50 times"),
         (100, "100 times"), (0, "Until I stop it"))
GAPS = (0.0, 0.3, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
TAP_SECONDS = 0.35
TAP_TRAVEL = 40
POLL = 0.3
LOOK_WIDTH = 160
STILL_LIMIT = 0.012
TIMEOUTS = ((10, "10 seconds"), (30, "30 seconds"), (60, "1 minute"), (300, "5 minutes"), (0, "No limit"))
HOLDS = (0.5, 1.0, 2.0, 3.0)
REPEATS = (5, 10, 25, 50, 100)
AREA_KINDS = ("area", "if", "until")
BLOCKS = {"if": "end", "repeat": "until"}

cache = {}


def file(name):
    return profiles.macro_folder() / f"{name}.json"


def forget():
    cache.clear()


def load():
    folder = profiles.macro_folder()
    if cache.get("folder") != folder:
        macros = []
        for path in sorted(folder.glob("*.json")):
            try:
                macros.append(json.loads(path.read_text()))
            except (OSError, ValueError):
                continue
        cache["folder"] = folder
        cache["all"] = macros
    return cache["all"]


def next_name():
    taken = {macro["name"] for macro in load()}
    return next(f"Macro {n}" for n in range(1, 1000) if f"Macro {n}" not in taken)


def write(macro):
    profiles.write_json(file(macro["name"]), macro, indent=None)
    forget()


def save(name, recording, display):
    if not recording:
        return None
    start = recording[0][0]
    macro = {
        "name": name,
        "duration": round(recording[-1][0] - start, 2),
        "speed": 1.0,
        "hotkey": "",
        "display": list(display),
        "events": [[round(at - start, 4), base64.b64encode(payload).decode()] for at, payload in recording],
    }
    write(macro)
    return macro


def update(current, **changes):
    macro = json.loads(file(current).read_text())
    if "name" in changes:
        changes["name"] = re.sub(r'[\/:*?"<>|]', "", changes["name"]).strip() or current
        if changes["name"] != current and file(changes["name"]).exists():
            raise ValueError(f"A macro called {changes['name']} already exists")
    macro.update(changes)
    write(macro)
    if macro["name"] != current:
        delete(current)
    return macro


def delete(name):
    file(name).unlink(missing_ok=True)
    profiles.stamp()
    forget()


def decode(payload):
    event = pb.InputEvent()
    event.ParseFromString(base64.b64decode(payload))
    return event


def actions(macro):
    """The raw events grouped into what a person did: a tap, a swipe, a hold or a key press"""
    found = []
    touching = set()
    current = None
    keys = {}
    for number, (offset, payload) in enumerate(macro["events"]):
        if isinstance(payload, dict):
            found.append({"start": offset, "end": offset, "events": [number], "step": payload})
            continue
        event = decode(payload)
        kind = event.WhichOneof("type")
        if kind == "touch_event":
            touches = event.touch_event.touches
            if current is None:
                current = {"start": offset, "end": offset, "events": [], "points": []}
                found.append(current)
            current["events"].append(number)
            current["end"] = offset
            for touch in touches:
                current["points"].append((touch.x, touch.y))
                (touching.add if touch.pressure else touching.discard)(touch.identifier)
            if not touching:
                current = None
        elif kind == "key_event":
            key = event.key_event.key or event.key_event.text
            held = keys.get(key)
            if held and event.key_event.eventType == pb.KeyboardEvent.keyup:
                held["events"].append(number)
                held["end"] = offset
                keys.pop(key)
                continue
            action = {"start": offset, "end": offset, "events": [number], "key": key}
            found.append(action)
            if event.key_event.eventType == pb.KeyboardEvent.keydown:
                keys[key] = action
        else:
            found.append({"start": offset, "end": offset, "events": [number], "other": True})
    previous = 0.0
    for action in found:
        action["wait"] = round(max(0.0, action["start"] - previous), 2)
        previous = max(previous, action["end"])
        action["label"] = describe(action)
    return found


def describe_step(step):
    kind = step.get("wait")
    if kind == "if":
        return "If the marked area looks the same, do the steps up to End if"
    if kind == "end":
        return "End if"
    if kind == "repeat":
        return "Repeat the steps up to Until"
    if kind == "until":
        return f"Until the marked area looks the same (at most {step.get('max', 50)} times)"
    limit = f"up to {step['timeout']:g} s" if step.get("timeout") else "no time limit"
    if kind == "find":
        return f"Tap the marked picture when it shows up ({limit})"
    if kind == "still":
        return f"Wait until the screen stops changing for {step.get('hold', 1.0):g} s ({limit})"
    return f"Wait until the marked area looks the same ({limit})"


def describe(action):
    if "step" in action:
        return describe_step(action["step"])
    if "key" in action:
        return f"Key {action['key'] or '?'}"
    if "points" not in action:
        return "Other input"
    points = action["points"]
    (x1, y1), (x2, y2) = points[0], points[-1]
    seconds = action["end"] - action["start"]
    if max(abs(x2 - x1), abs(y2 - y1)) > TAP_TRAVEL:
        return f"Swipe from {x1}, {y1} to {x2}, {y2} in {seconds:.1f}s"
    if seconds >= TAP_SECONDS:
        return f"Hold at {x1}, {y1} for {seconds:.1f}s"
    return f"Tap at {x1}, {y1}"


def new_step(kind, region=None, reference=None, tolerance=0.08, timeout=30, hold=1.0, then="stop", repeats=50,
             picture=None, display=None):
    """kind is area or still (wait), if or until (decide from the marked area), end or repeat (block ends),
    or find (tap a picture wherever it shows up, which is the picture and the display it was marked on)"""
    step = {"wait": kind}
    if kind in AREA_KINDS:
        step.update(region=vision.clean_region(region), reference=reference, tolerance=tolerance)
    if kind == "find":
        step.update(region=vision.clean_region(region), picture=picture, tolerance=tolerance, display=list(display))
    if kind in ("area", "still", "find"):
        step.update(timeout=timeout, then=then)
    if kind == "still":
        step["hold"] = hold
    if kind == "until":
        step.update(max=repeats, then=then)
    return step


def pair_up(events):
    """Which If goes with which End, and which Repeat with which Until, as {index: partner index}. A marker
    without its partner is left out and does nothing"""
    pairs, open_blocks = {}, []
    for index, (_, payload) in enumerate(events):
        kind = payload.get("wait") if isinstance(payload, dict) else None
        if kind in BLOCKS:
            open_blocks.append(index)
        elif kind in BLOCKS.values() and open_blocks and BLOCKS[events[open_blocks[-1]][1]["wait"]] == kind:
            opened = open_blocks.pop()
            pairs[opened], pairs[index] = index, opened
    return pairs


def add_steps(macro, after, steps, count=1):
    """One wait step, or a begin and end step around the next count actions"""
    if len(steps) == 1:
        return add_step(macro, after, steps[0])
    found = actions(macro)
    # The end goes in first, so the begin's place is still where it was
    add_step(macro, max(after, min(len(found) - 1, after + count)), steps[1])
    return add_step(macro, after, steps[0])


def add_step(macro, after, step):
    """Puts a wait step after the given action (-1 for the very start)"""
    found = actions(macro)
    if after < 0 or not found:
        index, offset = 0, 0.0
    else:
        index, offset = max(found[after]["events"]) + 1, found[after]["end"]
    macro["events"].insert(index, [offset, step])
    return finish(macro)


def update_step(macro, number, **changes):
    action = actions(macro)[number]
    macro["events"][action["events"][0]][1].update(changes)
    return macro


def grab(bridge, display, width):
    """A small raw picture of the screen as (bytes, width, height), or None if the emulator didn't answer"""
    height = max(1, round(width * display[1] / display[0])) if display and display[0] else width * 2
    try:
        return bridge.pixels(width, height)
    except Exception:
        return None


def mark_picture(bridge, display, region):
    """The pixels inside a region, to look for later, or None if the emulator didn't answer"""
    shot = grab(bridge, display, vision.FIND_WIDTH)
    if shot is None:
        return None
    pixels, across, down = vision.crop(*shot, region)
    return {"w": across, "h": down, "pixels": vision.encode(pixels)}


def locate(bridge, display, step):
    """Where the marked picture is on screen right now, as the fractions (across, down) of its middle, or None"""
    shot = grab(bridge, display, vision.FIND_WIDTH)
    if shot is None:
        return None
    frame, width, height = shot
    picture = step["picture"]
    hit = vision.find(frame, width, height, (vision.decode(picture["pixels"]), picture["w"], picture["h"]),
                      step.get("tolerance", 0.08))
    return None if hit is None else ((hit[0] + picture["w"] / 2) / width, (hit[1] + picture["h"] / 2) / height)


def seek(bridge, display, step, stopped, poll=POLL, clock=time.monotonic):
    """Waits for the marked picture. Its position, False if it ran out of time, None if playback was stopped"""
    timeout = step.get("timeout", 30)
    deadline = clock() + timeout if timeout else None
    while not stopped.is_set():
        found = locate(bridge, display, step)
        if found:
            return found
        if deadline is not None and clock() >= deadline:
            return False
        stopped.wait(poll)
    return None


def tap(bridge, display, point, stopped):
    x, y = round(point[0] * display[0]), round(point[1] * display[1])
    bridge.touch((0, x, y, True))
    stopped.wait(0.06)
    bridge.touch((0, x, y, False))


def look(bridge, display, step):
    """What the screen looks like right now for this step, or None if the emulator didn't answer"""
    shot = grab(bridge, display, LOOK_WIDTH)
    if shot is None:
        return None
    frame, width, height = shot
    if step.get("wait") == "still":
        return vision.sample(frame, width, height, vision.WHOLE_SCREEN, vision.STILL_GRID)
    return vision.sample(frame, width, height, step["region"])


def distance(bridge, display, step):
    """How different the marked area is from when the step was made (0 to 1), or None if it can't be read"""
    seen = look(bridge, display, step)
    return None if seen is None else vision.difference(seen, vision.decode(step["reference"]))


def matches(bridge, display, step):
    """Does the marked area look the way it did when the step was made, right now? An unreadable screen doesn't"""
    gap = distance(bridge, display, step)
    return gap is not None and gap <= step.get("tolerance", 0.08)


def wait_for(bridge, display, step, stopped, poll=POLL, clock=time.monotonic):
    """True once the step's wait is over, False if it ran out of time, None if playback was stopped"""
    timeout = step.get("timeout", 30)
    deadline = clock() + timeout if timeout else None
    area = step.get("wait") != "still"
    reference = vision.decode(step["reference"]) if area else None
    previous = calm_since = None
    while not stopped.is_set():
        seen = look(bridge, display, step)
        now = clock()
        if seen is not None:
            if area:
                if vision.difference(seen, reference) <= step.get("tolerance", 0.08):
                    return True
            elif previous is not None and vision.difference(seen, previous) <= STILL_LIMIT:
                calm_since = now if calm_since is None else calm_since
                if now - calm_since >= step.get("hold", 1.0):
                    return True
            else:
                calm_since = None
            previous = seen
        if deadline is not None and now >= deadline:
            return False
        stopped.wait(poll)
    return None


def finish(macro):
    events = macro["events"]
    macro["duration"] = round(events[-1][0] - events[0][0], 2) if events else 0.0
    return macro


def remove_action(macro, number):
    # Taking out one end of an If or Repeat takes the other with it
    found = actions(macro)
    pairs = pair_up(macro["events"])
    first = found[number]["events"][0]
    if first in pairs:
        other = next(index for index, action in enumerate(found) if pairs[first] in action["events"])
        for index in sorted((number, other), reverse=True):
            macro = remove_one(macro, index)
        return macro
    return remove_one(macro, number)


def remove_one(macro, number):
    # Later actions move up by the time this one and the wait before it took, so their own waits stay as they were
    found = actions(macro)
    action = found[number]
    earlier = max((other["end"] for other in found[:number]), default=0.0)
    shift = max(0.0, action["end"] - earlier)
    gone = set(action["events"])
    macro["events"] = [[round(offset - (shift if offset > action["end"] else 0.0), 4), payload]
                       for index, (offset, payload) in enumerate(macro["events"]) if index not in gone]
    return finish(macro)


def set_wait(macro, number, seconds):
    action = actions(macro)[number]
    delta = seconds - action["wait"]
    macro["events"] = [[round(max(0.0, offset + (delta if offset >= action["start"] else 0.0)), 4), payload]
                       for offset, payload in macro["events"]]
    return finish(macro)


class Player:
    def __init__(self, bridge, macro, loops=1, on_done=None, on_note=None):
        self.bridge = bridge
        speed = macro.get("speed") or 1.0
        self.display = macro.get("display")
        self.events = [(offset / speed, payload if isinstance(payload, dict) else base64.b64decode(payload))
                       for offset, payload in macro["events"]]
        self.gap = macro.get("gap", 0.3)
        self.loops = loops
        self.on_done = on_done
        self.on_note = on_note
        self.stopped = threading.Event()
        threading.Thread(target=self.play, daemon=True).start()

    def note(self, text):
        if self.on_note:
            self.on_note(text)

    def play(self):
        played = 0
        pairs = pair_up(self.events)
        while not self.stopped.is_set() and (self.loops == 0 or played < self.loops):
            start = time.monotonic()
            # Time spent waiting, and time skipped over, so the events after them keep their spacing
            delay = 0.0
            repeated = {}
            index = 0
            while index < len(self.events):
                offset, payload = self.events[index]
                if self.stopped.wait(max(0.0, start + delay + offset - time.monotonic())):
                    break
                index += 1
                if not isinstance(payload, dict):
                    self.bridge.replay(payload)
                    continue
                kind = payload.get("wait")
                if kind in ("area", "still"):
                    before = time.monotonic()
                    result = wait_for(self.bridge, self.display, payload, self.stopped)
                    delay += time.monotonic() - before
                    if result is False and payload.get("then", "stop") == "stop":
                        self.note(f"Macro stopped: {describe_step(payload).lower()} didn't happen in time")
                        self.stopped.set()
                elif kind == "find":
                    before = time.monotonic()
                    point = seek(self.bridge, payload.get("display") or self.display, payload, self.stopped)
                    delay += time.monotonic() - before
                    if point:
                        tap(self.bridge, payload.get("display") or self.display, point, self.stopped)
                    elif point is False and payload.get("then", "stop") == "stop":
                        self.note(f"Macro stopped: {describe_step(payload).lower()} didn't happen in time")
                        self.stopped.set()
                elif kind == "if" and index - 1 in pairs and not matches(self.bridge, self.display, payload):
                    end = pairs[index - 1]
                    delay -= self.events[end][0] - offset
                    index = end
                elif kind == "until" and index - 1 in pairs and not matches(self.bridge, self.display, payload):
                    count = repeated[index - 1] = repeated.get(index - 1, 0) + 1
                    if count >= payload.get("max", 50):
                        if payload.get("then", "stop") == "stop":
                            self.note(f"Macro stopped: repeated {count} times and the marked area never "
                                      "looked the same")
                            self.stopped.set()
                        continue
                    if self.stopped.wait(POLL):
                        break
                    # Back to just after the Repeat, with the clock set so the steps in between keep their spacing
                    index = pairs[index - 1] + 1
                    start, delay = time.monotonic() - self.events[index - 1][0], 0.0
            played += 1
            self.stopped.wait(self.gap)
        if self.on_done:
            self.on_done()

    def stop(self):
        self.stopped.set()
