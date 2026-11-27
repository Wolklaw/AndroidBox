"""Logic that doesn't need a phone or a window. Run from the repo root: python -m unittest discover tests"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANDROIDBOX_HOME", tempfile.mkdtemp(prefix="androidbox-test-"))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp(prefix="androidbox-local-"))

import base64  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from androidbox import claude, emulator, instances, macros, updates, vision  # noqa: E402
from androidbox.proto import emulator_controller_pb2 as pb  # noqa: E402


def load_helper():
    """The Claude helper as the plugin ships it, loaded without running main()"""
    text = (claude.TOOL_TEXT.replace("{CONSOLE_PORTS}", repr(list(instances.CONSOLE_PORTS)))
            .replace("{ADB_SERVER_PORT}", emulator.ADB_SERVER_PORT).replace("{HOME_LINE}", "HOME = Path('.')"))
    namespace = {"__name__": "helper"}
    exec(compile(text.rsplit("\nmain()", 1)[0], "helper", "exec"), namespace)
    return namespace


class Updates(unittest.TestCase):
    def test_versions_compare_by_number_not_text(self):
        self.assertGreater(updates.parse("1.10.0"), updates.parse("1.9.9"))
        self.assertEqual(updates.parse("1.2"), (1, 2))

    def test_only_our_installer_name_is_accepted(self):
        self.assertTrue(updates.WINDOWS_INSTALLER.match("Androidbox-Setup-1.9.6.exe"))
        self.assertFalse(updates.WINDOWS_INSTALLER.match("DroidCore-Setup-1.9.6.exe"))
        self.assertFalse(updates.WINDOWS_INSTALLER.match("Androidbox-Setup-1.9.6.exe.zip"))

    def test_release_without_checksum_is_not_installable(self):
        self.assertFalse(updates.Release("2.0", "page", url="u", size=1).installable)
        self.assertTrue(updates.Release("2.0", "page", url="u", size=1, sha256="x").installable)


class ReleaseNotes(unittest.TestCase):
    def test_page_instructions_are_left_out_of_the_app(self):
        body = "Press Download, then open the installer. Settings are kept.\n\n- One\n- Two"
        self.assertEqual(updates.tidy_notes(body), "- One\n- Two")

    def test_notes_without_instructions_are_kept(self):
        self.assertEqual(updates.tidy_notes("- One\n- Two"), "- One\n- Two")

    def test_long_notes_are_cut_between_changes(self):
        body = "\n".join(f"- Change number {n} " + "x" * 40 for n in range(40))
        cut = updates.tidy_notes(body)
        self.assertLessEqual(len(cut), updates.NOTES_LIMIT + 2)
        self.assertTrue(cut.endswith("\n…"))
        self.assertTrue(cut.splitlines()[-2].endswith("x" * 40))


class Helper(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()

    def test_instances_use_the_port_the_emulator_reports_not_the_slot_port(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "data").mkdir()
            (home / "data" / "instances.json").write_text(
                '[{"id": "boxa", "name": "A", "slot": 1}, {"id": "boxb", "name": "B", "slot": 2}]')
            running = home / "avd" / "running"
            running.mkdir(parents=True)
            (running / "pid_1.ini").write_text("avd.id=boxa\nport.serial=5584\n")
            helper = self.helper
            helper["HOME"] = home
            helper["tempfile"] = types.SimpleNamespace(gettempdir=lambda: str(home))
            helper["os"] = types.SimpleNamespace(environ={"LOCALAPPDATA": str(home)}, path=os.path)
            serials = {item["name"]: item["serial"] for item in helper["instances"]()}
        self.assertEqual(serials["A"], "emulator-5584")
        # B's own port is taken by A, and B isn't running, so it can't claim that port
        self.assertNotEqual(serials["B"], "emulator-5584")

    def test_every_tool_is_dispatched(self):
        names = {tool["name"] for tool in self.helper["TOOLS"]}
        self.assertEqual(names, set(self.helper["DISPATCH"]))

    def test_every_tool_has_a_schema_and_description(self):
        for tool in self.helper["TOOLS"]:
            self.assertTrue(tool["description"], tool["name"])
            self.assertEqual(tool["inputSchema"]["type"], "object", tool["name"])
            for required in tool["inputSchema"].get("required", []):
                self.assertIn(required, tool["inputSchema"]["properties"], tool["name"])

    def test_quoting_survives_a_shell(self):
        text = "a%sb&c's \"q\" $x;(y)"
        quoted = self.helper["shell_quote"](text)
        shell = subprocess.run(["sh", "-c", "printf %s " + quoted], capture_output=True, text=True)
        if shell.returncode == 0:
            self.assertEqual(shell.stdout, text)

    def test_non_ascii_typing_is_refused_clearly(self):
        self.helper["resolve"] = lambda name: "emulator-5554"
        with self.assertRaises(self.helper["Problem"]):
            self.helper["tool_type_text"]({"text": "سلام"})


class EmulatorApi(unittest.TestCase):
    def test_running_takes_no_arguments(self):
        # Once shadowed by an app-listing method of the same name, which broke every status check
        import inspect
        self.assertEqual(list(inspect.signature(emulator.Emulator.running).parameters), ["self"])
        self.assertTrue(hasattr(emulator.Emulator, "running_apps"))


class Paths(unittest.TestCase):
    def test_droidcore_folder_is_renamed_back(self):
        local = Path(tempfile.mkdtemp())
        (local / "DroidCore").mkdir()
        (local / "DroidCore" / "marker.txt").write_text("kept")
        code = "from androidbox import paths; print(paths.MIGRATED, paths.DEFAULT_HOME.name)"
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                                env={**os.environ, "LOCALAPPDATA": str(local), "XDG_DATA_HOME": str(local)})
        self.assertEqual(result.stdout.split(), ["True", "Androidbox"], result.stderr)
        self.assertEqual((local / "Androidbox" / "marker.txt").read_text(), "kept")


class Names(unittest.TestCase):
    def test_app_names_come_from_packages(self):
        try:
            from androidbox.ui import pages
        except ImportError:
            self.skipTest("Qt isn't installed")
        self.assertEqual(pages.app_name("com.supercell.clashofclans"), "Clashofclans")


class AppsPage(unittest.TestCase):
    def test_search_narrows_and_running_apps_come_first(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            from types import SimpleNamespace as N

            from PySide6.QtWidgets import QApplication, QLabel, QLineEdit
            from androidbox.ui import pages
        except ImportError:
            self.skipTest("Qt isn't installed")
        app = QApplication.instance() or QApplication([])
        host = N(page="library", active=lambda: None, run=lambda *a, **k: None, set_game_fps=lambda *a: None,
                 prefs={"game_list": True})
        page = pages.LibraryPage(host)
        controller = N(on=True, apps=["com.supercell.clashofclans", "org.test.zed"], running={"org.test.zed"},
                       instance=N(name="Main"), start=lambda: None, emulator=None)
        page.refresh(controller)
        page.show()

        def packages():
            return [label.text().split("  ")[0] for label in page.findChildren(QLabel)
                    if label.isVisible() and label.text().startswith(("com.", "org."))]

        self.assertEqual(packages(), ["org.test.zed", "com.supercell.clashofclans"])
        page.findChild(QLineEdit).setText("clash")
        self.assertEqual(packages(), ["com.supercell.clashofclans"])

        def texts():
            return [label.text() for label in page.findChildren(QLabel) if label.isVisible()]

        self.assertIn("Installed · 1 of 2", texts())
        self.assertNotIn("No apps match that search.", texts())
        page.findChild(QLineEdit).setText("nothing like this")
        self.assertIn("No apps match that search.", texts())
        page.findChild(QLineEdit).setText("")
        self.assertIn("Installed · 2", texts())
        self.assertNotIn("No apps match that search.", texts())
        app.processEvents()


class ToastPlacement(unittest.TestCase):
    def test_toast_stays_at_the_bottom_centre_when_the_window_resizes(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            from androidbox.ui.widgets import Toast
        except ImportError:
            self.skipTest("Qt isn't installed")
        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        parent.resize(640, 480)
        toast = Toast(parent)
        # Shown at start-up, before the window has its real size
        toast.show_message("Androidbox updated", "good")
        parent.resize(1263, 837)
        parent.show()
        app.processEvents()
        self.assertAlmostEqual(toast.geometry().center().x(), 1263 // 2, delta=2)
        self.assertEqual(toast.geometry().bottom(), 837 - 24 - 1)


def solid(colour, width=40, height=80):
    return bytes(colour) * (width * height), width, height


class FakeScreen:
    """Stands in for the emulator: shows each picture in turn and keeps the last one"""

    def __init__(self, *pictures):
        self.pictures = list(pictures)
        self.sent = []
        self.touches = []

    def touch(self, *touches):
        self.touches.extend(touches)

    def pixels(self, width, height):
        return self.pictures.pop(0) if len(self.pictures) > 1 else self.pictures[0]

    def replay(self, payload):
        self.sent.append(payload)


def tap_events(at):
    down = pb.InputEvent(touch_event=pb.TouchEvent(touches=[pb.Touch(x=10, y=10, identifier=0, pressure=1)]))
    up = pb.InputEvent(touch_event=pb.TouchEvent(touches=[pb.Touch(x=10, y=10, identifier=0, pressure=0)]))
    return [[at, base64.b64encode(down.SerializeToString()).decode()],
            [at + 0.01, base64.b64encode(up.SerializeToString()).decode()]]


def two_tap_macro():
    return {"name": "t", "display": [40, 80], "speed": 1.0, "gap": 0, "duration": 0.31,
            "events": tap_events(0.0) + tap_events(0.3)}


class Vision(unittest.TestCase):
    def test_same_screen_has_no_difference_and_black_against_white_is_total(self):
        black, white = solid((0, 0, 0)), solid((255, 255, 255))
        a, b = vision.sample(*black), vision.sample(*white)
        self.assertEqual(vision.difference(a, vision.sample(*black)), 0)
        self.assertEqual(vision.difference(a, b), 1.0)

    def test_region_only_looks_inside_itself(self):
        width, height = 40, 80
        frame = bytearray(bytes((0, 0, 0)) * (width * height))
        for y in range(height // 2):
            for x in range(width):
                frame[(y * width + x) * 3:(y * width + x) * 3 + 3] = bytes((255, 255, 255))
        top = vision.sample(bytes(frame), width, height, (0, 0, 1, 0.4))
        bottom = vision.sample(bytes(frame), width, height, (0, 0.6, 1, 0.4))
        self.assertEqual(vision.difference(top, bottom), 1.0)

    def test_a_four_byte_pixel_frame_reads_the_same(self):
        rgb, rgba = solid((10, 20, 30)), (bytes((10, 20, 30, 255)) * (40 * 80), 40, 80)
        self.assertEqual(vision.sample(*rgb), vision.sample(*rgba))


class WaitSteps(unittest.TestCase):
    def area_step(self, timeout=30, then="stop"):
        reference = vision.encode(vision.sample(*solid((200, 0, 0))))
        return macros.new_step("area", (0, 0, 1, 1), reference, timeout=timeout, then=then)

    def test_waits_until_the_area_matches(self):
        screen = FakeScreen(solid((0, 0, 0)), solid((0, 0, 0)), solid((200, 0, 0)))
        result = macros.wait_for(screen, [40, 80], self.area_step(), threading.Event(), poll=0.001)
        self.assertTrue(result)
        self.assertEqual(screen.pictures, [solid((200, 0, 0))])

    def test_times_out_when_it_never_matches(self):
        result = macros.wait_for(FakeScreen(solid((0, 0, 0))), [40, 80], self.area_step(timeout=0.05),
                                 threading.Event(), poll=0.005)
        self.assertIs(result, False)

    def test_stopping_playback_ends_the_wait(self):
        stopped = threading.Event()
        stopped.set()
        self.assertIsNone(macros.wait_for(FakeScreen(solid((0, 0, 0))), [40, 80], self.area_step(), stopped))

    def test_still_needs_the_screen_to_stop_moving(self):
        moving = [solid((n * 40, 0, 0)) for n in range(5)]
        step = macros.new_step("still", hold=0.03, timeout=5)
        screen = FakeScreen(*moving, solid((9, 9, 9)))
        self.assertTrue(macros.wait_for(screen, [40, 80], step, threading.Event(), poll=0.01))
        self.assertEqual(screen.pictures, [solid((9, 9, 9))])

    def test_a_screen_that_never_settles_times_out(self):
        class Flicker(FakeScreen):
            count = 0

            def pixels(self, width, height):
                self.count += 1
                return solid((255 * (self.count % 2),) * 3)

        step = macros.new_step("still", hold=0.5, timeout=0.05)
        self.assertIs(macros.wait_for(Flicker(solid((0, 0, 0))), [40, 80], step, threading.Event(), poll=0.005),
                      False)

    def test_an_unreadable_screen_is_not_a_match(self):
        class Broken:
            def pixels(self, width, height):
                raise OSError("emulator gone")

        self.assertIs(macros.wait_for(Broken(), [40, 80], self.area_step(timeout=0.03), threading.Event(),
                                      poll=0.005), False)


class MacroEditing(unittest.TestCase):
    def test_a_step_goes_after_the_action_it_was_asked_for(self):
        macro = macros.add_step(two_tap_macro(), 0, macros.new_step("still"))
        found = macros.actions(macro)
        self.assertEqual(len(found), 3)
        self.assertIn("step", found[1])
        self.assertEqual([found[0]["label"].split()[0], found[2]["label"].split()[0]], ["Tap", "Tap"])
        self.assertEqual(found[2]["wait"], 0.29)

    def test_a_step_at_the_start_comes_first(self):
        found = macros.actions(macros.add_step(two_tap_macro(), -1, macros.new_step("still")))
        self.assertIn("step", found[0])

    def test_removing_a_step_leaves_the_taps_alone(self):
        macro = macros.add_step(two_tap_macro(), 0, macros.new_step("still"))
        macro = macros.remove_action(macro, 1)
        self.assertEqual([action["label"].split()[0] for action in macros.actions(macro)], ["Tap", "Tap"])
        self.assertEqual(len(macro["events"]), 4)

    def test_describe_says_what_the_step_waits_for(self):
        self.assertIn("stops changing", macros.describe_step(macros.new_step("still")))
        self.assertIn("no time limit", macros.describe_step(macros.new_step("still", timeout=0)))


class PlayerWithSteps(unittest.TestCase):
    def play(self, screen, macro):
        done, notes = threading.Event(), []
        macros.Player(screen, macro, on_done=done.set, on_note=notes.append)
        self.assertTrue(done.wait(10))
        return notes

    def step_macro(self, then="stop", timeout=0.15):
        reference = vision.encode(vision.sample(*solid((200, 0, 0))))
        step = macros.new_step("area", (0, 0, 1, 1), reference, timeout=timeout, then=then)
        return macros.add_step(two_tap_macro(), 0, step)

    def test_the_second_tap_waits_for_the_screen(self):
        screen = FakeScreen(*([solid((0, 0, 0))] * 2), solid((200, 0, 0)))
        notes = self.play(screen, self.step_macro(timeout=10))
        self.assertEqual(notes, [])
        self.assertEqual(len(screen.sent), 4)

    def test_a_missed_wait_stops_the_macro_and_says_so(self):
        screen = FakeScreen(solid((0, 0, 0)))
        notes = self.play(screen, self.step_macro())
        self.assertEqual(len(screen.sent), 2)
        self.assertEqual(len(notes), 1)
        self.assertIn("didn't happen in time", notes[0])

    def test_carry_on_anyway_plays_everything(self):
        screen = FakeScreen(solid((0, 0, 0)))
        notes = self.play(screen, self.step_macro(then="go"))
        self.assertEqual(len(screen.sent), 4)
        self.assertEqual(notes, [])

    def test_macros_without_steps_play_as_before(self):
        screen = FakeScreen(solid((0, 0, 0)))
        self.play(screen, two_tap_macro())
        self.assertEqual(len(screen.sent), 4)


def three_tap_macro():
    macro = two_tap_macro()
    macro["events"] += tap_events(0.6)
    return macro


def red_step(kind, **options):
    reference = vision.encode(vision.sample(*solid((200, 0, 0))))
    return macros.new_step(kind, (0, 0, 1, 1), reference, **options)


class Blocks(unittest.TestCase):
    def test_if_and_end_are_added_around_the_chosen_steps(self):
        macro = macros.add_steps(three_tap_macro(), 0, [red_step("if"), macros.new_step("end")], 1)
        kinds = [action["step"]["wait"] if "step" in action else "tap" for action in macros.actions(macro)]
        self.assertEqual(kinds, ["tap", "if", "tap", "end", "tap"])

    def test_a_block_asking_for_more_steps_than_there_are_stops_at_the_end(self):
        macro = macros.add_steps(three_tap_macro(), 0, [macros.new_step("repeat"), red_step("until")], 9)
        kinds = [action["step"]["wait"] if "step" in action else "tap" for action in macros.actions(macro)]
        self.assertEqual(kinds, ["tap", "repeat", "tap", "tap", "until"])

    def test_removing_one_end_removes_its_partner(self):
        macro = macros.add_steps(three_tap_macro(), 0, [red_step("if"), macros.new_step("end")], 1)
        macro = macros.remove_action(macro, 3)
        self.assertEqual(len(macros.actions(macro)), 3)
        self.assertEqual(len(macro["events"]), 6)

    def test_markers_without_a_partner_are_left_out(self):
        macro = macros.add_step(three_tap_macro(), 0, macros.new_step("end"))
        self.assertEqual(macros.pair_up(macro["events"]), {})

    def play(self, screen, macro):
        done, notes = threading.Event(), []
        macros.Player(screen, macro, on_done=done.set, on_note=notes.append)
        self.assertTrue(done.wait(15))
        return notes

    def if_macro(self):
        return macros.add_steps(three_tap_macro(), 0, [red_step("if"), macros.new_step("end")], 1)

    def test_the_steps_inside_an_if_run_when_the_area_matches(self):
        screen = FakeScreen(solid((200, 0, 0)))
        self.play(screen, self.if_macro())
        self.assertEqual(len(screen.sent), 6)

    def test_the_steps_inside_an_if_are_skipped_when_it_does_not(self):
        screen = FakeScreen(solid((0, 0, 0)))
        started = time.monotonic()
        self.play(screen, self.if_macro())
        self.assertEqual(len(screen.sent), 4)
        # The skipped step's time is skipped too, so the last tap isn't left waiting for it
        self.assertLess(time.monotonic() - started, 0.55)

    def test_repeat_runs_the_steps_again_until_the_area_matches(self):
        macro = macros.add_steps(three_tap_macro(), 0, [macros.new_step("repeat"), red_step("until")], 1)
        screen = FakeScreen(solid((0, 0, 0)), solid((0, 0, 0)), solid((200, 0, 0)))
        notes = self.play(screen, macro)
        self.assertEqual(notes, [])
        self.assertEqual(len(screen.sent), 2 + 3 * 2 + 2)

    def test_repeat_gives_up_after_its_limit_and_says_so(self):
        macro = macros.add_steps(three_tap_macro(), 0,
                                 [macros.new_step("repeat"), red_step("until", repeats=2)], 1)
        screen = FakeScreen(solid((0, 0, 0)))
        notes = self.play(screen, macro)
        self.assertEqual(len(screen.sent), 2 + 2 * 2)
        self.assertEqual(len(notes), 1)
        self.assertIn("repeated 2 times", notes[0])

    def test_repeat_can_carry_on_after_its_limit(self):
        macro = macros.add_steps(three_tap_macro(), 0,
                                 [macros.new_step("repeat"), red_step("until", repeats=2, then="go")], 1)
        screen = FakeScreen(solid((0, 0, 0)))
        self.assertEqual(self.play(screen, macro), [])
        self.assertEqual(len(screen.sent), 2 + 2 * 2 + 2)


def scene(x=20, y=40, width=64, height=128, noise=0):
    """A dark screen with a red square with a white dot in it, so there is only one place it fits"""
    frame = bytearray(bytes((10, 10, 10)) * (width * height))
    for dy in range(8):
        for dx in range(8):
            colour = (255, 255, 255) if (dx, dy) == (2, 5) else (200 + noise, 0, 0)
            at = ((y + dy) * width + x + dx) * 3
            frame[at:at + 3] = bytes(colour)
    return bytes(frame), width, height


SQUARE = (20 / 64, 40 / 128, 8 / 64, 8 / 128)
EMPTY = bytes((10, 10, 10)) * (64 * 128), 64, 128


class PictureSearch(unittest.TestCase):
    def picture(self):
        return vision.crop(*scene(), SQUARE)

    def test_a_single_colour_is_flat_and_a_drawing_is_not(self):
        self.assertTrue(vision.flat(bytes((90, 90, 90)) * 64))
        self.assertFalse(vision.flat(self.picture()[0]))

    def test_crop_cuts_out_the_marked_pixels(self):
        pixels, across, down = self.picture()
        self.assertEqual((across, down, len(pixels)), (8, 8, 8 * 8 * 3))

    def test_finds_the_picture_where_it_is(self):
        for x, y in ((20, 40), (0, 0), (56, 120), (31, 77)):
            hit = vision.find(*scene(x, y), self.picture(), 0.05)
            self.assertEqual(hit[:2], (x, y), (x, y))
            self.assertLess(hit[2], 0.01)

    def test_finds_it_with_a_little_colour_noise(self):
        hit = vision.find(*scene(33, 60, noise=12), self.picture(), 0.08)
        self.assertEqual(hit[:2], (33, 60))

    def test_does_not_find_a_picture_that_is_not_there(self):
        empty = bytes((10, 10, 10)) * (64 * 128), 64, 128
        self.assertIsNone(vision.find(*empty, self.picture(), 0.08))

    def test_a_picture_bigger_than_the_screen_is_not_found(self):
        self.assertIsNone(vision.find(*scene(), (bytes(3 * 70 * 10), 70, 10), 0.08))

    def test_a_four_byte_pixel_frame_works(self):
        frame, width, height = scene(12, 12)
        wide = bytearray()
        for at in range(0, len(frame), 3):
            wide.extend(frame[at:at + 3] + b"\xff")
        self.assertEqual(vision.find(bytes(wide), width, height, self.picture(), 0.05)[:2], (12, 12))

    def test_a_real_sized_screen_is_searched_quickly(self):
        frame = scene(250, 400, width=320, height=568)
        picture = vision.crop(*frame, (250 / 320, 400 / 568, 40 / 320, 40 / 568))
        started = time.monotonic()
        self.assertEqual(vision.find(*frame, picture, 0.08)[:2], (250, 400))
        self.assertLess(time.monotonic() - started, 3)


class FindSteps(unittest.TestCase):
    def find_step(self, **options):
        picture = macros.mark_picture(FakeScreen(scene()), [40, 80], SQUARE)
        return macros.new_step("find", SQUARE, picture=picture, display=[40, 80], **options)

    def play(self, screen, macro):
        done, notes = threading.Event(), []
        macros.Player(screen, macro, on_done=done.set, on_note=notes.append)
        self.assertTrue(done.wait(15))
        return notes

    def macro_with(self, step):
        return macros.add_step(two_tap_macro(), 0, step)

    def test_taps_the_middle_of_the_picture_once_it_shows_up(self):
        screen = FakeScreen(EMPTY, EMPTY, scene())
        notes = self.play(screen, self.macro_with(self.find_step(timeout=10)))
        self.assertEqual(notes, [])
        self.assertEqual(screen.touches, [(0, 15, 28, True), (0, 15, 28, False)])
        self.assertEqual(len(screen.sent), 4)

    def test_stops_and_says_so_when_it_never_shows_up(self):
        screen = FakeScreen(EMPTY)
        notes = self.play(screen, self.macro_with(self.find_step(timeout=0.15)))
        self.assertEqual(screen.touches, [])
        self.assertEqual(len(screen.sent), 2)
        self.assertIn("didn't happen in time", notes[0])

    def test_can_carry_on_without_tapping(self):
        screen = FakeScreen(EMPTY)
        self.play(screen, self.macro_with(self.find_step(timeout=0.15, then="go")))
        self.assertEqual(screen.touches, [])
        self.assertEqual(len(screen.sent), 4)

    def test_locate_says_where_the_picture_is_as_fractions(self):
        x, y = macros.locate(FakeScreen(scene()), [40, 80], self.find_step())
        self.assertAlmostEqual(x, 24 / 64)
        self.assertAlmostEqual(y, 44 / 128)

    def test_update_step_changes_its_settings_in_place(self):
        macro = self.macro_with(self.find_step())
        macros.update_step(macro, 1, timeout=60, then="go")
        step = macros.actions(macro)[1]["step"]
        self.assertEqual((step["timeout"], step["then"]), (60, "go"))


class LegacyEmulatorTests(unittest.TestCase):
    def test_only_the_android_4_1_image_uses_the_older_emulator(self):
        from androidbox import installer, paths
        self.assertTrue(installer.needs_legacy_emulator(installer.LEGACY_API))
        self.assertEqual(installer.emulator_exe(installer.LEGACY_API), paths.LEGACY_EMULATOR)
        for api in ("36", "30"):
            self.assertFalse(installer.needs_legacy_emulator(api))
            self.assertEqual(installer.emulator_exe(api), paths.EMULATOR)

    def test_android_4_1_never_gets_4_gb_of_ram(self):
        from androidbox import installer
        self.assertEqual(installer.usable_ram(installer.LEGACY_API, 8192), installer.LEGACY_MAX_RAM)
        self.assertEqual(installer.usable_ram(installer.LEGACY_API, 2048), 2048)
        self.assertEqual(installer.usable_ram("36", 8192), 8192)


class Regressions(unittest.TestCase):
    def test_no_class_defines_the_same_method_twice(self):
        # The second definition silently replaces the first: force_stop(package) once hid the force_stop()
        # that ends a hung emulator, so stopping one raised instead
        import ast
        for path in (ROOT / "androidbox").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ClassDef):
                    names = [item.name for item in node.body if isinstance(item, ast.FunctionDef)
                             and not item.decorator_list]
                    twice = sorted({name for name in names if names.count(name) > 1})
                    self.assertEqual(twice, [], f"{path.name}: {node.name}")

    def test_ending_the_emulator_and_stopping_an_app_are_separate(self):
        import inspect
        self.assertEqual(list(inspect.signature(emulator.Emulator.kill).parameters), ["self"])
        self.assertEqual(list(inspect.signature(emulator.Emulator.force_stop).parameters), ["self", "package"])

    def test_a_macro_cannot_be_renamed_out_of_its_folder(self):
        macros.write({"name": "Escape me", "duration": 0.0, "events": []})
        renamed = macros.update("Escape me", name="..\\..\\outside")
        self.assertNotIn("\\", renamed["name"])
        self.assertEqual(macros.file(renamed["name"]).parent, macros.file("x").parent)
        macros.delete(renamed["name"])

    def test_files_that_are_not_macros_are_left_out(self):
        folder = macros.file("x").parent
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "stray.json").write_text("[1, 2, 3]")
        (folder / "nameless.json").write_text('{"events": []}')
        macros.forget()
        self.assertTrue(all(isinstance(macro, dict) and "name" in macro for macro in macros.load()))
        for name in ("stray", "nameless"):
            (folder / f"{name}.json").unlink()
        macros.forget()

    def test_an_empty_macro_set_to_repeat_for_ever_ends_at_once(self):
        done = threading.Event()
        macros.Player(None, {"events": [], "gap": 0.0}, loops=0, on_done=done.set)
        self.assertTrue(done.wait(5))

    def test_a_damaged_macro_still_reports_that_it_ended(self):
        class Broken:
            def replay(self, payload):
                raise ValueError("not an input event")

        done = threading.Event()
        hook, threading.excepthook = threading.excepthook, lambda args: None
        try:
            macros.Player(Broken(), {"events": [[0.0, base64.b64encode(b"junk").decode()]]}, on_done=done.set)
            self.assertTrue(done.wait(5))
        finally:
            threading.excepthook = hook

    def test_a_download_cut_short_is_an_error_that_keeps_what_arrived(self):
        from unittest import mock
        from androidbox import installer

        class Response:
            status = 200

            def __init__(self):
                self.chunks = [b"abc", b""]

            def read(self, amount):
                return self.chunks.pop(0)

            def __enter__(self):
                return self

            def __exit__(self, *details):
                return False

        package = installer.Package("the test", installer.REPOSITORY + "file.zip", 10, "", "", Path("x"))
        partial = Path(tempfile.mkdtemp()) / "file.part"
        with mock.patch("urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(OSError):
                installer.fetch(package.url, partial, 0, package, lambda *progress: None)
        self.assertEqual(partial.read_bytes(), b"abc")

    def test_a_layout_always_has_four_direction_keys(self):
        from androidbox import keymap
        self.assertEqual(keymap.parse([{"kind": "joystick", "x": 0.5, "y": 0.5, "keys": ["W"]}])[0].keys,
                         ["W", "", "", ""])
        self.assertEqual(keymap.Control("tilt", 0.1, 0.5, keys=["", "A", "", "D"]).keys, ["", "A", "", "D"])
        engine = keymap.Engine()
        engine.use(keymap.parse([{"kind": "joystick", "x": 0.5, "y": 0.5, "keys": ["W"]}]))
        self.assertTrue(engine.press("W", True, 100, 100))

    def test_a_damaged_instance_entry_does_not_stop_the_rest_loading(self):
        import json
        from androidbox import paths
        good = {"id": "boxgood", "name": "Good", "slot": 1}
        paths.write_text(paths.INSTANCES, json.dumps([good, {"id": "boxbad"}, "nonsense", {**good, "slot": 99}]))
        self.assertEqual([instance.id for instance in instances.load()], ["boxgood"])
        paths.INSTANCES.unlink()

    def test_claude_config_is_only_rewritten_when_it_changes(self):
        import json
        config = Path(tempfile.mkdtemp()) / "claude.json"
        self.assertTrue(claude.edit_config(lambda servers: servers.pop("androidbox", None), config))
        self.assertFalse(config.exists())
        entry = {"command": "python"}
        self.assertTrue(claude.edit_config(lambda servers: servers.__setitem__("androidbox", entry), config))
        self.assertEqual(json.loads(config.read_text())["mcpServers"], {"androidbox": entry})
        config.write_text(config.read_text() + "\n\n")
        written = config.read_bytes()
        self.assertTrue(claude.edit_config(lambda servers: servers.__setitem__("androidbox", dict(entry)), config))
        self.assertEqual(config.read_bytes(), written)

    def test_an_input_stream_that_ended_hands_its_event_back(self):
        import queue
        from androidbox.bridge import Bridge
        bridge = Bridge.__new__(Bridge)
        bridge.outbox, bridge.closed = queue.Queue(), False
        live = threading.Event()
        live.set()
        events = bridge.pending(live)
        bridge.outbox.put("first")
        self.assertEqual(next(events), "first")
        live.clear()
        bridge.outbox.put("second")
        self.assertEqual(list(events), [])
        self.assertEqual(bridge.outbox.get_nowait(), "second")

    def test_a_rejected_shared_screen_falls_back_to_plain_images(self):
        # Emulator 37.3 refused the shared frame file and sent nothing, which left the screen blank (#25, #26)
        from unittest import mock
        from androidbox import bridge as bridge_module
        from androidbox.bridge import Bridge

        class Stream:
            def __init__(self, images):
                self.images, self.done = images, threading.Event()

            def __iter__(self):
                yield from self.images
                self.done.wait(5)

            def cancel(self):
                self.done.set()

        shared = []

        def stream(request, metadata):
            shared.append(request.transport.channel == pb.ImageTransport.MMAP)
            if shared[-1]:
                return Stream([])
            return Stream([pb.Image(image=bytes(2 * 2 * 3), format=pb.ImageFormat(width=2, height=2))])

        bridge = Bridge.__new__(Bridge)
        bridge.stub = types.SimpleNamespace(streamScreenshot=stream)
        bridge.metadata, bridge.screen, bridge.closed = [], None, False
        bridge.frames = Path(tempfile.mkdtemp()) / "androidbox-test.frame"
        bridge.copy_frames, bridge.fallback = False, threading.RLock()
        shown = threading.Event()
        with mock.patch.object(bridge_module, "SHARED_FRAME_WAIT", 0.2):
            bridge.watch(2, 2, lambda *frame: shown.set())
            self.assertTrue(shown.wait(5))
        self.assertEqual(shared, [True, False])
        bridge.unwatch()

    def test_the_log_is_searched_for_every_known_problem(self):
        from androidbox import diagnostics
        log = "ok\n  E AndroidRuntime: FATAL EXCEPTION: main\nI ActivityManager: ANR in com.game\nfine"
        found = diagnostics.findings(log)
        self.assertEqual([title for title, _, _ in found], ["App crash", "App not responding"])
        self.assertEqual(found[0][2], ["E AndroidRuntime: FATAL EXCEPTION: main"])

    def test_android_4_1_gets_an_sd_card_and_newer_versions_do_not(self):
        # Without one, /sdcard on Android 4.1 is a locked folder and OUYA games and its launcher can't write
        import shutil
        from androidbox import installer
        for api, expected in ((installer.LEGACY_API, "yes"), (installer.DEFAULT_API, "no")):
            instance = instances.Instance(id=f"sdcard{api}", name="Card", slot=0, api=api)
            instances.write_avd(instance)
            config = (instance.folder / "config.ini").read_text()
            self.assertIn(f"hw.sdCard={expected}\n", config)
            shutil.rmtree(instance.folder, ignore_errors=True)


class TypedTextTests(unittest.TestCase):
    def press(self, key, text, modifiers=None):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        return QKeyEvent(QEvent.Type.KeyPress, key, modifiers or Qt.KeyboardModifier.NoModifier, text)

    def test_layout_characters_are_sent_as_typed(self):
        from PySide6.QtCore import Qt
        from androidbox.ui.phone import typed_text
        # An Italian layout: Shift+apostrophe types "?", AltGr (Ctrl+Alt) types "@" and the euro sign
        self.assertEqual(typed_text(self.press(Qt.Key.Key_Question, "?", Qt.KeyboardModifier.ShiftModifier)), "?")
        both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        self.assertEqual(typed_text(self.press(Qt.Key.Key_At, "@", both)), "@")
        self.assertEqual(typed_text(self.press(Qt.Key.Key_E, chr(0x20ac), both)), chr(0x20ac))

    def test_shortcuts_and_named_keys_are_not_text(self):
        from PySide6.QtCore import Qt
        from androidbox.ui.phone import typed_text
        self.assertEqual(typed_text(self.press(Qt.Key.Key_C, chr(3), Qt.KeyboardModifier.ControlModifier)), "")
        self.assertEqual(typed_text(self.press(Qt.Key.Key_Return, chr(13))), "")
        self.assertEqual(typed_text(self.press(Qt.Key.Key_Space, " ")), "")
        self.assertEqual(typed_text(self.press(Qt.Key.Key_Shift, "")), "")


if __name__ == "__main__":
    unittest.main()


def test_legacy_gamepad_scancodes_are_distinct_and_cover_every_pad_button():
    from androidbox import emulator
    from androidbox.ui import phone
    codes = [code for code, _ in emulator.PAD_SCANCODES.values()]
    assert len(set(codes)) == len(codes)
    assert all(name.startswith("BUTTON_") for _, name in emulator.PAD_SCANCODES.values())
    assert phone.GAMEPAD_CODES == {name: code for name, (code, _) in emulator.PAD_SCANCODES.items()}


def test_proxy_argument_accepts_common_spellings():
    from androidbox.instances import proxy_argument
    assert proxy_argument("1.2.3.4:80") == "http://1.2.3.4:80"
    assert proxy_argument("u:p@1.2.3.4:80") == "http://u:p@1.2.3.4:80"
    assert proxy_argument("1.2.3.4:80:u:p") == "http://u:p@1.2.3.4:80"
    assert proxy_argument("socks5://1.2.3.4:80") == ""
    assert proxy_argument("ftp://1.2.3.4:80") == ""
    assert proxy_argument("nonsense") == ""
    assert proxy_argument("") == ""


def test_parse_proxy_recognises_socks():
    from androidbox.instances import parse_proxy, proxy_label
    assert parse_proxy("socks5://u:p@1.2.3.4:1080") == ("socks", "1.2.3.4", 1080, "u", "p")
    assert parse_proxy("socks5h://1.2.3.4:1080:u:p") == ("socks", "1.2.3.4", 1080, "u", "p")
    assert parse_proxy("socks://h.example:1080") == ("socks", "h.example", 1080, "", "")
    assert parse_proxy("1.2.3.4:80") == ("http", "1.2.3.4", 80, "", "")
    assert proxy_label("socks5://u:secret@1.2.3.4:1080") == "socks5://***@1.2.3.4:1080"
    assert proxy_label("1.2.3.4:80:u:secret") == "http://***@1.2.3.4:80"
    assert "secret" not in proxy_label("socks5://u:secret@1.2.3.4:1080")


def test_socks_relay_tunnels_http_through_socks5_with_login():
    import socket
    import threading
    from androidbox.socks_relay import Relay

    seen = {}

    def target():
        sock, _ = target_server.accept()
        seen["request"] = sock.recv(4096)
        sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nhi")
        sock.close()

    def socks():
        client, _ = socks_server.accept()
        assert client.recv(16) == b"\x05\x02\x00\x02"
        client.sendall(b"\x05\x02")
        login = client.recv(64)
        seen["login"] = login
        client.sendall(b"\x01\x00")
        request = client.recv(64)
        seen["request_head"] = request
        upstream = socket.create_connection(("127.0.0.1", target_server.getsockname()[1]))
        client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        def forward():
            try:
                for data in iter(lambda: client.recv(4096), b""):
                    upstream.sendall(data)
            except OSError:
                pass

        threading.Thread(target=forward, daemon=True).start()
        try:
            for data in iter(lambda: upstream.recv(4096), b""):
                client.sendall(data)
        except OSError:
            pass
        client.close()

    target_server = socket.socket()
    target_server.bind(("127.0.0.1", 0))
    target_server.listen(1)
    socks_server = socket.socket()
    socks_server.bind(("127.0.0.1", 0))
    socks_server.listen(1)
    threading.Thread(target=target, daemon=True).start()
    threading.Thread(target=socks, daemon=True).start()
    relay = Relay("127.0.0.1", socks_server.getsockname()[1], "user", "pw")
    try:
        for opener in (b"CONNECT example.test:80 HTTP/1.1\r\nHost: example.test:80\r\n\r\n",
                       b"GET http://example.test/a?b=1 HTTP/1.1\r\nHost: example.test\r\nProxy-Connection: keep-alive\r\n\r\n"):
            client = socket.create_connection(("127.0.0.1", relay.port), timeout=10)
            client.sendall(opener)
            if opener.startswith(b"CONNECT"):
                assert client.recv(4096).startswith(b"HTTP/1.1 200")
                client.sendall(b"GET / HTTP/1.1\r\n\r\n")
            reply = b""
            while not reply.endswith(b"hi"):
                chunk = client.recv(4096)
                assert chunk
                reply += chunk
            client.close()
            break
        assert seen["login"] == b"\x01\x04user\x02pw"
        assert b"example.test" in seen["request_head"]
        assert seen["request"].startswith(b"GET / HTTP/1.1")
    finally:
        relay.close()


def test_socks_relay_reports_a_dead_proxy_as_bad_gateway():
    import socket
    from androidbox.socks_relay import Relay
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    port = dead.getsockname()[1]
    dead.close()
    relay = Relay("127.0.0.1", port)
    try:
        client = socket.create_connection(("127.0.0.1", relay.port), timeout=10)
        client.sendall(b"CONNECT example.test:443 HTTP/1.1\r\n\r\n")
        assert client.recv(4096).startswith(b"HTTP/1.1 502")
    finally:
        relay.close()


def test_speaks_socks5_detects_socks_behind_an_http_spelling():
    import socket
    import threading
    from androidbox.socks_relay import speaks_socks5

    def serve(reply):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)

        def run():
            client, _ = server.accept()
            client.recv(16)
            client.sendall(reply)
            client.close()
            server.close()
        threading.Thread(target=run, daemon=True).start()
        return server.getsockname()[1]

    assert speaks_socks5("127.0.0.1", serve(b"\x05\x00"))
    assert not speaks_socks5("127.0.0.1", serve(b"HTTP/1.1 400 Bad Request\r\n\r\n"))
    assert not speaks_socks5("127.0.0.1", 1, timeout=1)


def _serve_once(reply):
    import socket
    import threading
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def run():
        client, _ = server.accept()
        client.recv(4096)
        client.sendall(reply)
        client.close()
        server.close()
    threading.Thread(target=run, daemon=True).start()
    return server.getsockname()[1]


def test_proxy_test_reports_what_is_wrong():
    from androidbox.socks_relay import check
    ok, _ = check("http", "127.0.0.1", _serve_once(b"HTTP/1.1 200 Connection established\r\n\r\n"))
    assert ok
    ok, message = check("http", "127.0.0.1", _serve_once(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"), "u", "p")
    assert not ok and "username or password" in message
    ok, message = check("http", "127.0.0.1", _serve_once(b"\x05\x00"))
    assert not ok and "socks5://" in message
    ok, message = check("http", "127.0.0.1", 1, timeout=1)
    assert not ok and "Couldn't use the proxy" in message
    assert instances.test_proxy("")[0] is False
    assert instances.test_proxy("nonsense")[0] is False


def test_startup_reason_reads_known_failures_and_ignores_normal_logs():
    from androidbox import diagnostics
    healthy = ("INFO         | Checking: hasSufficientDiskSpace\nINFO         |      Ok: met\n"
               "ERROR        | Error opening 'x/snapshots/default_boot/snapshot.pb' for writing.\n"
               "WARNING      | Failed to load snapshot 'default_boot'\nINFO | Guest GLES Driver: Auto\n")
    assert diagnostics.startup_findings(healthy) == []
    broken = "INFO | starting\nERROR | WHPX: Failed to create partition\nERROR | No space left on device\n"
    found = diagnostics.startup_findings(broken)
    assert [title for title, _, _ in found][0].startswith("Windows' virtualization")
    assert len(found) == 2 and "WHPX" in found[0][2]


def test_hardware_warnings_only_speak_when_something_is_off():
    mine = instances.Instance(id="a", name="a", slot=0, ram=8192)
    other = instances.Instance(id="b", name="b", slot=1, ram=8192)
    assert instances.hardware_warnings(mine, [mine], 16384, 200) == []
    assert instances.hardware_warnings(mine, [mine, other], 32768, 200) == []
    memory, = instances.hardware_warnings(mine, [mine, other], 16384, 200)
    assert "16 GB" in memory and "together" in memory
    disk, = instances.hardware_warnings(mine, [mine], 16384, 4.2)
    assert "4 GB" in disk


def test_themes_share_one_palette_dictionary():
    from androidbox.ui import theme
    colors = theme.COLORS
    try:
        theme.use("glitch")
        assert theme.COLORS is colors and colors["accent"] == "#9be8b8" and theme.glitched()
        assert "border-left" in theme.stylesheet()
        theme.use("nonsense")
        assert not theme.glitched() and colors["accent"] == "#3ddc84"
    finally:
        theme.use("classic")
    assert theme.THEMES.keys() == {value for _, value in theme.NAMES}
    assert all(set(theme.CLASSIC) <= set(palette) for palette in theme.THEMES.values())


def _serve_socks5(accept_login=True):
    """A one-connection SOCKS5 proxy that lets every request through"""
    import socket
    import threading
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def run():
        client, _ = server.accept()
        client.recv(16)
        client.sendall(b"\x05\x00")
        client.recv(64)
        client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        client.close()
        server.close()
    threading.Thread(target=run, daemon=True).start()
    return server.getsockname()[1]


def _closed_port():
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_probe_names_the_step_that_failed():
    from androidbox.socks_relay import probe
    keys = lambda steps: [(step.key, step.ok) for step in steps]
    assert keys(probe("socks", "127.0.0.1", _serve_socks5())) == [("lookup", True), ("connect", True),
                                                                  ("target", True)]
    refused = probe("socks", "127.0.0.1", _closed_port(), timeout=3)
    assert keys(refused) == [("lookup", True), ("connect", False)] and "refused" in refused[-1].detail
    missing = probe("http", "no-such-host.invalid", 8080, timeout=3)
    assert keys(missing) == [("lookup", False)] and "can't be looked up" in missing[0].detail
    wrong_kind = probe("socks", "127.0.0.1", _serve_once(b"HTTP/1.1 400 Bad Request\r\n\r\n"))
    assert keys(wrong_kind)[-1] == ("proxy", False) and "isn't a SOCKS5 proxy" in wrong_kind[-1].detail
    blocked = probe("http", "127.0.0.1", _serve_once(b"HTTP/1.1 403 Forbidden\r\n\r\n"))
    assert keys(blocked)[-1] == ("proxy", False) and "403" in blocked[-1].detail


def test_ping_verdict_and_vpn_interfaces():
    from androidbox.diagnostics import ping_verdict, vpn_interfaces
    assert ping_verdict("ping: unknown host example.com") == "dns"
    assert ping_verdict("64 bytes from 1.2.3.4: icmp_seq=1\n1 packets transmitted, 1 received") == "found"
    assert ping_verdict("1 packets transmitted, 0 received, 100% packet loss") == "silent"
    assert vpn_interfaces("dummy0\neth0\nlo\ntun0\n") == ["tun0"]
    assert vpn_interfaces("eth0\nlo\n") == []


def test_proxy_label_hides_a_login_even_in_text_that_isnt_a_proxy():
    from androidbox.instances import proxy_label
    assert "secret" not in proxy_label("ftp://user:secret@1.2.3.4:21")
    assert proxy_label("ftp://user:secret@1.2.3.4:21") == "ftp://***@1.2.3.4:21"
    assert "secret" not in proxy_label("1.2.3.4:abc:user:secret")
    assert proxy_label("nonsense") == "nonsense"
    assert proxy_label("") == ""


def _no_direct_internet(monkeypatch):
    """Makes example.com unreachable from the PC, and leaves every other address to the real thing"""
    from androidbox import socks_relay
    real = socks_relay.reach

    def reach(host, port, what, timeout=10):
        if host == "example.com":
            return [socks_relay.Step("lookup", True, f"Look up {what}", "1.2.3.4"),
                    socks_relay.Step("connect", False, f"Connect to {what}", "no answer")], None
        return real(host, port, what, timeout)
    monkeypatch.setattr(socks_relay, "reach", reach)


def test_network_report_explains_a_proxy_that_cant_be_reached(monkeypatch):
    from androidbox import diagnostics, socks_relay
    _no_direct_internet(monkeypatch)
    instance = instances.Instance(id="netcheck", name="Net", slot=0,
                                  proxy=f"socks5://user:secret@127.0.0.1:{_closed_port()}")
    answers = {"settings": (0, "null\n"), "ls": (0, "eth0\nlo\ntun0\n"), "ping": (1, "ping: unknown host example.com")}
    text, problems = diagnostics.network_report(instance, lambda *command, timeout=30: answers[command[1]])
    assert "secret" not in text and "socks5://***@127.0.0.1" in text
    assert [title for title, _, _ in problems] == ["The proxy doesn't work from this PC",
                                                   "Android can't look up web addresses"]
    assert "refused" in problems[0][2][0] and "VPN or tunnel" in text and "tun0" in text
    quiet, none = diagnostics.network_report(instances.Instance(id="netcheck", name="Net", slot=0))
    assert "Proxy setting: none" in quiet and "Android wasn't running" in quiet
    assert [title for title, _, _ in none] == ["This PC can't reach the Internet"]


def test_collect_adds_the_network_check_to_the_bundle(monkeypatch, tmp_path):
    import types
    import zipfile
    from androidbox import diagnostics, socks_relay
    _no_direct_internet(monkeypatch)
    instance = instances.Instance(id="netcheck", name="Net", slot=0, proxy="user:secret@no-such-host.invalid:8080")
    emulator = types.SimpleNamespace(instance=instance, running=lambda: False)
    target = tmp_path / "diagnostics.zip"
    problems = diagnostics.collect(emulator, target)
    with zipfile.ZipFile(target) as bundle:
        names = bundle.namelist()
        everything = "".join(bundle.read(name).decode("utf-8", "replace") for name in names)
        summary = bundle.read("summary.txt").decode()
    assert "network.txt" in names and problems >= 1
    assert "== Network: The proxy doesn't work from this PC" in summary
    assert "secret" not in everything


class GameList(unittest.TestCase):
    """The shared game list: the files in the games folder, and how the app reads and uses them"""

    def setUp(self):
        from androidbox import gamelist
        self.gamelist = gamelist
        gamelist.CACHE.unlink(missing_ok=True)
        gamelist.PLAYED.unlink(missing_ok=True)
        gamelist.cache.clear()

    def entry(self, **changes):
        return {"package": "com.example.game", "name": "Example", "works": "yes", **changes}

    def opener(self, text):
        class Response:
            def __init__(self):
                self.body = text.encode()

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        return lambda request, timeout: Response()

    def test_every_game_in_the_repository_checks_out(self):
        # The index itself is rewritten on main by the Game list workflow, so a pull request that only adds a
        # game's file passes here
        sys.path.insert(0, str(ROOT / "tools"))
        import build_games
        found = build_games.entries()
        self.assertTrue(found)
        for path, _, wrong in found:
            self.assertEqual(wrong, [], path.name)
        self.assertEqual(build_games.duplicates(found), [])
        self.assertTrue(self.gamelist.parse((ROOT / "games" / "index.json").read_text(encoding="utf-8")))

    def test_entries_that_are_wrong_say_why(self):
        problems = self.gamelist.problems
        self.assertEqual(problems(self.entry(android="36", fps=60, notes="Fine")), [])
        self.assertTrue(problems(self.entry(package="not a package")))
        self.assertTrue(problems(self.entry(works="maybe")))
        self.assertTrue(problems(self.entry(android=36)))
        self.assertTrue(problems(self.entry(fps=75)))
        self.assertTrue(problems(self.entry(notes="x" * 301)))
        self.assertTrue(problems(self.entry(download="https://example.com/game.apk")))
        self.assertTrue(problems(self.entry(controls=[{"kind": "tap", "x": 1.5, "y": 0.5, "key": "A"}])))
        self.assertTrue(problems(self.entry(controls=[{"kind": "macro", "x": 0.5, "y": 0.5, "key": "M"}])))
        self.assertTrue(problems(self.entry(controls=[{"kind": "tap", "x": 0.5, "y": 0.5, "script": "x"}])))
        self.assertEqual(problems(self.entry(controls=[{"kind": "swipe", "x": 0.5, "y": 0.5, "x2": 0.5, "y2": 0.1,
                                                        "key": "E"}])), [])

    def test_one_bad_entry_does_not_hide_the_rest(self):
        text = json.dumps({"format": 1, "games": [self.entry(), self.entry(package="com.other.game", works="?")]})
        self.assertEqual(list(self.gamelist.parse(text)), ["com.example.game"])
        with self.assertRaises(ValueError):
            self.gamelist.parse(json.dumps({"format": 2, "games": []}))

    def test_the_list_is_kept_for_offline_use_and_fetched_once_a_day(self):
        gamelist = self.gamelist
        text = gamelist.build([self.entry()])
        self.assertTrue(gamelist.stale())
        self.assertIn("com.example.game", gamelist.refresh(opener=self.opener(text)))
        self.assertFalse(gamelist.stale())
        gamelist.cache.clear()
        self.assertEqual(gamelist.entry("com.example.game")["name"], "Example")

        def offline(request, timeout):
            raise OSError("no network")

        self.assertIn("com.example.game", gamelist.refresh(force=True, opener=offline))
        self.assertIn("com.example.game", gamelist.refresh(force=True, opener=self.opener("not json")))

    def test_a_setup_is_used_and_a_shared_one_leaves_out_macros(self):
        from androidbox import keymap, profiles
        gamelist = self.gamelist
        profiles.start()
        package = "com.example.game"
        controls = [{"kind": "joystick", "x": 0.14, "y": 0.68, "keys": ["W", "A", "S", "D"]},
                    {"kind": "tap", "x": 0.88, "y": 0.66, "key": "Space"}]
        self.assertEqual(gamelist.apply(self.entry(fps=60, controls=controls)), ["frame rate", "controls"])
        self.assertEqual(profiles.game(package)["fps"], 60)
        self.assertEqual([control.kind for control in keymap.load(package)], ["joystick", "tap"])

        keymap.save(package, [*keymap.load(package), keymap.Control(kind="macro", x=0.5, y=0.5, key="M",
                                                                     macro="Farm")])
        shared = gamelist.entry_for(package, "Example", "partly", "  Turn graphics down  ", android="36", fps=60)
        self.assertEqual(gamelist.problems(shared), [])
        self.assertEqual([control["kind"] for control in shared["controls"]], ["joystick", "tap"])
        self.assertEqual(shared["notes"], "Turn graphics down")
        self.assertEqual(gamelist.summary(shared), "Partly works on Android 16  ·  has a setup")
        self.assertEqual(gamelist.summary(shared, "36"), "Partly works on Android 16  ·  has a setup")
        self.assertEqual(gamelist.summary(shared, "35"), "Partly works on Android 16, this is Android 15")
        self.assertEqual(gamelist.summary(self.entry()), "Works")
        keymap.save(package, [])
        profiles.set_game(package, fps=0)

    def test_the_apps_page_shows_what_the_list_says(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            from types import SimpleNamespace as N

            from PySide6.QtWidgets import QApplication, QLabel
            from androidbox.ui import pages
        except ImportError:
            self.skipTest("Qt isn't installed")
        app = QApplication.instance() or QApplication([])
        text = self.gamelist.build([self.entry(android="36", fps=60, notes="Turn graphics down")])
        self.gamelist.refresh(opener=self.opener(text))
        host = N(page="library", active=lambda: None, run=lambda *a, **k: None, set_game_fps=lambda *a: None,
                 prefs={"game_list": True})
        page = pages.LibraryPage(host)
        controller = N(on=True, apps=["com.example.game"], running=set(), instance=N(name="Main", api="35"),
                       start=lambda: None, emulator=None)
        page.refresh(controller)
        texts = [label.text() for label in page.findChildren(QLabel)]
        self.assertIn("Example", texts)
        self.assertIn("Game list: Works on Android 16, this is Android 15", texts)
        app.processEvents()

    def test_a_play_store_link_only_takes_a_package_name(self):
        self.assertEqual(self.gamelist.play_link("com.example.game"), "market://details?id=com.example.game")
        for bad in ("com.example.game' ; reboot", "com.example game", "noperiod", ""):
            with self.assertRaises(ValueError):
                self.gamelist.play_link(bad)

    def test_opening_a_link_quotes_it_for_the_device_shell(self):
        from types import SimpleNamespace as N
        calls = []
        fake = N(adb=lambda *args, timeout=30: calls.append(args) or (0, ""))
        emulator.Emulator.open_url(fake, "market://details?id=com.example.game")
        self.assertEqual(calls[0][-1], "'market://details?id=com.example.game'")
        self.assertIn("android.intent.action.VIEW", calls[0])

    def test_crashes_in_androids_event_log_are_found_for_one_game(self):
        log = ("--------- beginning of events\n"
               "11-27 10:00:00.000  1234  1250 I am_crash: [5678,0,com.example.game,953794116,"
               "java.lang.RuntimeException,boom,Game.java,12,0]\n"
               "11-27 10:01:00.000  1234  1250 I am_anr  : [0,5679,com.example.game,953794116,Input dispatching]\n"
               "11-27 10:02:00.000  1234  1250 I am_crash: [5680,0,com.example.game.helper,1,x,y,z,1,0]\n"
               "11-27 10:03:00.000  1234  1250 I am_proc_start: [0,5681,10100,com.example.game,activity]\n")
        found = self.gamelist.crash_lines(log, "com.example.game")
        self.assertEqual(len(found), 2)
        self.assertEqual(self.gamelist.crash_lines(log, "com.other"), [])

    def test_play_is_added_up_and_a_crash_counts_once(self):
        gamelist = self.gamelist
        crash = "11-27 10:00:00.000 I am_crash: [5678,0,com.example.game,1,x,y,z,1,0]"
        gamelist.record_play("com.example.game", "36", 120, [crash])
        record = gamelist.record_play("com.example.game", "36", 200.4, [crash])
        self.assertEqual((record["seconds"], record["sessions"], record["crashes"]), (320, 2, 1))
        self.assertIsNone(gamelist.play_record("com.example.game", "35"), "Android versions mixed up")

    def test_a_game_is_ready_to_report_after_a_fair_run_and_only_until_done(self):
        gamelist = self.gamelist
        gamelist.record_play("com.example.game", "36", gamelist.REPORT_AFTER - 60)
        self.assertEqual(gamelist.to_report(), [])
        gamelist.record_play("com.example.game", "36", 60)
        self.assertEqual([record["package"] for record in gamelist.to_report("36")], ["com.example.game"])
        self.assertEqual(gamelist.to_report("35"), [])
        gamelist.mark("com.example.game", "36", "done")
        self.assertEqual(gamelist.to_report(), [])

        # A game that dies on start is worth a report after a few tries
        for number in range(3):
            gamelist.record_play("com.example.crash", "36", 5, [f"I am_crash: [{number},0,com.example.crash,1]"])
        record = gamelist.play_record("com.example.crash", "36")
        self.assertTrue(gamelist.worth_reporting(record))
        self.assertEqual(gamelist.guess_works(record), "no")
        self.assertEqual(gamelist.guess_notes(record), "Closes by itself as soon as it opens.")

    def test_a_game_the_list_already_covers_on_this_android_isnt_drafted(self):
        gamelist = self.gamelist
        gamelist.refresh(opener=self.opener(gamelist.build([self.entry(android="36")])))
        gamelist.record_play("com.example.game", "36", gamelist.REPORT_AFTER)
        gamelist.record_play("com.example.game", "35", gamelist.REPORT_AFTER)
        self.assertEqual([record["api"] for record in gamelist.to_report()], ["35"])

    def test_a_draft_guesses_from_what_was_seen_and_opens_as_a_new_file_on_github(self):
        from urllib.parse import parse_qs, urlparse
        gamelist = self.gamelist
        self.assertEqual(gamelist.guess_works({"seconds": 900}), "yes")
        self.assertEqual(gamelist.guess_notes({"seconds": 900}), "")
        self.assertEqual(gamelist.guess_works({"seconds": 900, "crashes": 2}), "partly")
        self.assertEqual(gamelist.guess_notes({"seconds": 900, "crashes": 2}), "Closed by itself 2 times while playing.")
        self.assertEqual(gamelist.duration(20), "under a minute")
        self.assertEqual(gamelist.duration(25 * 60), "25 minutes")
        self.assertEqual(gamelist.duration(3 * 3600), "3 hours")
        entry = gamelist.entry_for("com.example.game", "Example & Co", "yes", "50% faster?", android="36")
        link = urlparse(gamelist.propose_link(entry))
        self.assertEqual(link.path, "/Wolklaw/Androidbox/new/main/games")
        query = parse_qs(link.query)
        self.assertEqual(query["filename"], ["com.example.game.json"])
        self.assertEqual(json.loads(query["value"][0]), entry)

    def offer_window(self, **prefs):
        from types import SimpleNamespace as N
        offers = []
        window = N(prefs={"game_list": True, "game_list_offered": [], **prefs}, offers=offers,
                   offer=N(show_offer=lambda text, action, then: offers.append(text)),
                   use_game_setup=lambda *a: None)
        window.set_pref = lambda key, value: window.prefs.__setitem__(key, value)
        return window

    def test_a_listed_games_setup_is_offered_once_and_only_when_it_isnt_set_up(self):
        try:
            from androidbox.ui.window import MainWindow
        except ImportError:
            self.skipTest("Qt isn't installed")
        from types import SimpleNamespace as N
        from androidbox import keymap, profiles
        profiles.start()
        controls = [{"kind": "tap", "x": 0.5, "y": 0.5, "key": "Space"}]
        text = self.gamelist.build([self.entry(fps=60, controls=controls),
                                    self.entry(package="com.example.plain")])
        self.gamelist.refresh(opener=self.opener(text))
        window = self.offer_window()
        MainWindow.offer_game_setup(window, N(package="com.example.game"))
        self.assertEqual(window.offers, ["The game list has a frame rate and controls for Example. Use them?"])
        MainWindow.offer_game_setup(window, N(package="com.example.game"))
        self.assertEqual(len(window.offers), 1, "offered a second time")
        MainWindow.offer_game_setup(window, N(package="com.example.plain"))
        self.assertEqual(len(window.offers), 1, "offered a game with nothing to use")

        window = self.offer_window()
        keymap.save("com.example.game", keymap.parse(controls))
        MainWindow.offer_game_setup(window, N(package="com.example.game"))
        self.assertEqual(window.offers, [], "offered over controls you set up yourself")
        keymap.save("com.example.game", [])

        window = self.offer_window(game_list=False)
        MainWindow.offer_game_setup(window, N(package="com.example.game"))
        self.assertEqual(window.offers, [], "offered with the game list turned off")

    def test_playing_a_game_with_drafts_on_notes_its_time_and_offers_its_entry_once(self):
        try:
            from androidbox.ui.window import MainWindow
        except ImportError:
            self.skipTest("Qt isn't installed")
        from types import SimpleNamespace as N
        from unittest import mock
        gamelist = self.gamelist
        crash = "11-27 10:00:00.000 I am_crash: [5678,0,com.example.game,1,x,y,z,1,0]"
        emulator_ = N(apps=lambda: ["com.example.game"], crash_log=lambda: crash)
        controller = N(instance=N(id="a", api="36"), state="on", on=True, package=None, apps=None, emulator=emulator_)
        window = self.offer_window(game_list_drafts=True)
        window.sessions = {}
        window.offer.isVisible = lambda: False
        window.run = lambda work, then=None, failed=None: then(work())
        window.track_play = lambda c: MainWindow.track_play(window, c)
        window.end_play = lambda c, *rest: MainWindow.end_play(window, c, *rest)
        clock = [1000.0]
        with mock.patch("time.monotonic", lambda: clock[0]):
            for package in ("com.example.game", "com.android.launcher3", "com.example.game", None):
                controller.package = package
                window.track_play(controller)
                clock[0] += gamelist.REPORT_AFTER / 2
        record = gamelist.play_record("com.example.game", "36")
        self.assertEqual((record["seconds"], record["sessions"], record["crashes"]), (gamelist.REPORT_AFTER, 2, 1))
        self.assertIsNone(gamelist.play_record("com.android.launcher3", "36"), "noted an app Android came with")
        self.assertEqual(len(window.offers), 1)
        self.assertIn("doesn't say how", window.offers[0])

        # Off, nothing is noted
        gamelist.PLAYED.unlink()
        window.prefs["game_list_drafts"] = False
        controller.package = "com.example.game"
        window.track_play(controller)
        controller.package = None
        window.track_play(controller)
        self.assertEqual(gamelist.played(), {})

    def test_the_game_list_page_filters_and_offers_what_fits(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            from types import SimpleNamespace as N

            from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QPushButton
            from androidbox.ui import pages
        except ImportError:
            self.skipTest("Qt isn't installed")
        app = QApplication.instance() or QApplication([])
        text = self.gamelist.build([self.entry(fps=60), self.entry(package="com.other.racer", name="Racer",
                                                                     works="no")])
        self.gamelist.refresh(opener=self.opener(text))
        controller = N(on=True, apps=["com.example.game"], instance=N(name="Main", api="36"))
        host = N(page="gamelist", active=lambda: controller, run=lambda *a, **k: None,
                 prefs={"game_list": True, "game_list_drafts": True})
        self.gamelist.record_play("com.example.played", "36", self.gamelist.REPORT_AFTER, ["I am_crash: [1,0,com.example.played,1]"])
        page = pages.GameListPage(host)
        page.refresh()
        page.show()

        def shown():
            return [label.text() for label in page.findChildren(QLabel) if label.isVisible()]

        def buttons():
            return [button.text() for button in page.findChildren(QPushButton) if button.isVisibleTo(page)]

        self.assertIn("Games · 2", shown())
        self.assertIn("Played here, not on the list · 1", shown())
        self.assertIn("Played 10 minutes on Android 16  ·  1 crash", shown())
        self.assertIn("Draft it…", buttons())
        self.assertIn("Use setup", buttons())
        self.assertIn("Open", buttons())
        # A game that doesn't work isn't sent to Google Play
        self.assertNotIn("Google Play", buttons())
        filters = page.findChild(QComboBox)
        filters.setCurrentIndex(filters.findData("no"))
        self.assertIn("Games · 1 of 2", shown())
        self.assertIn("Racer", shown())
        self.assertNotIn("Example", shown())
        filters.setCurrentIndex(filters.findData(""))
        page.findChild(QLineEdit).setText("example")
        self.assertIn("Games · 1 of 2", shown())

        host.prefs["game_list"] = False
        page.refresh()
        from PySide6.QtCore import QEvent
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        self.assertEqual(buttons(), ["Turn it on"])
        app.processEvents()


def test_stream_state_reads_volume_and_mute_from_dumpsys():
    modern = ("- STREAM_VOICE_CALL:\n   Muted: false\n   Max: 5\n- STREAM_MUSIC:\n   Muted: true\n"
              "   Muted Internally: false\n   Min: 0\n   Max: 25\n   streamVolume:7\n"
              "   Current: 2 (speaker): 7, 40000000 (default): 20\n- STREAM_ALARM:\n   Muted: false\n")
    assert emulator.stream_state(modern, "STREAM_MUSIC") == {"muted": True, "level": 7, "max": 25}
    older = "- STREAM_MUSIC:\n   Muted: false\n   Max: 15\n   Current: 4 (headset): 3, 2 (speaker): 9\n"
    assert emulator.stream_state(older, "STREAM_MUSIC") == {"muted": False, "level": 9, "max": 15}
    legacy = "- STREAM_MUSIC:\n   Mute count: 0\n   Current: 2: 11, 4: 15\n"
    assert emulator.stream_state(legacy, "STREAM_MUSIC") == {"muted": False, "level": 11, "max": None}
    assert emulator.stream_state("", "STREAM_MUSIC") is None


def test_volume_text_reads_like_the_toolbar_shows_it():
    from androidbox.ui.controller import volume_text
    assert volume_text({"muted": False, "level": 5, "max": 15}) == "Volume 5/15"
    assert volume_text({"muted": True, "level": 5, "max": 15}) == "Volume 5/15, muted"
    assert volume_text(None) == "Volume unknown"
