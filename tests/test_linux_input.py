"""The Linux pieces under global shortcuts and updates: Androidbox's own D-Bus messages, shortcuts in Linux's terms,
reading keyboards, and picking the Linux release. None of these need a desktop. Run from the repo root:
python -m unittest discover tests"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANDROIDBOX_HOME", tempfile.mkdtemp(prefix="androidbox-test-"))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp(prefix="androidbox-local-"))

from androidbox import dbus, hotkeys, native, updates  # noqa: E402


class Messages(unittest.TestCase):
    def round_trip(self, signature, values):
        data = dbus.encode(1, 7, {dbus.PATH: "/a/b", dbus.MEMBER: "Go"}, signature, values)
        self.assertEqual(dbus.message_size(data[:16]), len(data))
        return dbus.decode(data)

    def test_a_message_reads_back_as_it_was_written(self):
        values = [True, 3, -2, 2 ** 40, 1.5, "héllo", ["a", "bc"], (7, "x"),
                  {"handle_token": dbus.Variant("s", "t1"), "n": dbus.Variant("u", 5)}]
        message = self.round_trip("buixdsas(ys)a{sv}", values)
        self.assertEqual(message.serial, 7)
        self.assertEqual((message.path, message.member), ("/a/b", "Go"))
        # Variants come back as the plain values in them
        self.assertEqual(message.body, [*values[:7], (7, "x"), {"handle_token": "t1", "n": 5}])

    def test_the_shortcut_portals_bind_call_is_marshalled(self):
        shortcuts = [("ctrl-alt-b", {"description": dbus.Variant("s", "Boss key"),
                                     "preferred_trigger": dbus.Variant("s", "CTRL+ALT+b")})]
        message = self.round_trip("oa(sa{sv})sa{sv}", ["/org/x/session/1", shortcuts, "",
                                                         {"handle_token": dbus.Variant("s", "abx1")}])
        self.assertEqual(message.body[1], [("ctrl-alt-b", {"description": "Boss key",
                                                           "preferred_trigger": "CTRL+ALT+b"})])

    def test_an_empty_array_still_pads_to_its_elements(self):
        message = self.round_trip("a(ss)u", [[], 9])
        self.assertEqual(message.body, [[], 9])

    def test_signatures_split_into_complete_types(self):
        self.assertEqual(dbus.split("sa{sv}a(ya{sv})u"), ["s", "a{sv}", "a(ya{sv})", "u"])
        with self.assertRaises(ValueError):
            dbus.split("z")

    def test_a_cut_off_message_is_an_error_not_garbage(self):
        data = dbus.encode(1, 1, {dbus.PATH: "/"}, "s", ["long enough"])
        with self.assertRaises(ValueError):
            dbus.decode(data[:-6])

    def test_bus_addresses_unescape(self):
        self.assertEqual(dbus.unescape("/run/user/1000/a%20b"), "/run/user/1000/a b")
        with mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/x"}):
            self.assertEqual(dbus.session_address(), "unix:path=/x")


class Combos(unittest.TestCase):
    def test_a_shortcut_becomes_the_xdg_trigger_and_a_steady_id(self):
        item = hotkeys.combo("Ctrl+Alt+B", "Boss key")
        self.assertEqual(item.trigger, "CTRL+ALT+b")
        self.assertEqual(item.identifier, "ctrl-alt-b")
        self.assertEqual(item.keysym, ord("b"))
        self.assertEqual(item.label, "Boss key")
        self.assertEqual(hotkeys.combo("Meta+Shift+F5").trigger, "SHIFT+LOGO+F5")
        self.assertEqual(hotkeys.combo("Ctrl+1").keysym, ord("1"))
        self.assertEqual(hotkeys.combo("Ctrl+Del").name, "Delete")

    def test_a_shortcut_without_a_modifier_or_with_an_odd_key_is_refused(self):
        self.assertIsNone(hotkeys.combo("B"))
        self.assertIsNone(hotkeys.combo(""))
        self.assertIsNone(hotkeys.combo("Ctrl+Alt+Print"))


DEVICES = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd leds event3
B: EV=120013
B: KEY=402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe

I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
H: Handlers=kbd event1
B: EV=3
B: KEY=10000000000000 0

I: Bus=0003 Vendor=046d Product=c08b Version=0111
N: Name="Logitech Mouse"
H: Handlers=mouse0 event5
B: EV=17
B: KEY=ffff0000 0 0 0 0
"""


