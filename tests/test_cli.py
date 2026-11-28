"""The androidbox command, groups, the processor limit and the permission tools, without a phone or a window"""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANDROIDBOX_HOME", tempfile.mkdtemp(prefix="androidbox-test-"))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp(prefix="androidbox-local-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidbox import cli, emulator, instances, native  # noqa: E402
from test_core import load_helper  # noqa: E402


def instance(name, group="", slot=0):
    return instances.Instance(id=name.lower(), name=name, slot=slot, group=group)


class Commands(unittest.TestCase):
    def test_commands_go_to_the_command_line_and_window_options_do_not(self):
        self.assertTrue(cli.wanted(["start", "Pixel"]))
        self.assertTrue(cli.wanted(["--version"]))
        self.assertTrue(cli.wanted(["help"]))
        self.assertFalse(cli.wanted([]))
        self.assertFalse(cli.wanted(["--instance", "pixel"]))

    def test_every_command_has_a_handler(self):
        for name in cli.COMMANDS:
            extra = {"start": ["--all"], "stop": ["--all"], "wait": ["--all"], "install": ["a", "b.apk"],
                     "launch": ["a", "b"], "apps": ["a"], "shell": ["a", "ls"], "screenshot": ["a"],
                     "record": ["a", "5"], "macro": ["list"]}.get(name, [])
            args = cli.parser().parse_args([name, *extra])
            self.assertTrue(callable(args.handler), name)

    def test_group_and_macro_options_parse(self):
        args = cli.parser().parse_args(["start", "--group", "Farm", "--no-wait"])
        self.assertEqual(args.group, "Farm")
        args = cli.parser().parse_args(["macro", "play", "Pixel", "Daily", "--times", "3", "--report", "out"])
        self.assertEqual((args.name, args.macro, args.times, args.report), ("Pixel", "Daily", 3, "out"))

    def test_instances_are_chosen_by_name_group_or_all(self):
        known = [instance("Pixel", "Farm"), instance("Tablet", "farm", 1), instance("Other", slot=2)]
        with mock.patch.object(cli, "everything", return_value=known):
            pick = lambda *words: cli.chosen(cli.parser().parse_args(["stop", *words]))  # noqa: E731
            self.assertEqual([i.name for i in pick("--group", "FARM")], ["Pixel", "Tablet"])
            self.assertEqual([i.name for i in pick("other")], ["Other"])
            self.assertEqual(len(pick("--all")), 3)
            with self.assertRaisesRegex(cli.Failure, "Groups: Farm"):
                pick("--group", "Nope")
            with self.assertRaisesRegex(cli.Failure, "Instances: Pixel, Tablet, Other"):
                pick("Nope")
            with self.assertRaises(cli.Failure):
                pick()

    def test_report_is_written_as_json_and_escaped_html(self):
        with tempfile.TemporaryDirectory() as folder:
            runs = [{"run": 1, "seconds": 4.2, "app": "com.game", "crashes": [], "screenshot": "run-1.png"},
                    {"run": 2, "seconds": 3.0, "app": None, "crashes": ["am_crash: <boom>"]}]
            cli.write_report(Path(folder), instance("Pixel"), {"name": "Daily & more"}, runs)
            summary = json.loads((Path(folder) / "report.json").read_text())
            self.assertEqual(summary["crashed_runs"], 1)
            page = (Path(folder) / "report.html").read_text()
            self.assertIn("Daily &amp; more", page)
            self.assertIn("am_crash: &lt;boom&gt;", page)
            self.assertNotIn("<boom>", page)


class Instances(unittest.TestCase):
    def test_group_and_processor_limit_are_saved(self):
        saved = instances.from_dict(json.loads(json.dumps(instances.asdict(
            instances.Instance(id="a", name="A", slot=0, group="Farm", cpu_limit=25)))))
        self.assertEqual((saved.group, saved.cpu_limit), ("Farm", 25))

    def test_reading_without_repair_never_writes(self):
        with mock.patch.object(instances, "recover", return_value=True), \
                mock.patch.object(instances, "save") as save:
            instances.load(repair=False)
            save.assert_not_called()
            instances.load()
            save.assert_called_once()

    def test_emulator_pid_with_a_trailing_nul_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "hardware-qemu.ini.lock"
            lock.write_text("12345\0")
            with mock.patch.object(emulator.Emulator, "lock", new=lock):
                self.assertEqual(emulator.Emulator(instance("Pixel")).qemu_pid(), 12345)
            lock.write_text("")
            with mock.patch.object(emulator.Emulator, "lock", new=lock):
                self.assertIsNone(emulator.Emulator(instance("Pixel")).qemu_pid())


