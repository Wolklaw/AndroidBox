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

from androidbox import claude, emulator, instances, updates  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