class Keyboards(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_only_devices_with_letter_keys_count_as_keyboards(self):
        devices = self.folder / "devices"
        devices.write_text(DEVICES)
        self.assertEqual(hotkeys.keyboards(devices), [hotkeys.INPUT / "event3"])
        self.assertEqual(hotkeys.keyboards(self.folder / "missing"), [])

    def test_the_layout_comes_from_xkb_variables_then_the_system_setting(self):
        with mock.patch.dict(os.environ, {"XKB_DEFAULT_LAYOUT": "fr", "XKB_DEFAULT_VARIANT": "azerty"}):
            names = hotkeys.layout_names()
        self.assertEqual((names["layout"], names["variant"]), ("fr", "azerty"))

    def test_key_codes_fall_back_to_a_us_keyboard(self):
        self.assertEqual(hotkeys.key_code(ord("b"), {}), 48)
        self.assertEqual(hotkeys.key_code(0xFFBE, {}), 59)  # F1
        self.assertEqual(hotkeys.key_code(ord("b"), {ord("b"): 49}), 49)

    def test_a_held_modifier_and_a_press_fire_the_shortcut_once(self):
        pressed = []
        reader = hotkeys.KeyboardShortcuts.__new__(hotkeys.KeyboardShortcuts)
        reader.pressed, reader.devices, reader.held, reader.layout = pressed.append, {}, set(), {}
        refused, _ = reader.bind([hotkeys.combo("Ctrl+Alt+B"), hotkeys.combo("Ctrl+Alt+B")])
        self.assertEqual(refused, ["Ctrl+Alt+B"])  # the same keys twice
        read_end, write_end = os.pipe()
        os.set_blocking(read_end, False)
        reader.devices["kbd"] = read_end

        def keys(*events):
            os.write(write_end, b"".join(hotkeys.EVENT.pack(0, 0, kind, code, value)
                                         for kind, code, value in events))
            reader.read("kbd", read_end)

        keys((1, 29, 1), (1, 56, 1), (4, 4, 48), (1, 48, 1), (1, 48, 2), (1, 48, 0))
        self.assertEqual(pressed, ["Ctrl+Alt+B"])
        keys((1, 56, 0), (1, 48, 1))  # Alt let go: just Ctrl+B
        self.assertEqual(pressed, ["Ctrl+Alt+B"])
        os.close(write_end)
        reader.read("kbd", read_end)  # the device went away
        self.assertEqual(reader.devices, {})

    @unittest.skipIf(sys.platform == "win32", "keyboards are opened the Linux way")
    def test_listening_to_just_some_keyboards_is_not_offered(self):
        with mock.patch.object(hotkeys, "keyboards", return_value=[Path("/nonexistent/event9")]):
            with self.assertRaises(OSError):
                hotkeys.KeyboardShortcuts(lambda text: None)


class LinuxRelease(unittest.TestCase):
    def test_linux_picks_the_linux_package_from_the_release(self):
        base = updates.DOWNLOADS + "v9.9.9/"
        release = {"tag_name": "v9.9.9", "html_url": "https://example.invalid/r", "body": "", "assets": [
            {"name": "Androidbox-Setup-9.9.9.exe", "browser_download_url": base + "Androidbox-Setup-9.9.9.exe",
             "size": 1, "digest": "sha256:aa"},
            {"name": "Androidbox-9.9.9-linux.tar.gz", "browser_download_url": base + "Androidbox-9.9.9-linux.tar.gz",
             "size": 2, "digest": "sha256:bb"}]}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *details):
                return False

        for windows, name, digest in ((False, "Androidbox-9.9.9-linux.tar.gz", "bb"),
                                      (True, "Androidbox-Setup-9.9.9.exe", "aa")):
            with mock.patch.object(native, "WINDOWS", windows), \
                    mock.patch.object(updates.urllib.request, "urlopen",
                                      return_value=Response(json.dumps(release).encode())):
                found = updates.latest()
            self.assertEqual((found.name, found.sha256), (name, digest))


if __name__ == "__main__":
    unittest.main()