class ProcessorLimit(unittest.TestCase):
    def test_quota_is_a_share_of_every_core(self):
        self.assertEqual(native.cpu_quota(25, cores=16), 4_000_000)
        self.assertEqual(native.cpu_quota(50, cores=1), 500_000)
        self.assertEqual(native.cpu_quota(0), native.INFINITY)

    @unittest.skipIf(native.WINDOWS, "Linux applies it through systemd")
    def test_limit_is_clamped_before_it_reaches_systemd(self):
        with mock.patch.object(native, "_set_scope") as scope:
            self.assertTrue(native.set_cpu_limit(1, 250))
            self.assertEqual(scope.call_args[0][1][0][0], "CPUQuotaPerSecUSec")
        with mock.patch.object(native, "_set_scope", side_effect=OSError):
            self.assertFalse(native.set_cpu_limit(1, 50))


class Groups(unittest.TestCase):
    def test_a_group_typed_another_way_joins_the_existing_one(self):
        from androidbox.ui import window
        changed = {}
        host = types.SimpleNamespace(page="apps", groups=lambda: ["Farm"],
                                     set_automation=lambda controller, **values: changed.update(values))
        controller = types.SimpleNamespace(instance=instance("Pixel"))
        window.MainWindow.set_group(host, controller, "  farm ")
        self.assertEqual(changed, {"group": "Farm"})
        changed.clear()
        window.MainWindow.set_group(host, controller, "Night   shift")
        self.assertEqual(changed, {"group": "Night shift"})


class PermissionTools(unittest.TestCase):
    DUMPSYS = """Packages:
  Package [com.game] (abc):
    requested permissions:
      android.permission.CAMERA
    install permissions:
      android.permission.INTERNET: granted=true
    User 0: installed=true
      runtime permissions:
        android.permission.CAMERA: granted=false, flags=[ USER_SENSITIVE_WHEN_GRANTED]
        android.permission.POST_NOTIFICATIONS: granted=true, flags=[ ]
"""
    OLD_DUMPSYS = """Packages:
  Package [com.game] (abc):
    grantedPermissions:
      android.permission.INTERNET
      android.permission.CAMERA
    other: x
"""

    def setUp(self):
        self.helper = load_helper()
        self.helper["resolve"] = lambda name: "emulator-5580"

    def answer(self, text):
        self.helper["adb"] = lambda serial, *args, **options: text

    def test_short_names_get_the_android_prefix(self):
        self.assertEqual(self.helper["permission_name"]("camera"), "android.permission.CAMERA")
        self.assertEqual(self.helper["permission_name"]("com.android.vending.BILLING"), "com.android.vending.BILLING")

    def test_granted_and_missing_permissions_are_listed(self):
        self.answer(self.DUMPSYS)
        text = self.helper["tool_app_permissions"]({"package": "com.game"})[0]["text"]
        granted, missing = text.split("Not granted:")
        self.assertIn("INTERNET", granted)
        self.assertIn("POST_NOTIFICATIONS", granted)
        self.assertIn("CAMERA", missing)
        self.assertNotIn("CAMERA", granted)

    def test_android_4_lists_granted_permissions_under_a_heading(self):
        self.answer(self.OLD_DUMPSYS)
        text = self.helper["tool_app_permissions"]({"package": "com.game"})[0]["text"]
        self.assertIn("android.permission.CAMERA", text.split("Not granted:")[0])
        self.assertNotIn("other", text)

    def test_missing_app_is_a_problem_not_a_crash(self):
        self.answer("Unable to find package: com.nope")
        with self.assertRaises(self.helper["Problem"]):
            self.helper["tool_app_permissions"]({"package": "com.nope"})

    def test_android_before_6_cannot_change_permissions(self):
        self.answer("19")
        with self.assertRaisesRegex(self.helper["Problem"], "before 6.0"):
            self.helper["tool_grant_permission"]({"package": "com.game", "permission": "CAMERA"})

    def test_androids_stack_trace_is_cut_to_the_reason(self):
        def adb(serial, *args, **options):
            if "getprop" in args:
                return "36"
            raise self.helper["Problem"]("Exception occurred while executing 'grant':\n"
                                         "java.lang.SecurityException: Permission INTERNET is not changeable\n"
                                         "\tat com.android.server.Something")
        self.helper["adb"] = adb
        with self.assertRaisesRegex(self.helper["Problem"], "^Permission INTERNET is not changeable$"):
            self.helper["tool_grant_permission"]({"package": "com.game", "permission": "INTERNET"})

    def test_plugin_copy_has_the_same_tools(self):
        plugin = (ROOT / "plugin" / "server" / "androidbox.py").read_text(encoding="utf-8")
        for name in ("app_permissions", "grant_permission", "revoke_permission"):
            self.assertIn(f'"name": "{name}"', plugin)
            self.assertIn(f"def tool_{name}(arguments)", plugin)


if __name__ == "__main__":
    unittest.main()
