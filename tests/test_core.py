"""Logic that doesn't need a phone or a window. Run from the repo root: python -m unittest discover tests"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANDROIDBOX_HOME", tempfile.mkdtemp(prefix="androidbox-test-"))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp(prefix="androidbox-local-"))

import base64  # noqa: E402
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
        self.assertTrue(updates.INSTALLER.match("Androidbox-Setup-1.9.6.exe"))
        self.assertFalse(updates.INSTALLER.match("DroidCore-Setup-1.9.6.exe"))
        self.assertFalse(updates.INSTALLER.match("Androidbox-Setup-1.9.6.exe.zip"))

    def test_release_without_checksum_is_not_installable(self):
        self.assertFalse(updates.Release("2.0", "page", url="u", size=1).installable)
        self.assertTrue(updates.Release("2.0", "page", url="u", size=1, sha256="x").installable)


class Helper(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()

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
                                env={**os.environ, "LOCALAPPDATA": str(local)})
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
        host = N(page="library", active=lambda: None, run=lambda *a, **k: None, set_game_fps=lambda *a: None)
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
        app.processEvents()


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


if __name__ == "__main__":
    unittest.main()
