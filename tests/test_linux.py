"""The Linux side of Androidbox. These switch native.WINDOWS off where they have to, so they run on either system, and
on a real Linux machine (the Linux workflow) they run for real. Run from the repo root: python -m unittest discover tests"""
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANDROIDBOX_HOME", tempfile.mkdtemp(prefix="androidbox-test-"))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp(prefix="androidbox-local-"))
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp(prefix="androidbox-xdg-"))

from androidbox import diagnostics, gamepad, hotkeys, installer, instances, native, paths, system  # noqa: E402

LINUX = mock.patch.object(native, "WINDOWS", False)
fake_sysconf = lambda name: 100 if name == "SC_CLK_TCK" else 4096


class Processes(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        patches = [LINUX, mock.patch.object(native, "PROC", self.folder),
                   mock.patch.object(os, "sysconf", fake_sysconf, create=True)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def process(self, name, fields):
        (self.folder / "42").mkdir(exist_ok=True)
        (self.folder / "42" / "stat").write_text(f"42 ({name}) {fields}\n")

    def test_processor_time_counts_user_and_system_ticks(self):
        # state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt utime stime
        self.process("qemu-system-x86_64", "S 1 42 42 0 -1 4194560 100 0 0 0 700 300 0 0 20 0")
        self.assertEqual(native.process_times(42), 10.0)

    def test_a_process_name_with_spaces_and_brackets_does_not_shift_the_fields(self):
        self.process("my (odd) name", "R 1 42 42 0 -1 4194560 100 0 0 0 150 50 0 0 20 0")
        self.assertEqual(native.process_times(42), 2.0)

    def test_memory_is_resident_pages_times_page_size(self):
        (self.folder / "42").mkdir()
        (self.folder / "42" / "statm").write_text("5000 250 100 10 0 400 0\n")
        self.assertEqual(native.process_memory(42), 250 * 4096)

    def test_a_process_that_is_gone_reads_as_none(self):
        self.assertIsNone(native.process_times(999))
        self.assertIsNone(native.process_memory(999))

    def test_host_memory_is_read_in_megabytes(self):
        (self.folder / "meminfo").write_text("MemTotal:       32768000 kB\nMemFree:        1000 kB\n")
        self.assertEqual(native.host_memory(), 32000)

    def test_a_zombie_is_not_alive(self):
        self.process("qemu", "Z 1 42 42 0 -1 0 0 0 0 0 0 0 0 0 20 0")
        with mock.patch.object(os, "kill", lambda pid, sig: None):
            self.assertFalse(native.process_alive(42))
        self.process("qemu", "S 1 42 42 0 -1 0 0 0 0 0 0 0 0 0 20 0")
        with mock.patch.object(os, "kill", lambda pid, sig: None):
            self.assertTrue(native.process_alive(42))

    def test_the_real_python_process_is_alive(self):
        # Asked the way this system really does it: on Windows os.kill(pid, 0) would send this process a Ctrl+C
        with mock.patch.object(native, "WINDOWS", sys.platform == "win32"),                 mock.patch.object(native, "PROC", Path("/proc")):
            self.assertTrue(native.process_alive(os.getpid()))


class WhatDiffers(unittest.TestCase):
    def test_programs_have_no_exe_suffix_on_linux(self):
        with LINUX:
            self.assertEqual(native.exe("adb"), "adb")
            self.assertEqual(native.child_options(), {"start_new_session": True})
            self.assertEqual(native.quiet_options(), {})

    def test_crash_dialog_helpers_do_nothing_on_linux(self):
        with LINUX:
            with native.without_crash_dialogs():
                pass
            self.assertFalse(native.close_crash_dialogs())
            self.assertEqual(native.short_path("/home/a b/x"), "/home/a b/x")
            with mock.patch.object(native, "_desktop_animations", return_value=True):
                self.assertTrue(native.animations_allowed())

    def test_discovery_folders_include_where_linux_emulators_write(self):
        with LINUX, mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000", "USER": "spark"}):
            folders = {folder.as_posix() for folder in paths.discovery_folders()}
        self.assertIn("/run/user/1000/avd/running", folders)
        self.assertIn("/tmp/android-spark/avd/running", folders)

    def test_this_systems_paths_are_consistent(self):
        self.assertEqual(paths.ADB.name, native.exe("adb"))
        self.assertEqual(paths.EMULATOR.name, native.exe("emulator"))
        self.assertTrue(paths.ICON.is_file(), paths.ICON)

    def test_only_one_virtualization_hint_is_shown_and_it_is_this_systems(self):
        titles = [title for title, _, _ in diagnostics.START_FINDINGS if title.endswith("isn't working")]
        self.assertEqual(titles, ["Windows' virtualization isn't working" if native.WINDOWS
                                  else "KVM isn't working"])

    def test_kvm_trouble_in_the_log_is_recognised(self):
        found = diagnostics.START_PATTERN.search("emulator: ERROR: /dev/kvm is not accessible".lower())
        if not native.WINDOWS:
            self.assertTrue(found)


class Packages(unittest.TestCase):
    def archive(self, host, arch=None):
        text = "<archive>" + (f"<host-os>{host}</host-os>" if host else "") + (f"<host-arch>{arch}</host-arch>"
                                                                           if arch else "") + "</archive>"
        return ET.fromstring(text)

    def test_the_right_build_is_picked_for_each_system(self):
        for system_name in ("windows", "linux"):
            with mock.patch.object(installer, "HOST_OS", system_name):
                self.assertTrue(installer.runs_here(self.archive(system_name, "x64")))
                self.assertTrue(installer.runs_here(self.archive(system_name)))
                self.assertTrue(installer.runs_here(self.archive(None)))
                other = "linux" if system_name == "windows" else "windows"
                self.assertFalse(installer.runs_here(self.archive(other, "x64")))
                self.assertFalse(installer.runs_here(self.archive(system_name, "aarch64")))

    def test_the_old_android_4_1_emulator_is_the_build_for_this_system(self):
        self.assertIn(f"emulator-{installer.HOST_OS}_x64-7033400.zip", installer.LEGACY_EMULATOR_URL)

    @unittest.skipIf(sys.platform == "win32", "permissions only mean something on Linux")
    def test_unpacking_keeps_the_executable_bit_and_symlinks(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        archive = folder / "sdk.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            program = zipfile.ZipInfo("tools/emulator")
            program.external_attr = (stat.S_IFREG | 0o755) << 16
            zipped.writestr(program, "#!/bin/sh\n")
            plain = zipfile.ZipInfo("tools/readme.txt")
            plain.external_attr = (stat.S_IFREG | 0o644) << 16
            zipped.writestr(plain, "hi")
            link = zipfile.ZipInfo("tools/emulator-link")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            zipped.writestr(link, "emulator")
        installer.extract(archive, folder / "sdk" / "emulator", lambda done, total: None)
        unpacked = folder / "sdk" / "emulator"
        # tools/ is the only thing inside, so it is the folder that became "emulator"
        self.assertTrue(os.access(unpacked / "emulator", os.X_OK))
        self.assertFalse(os.access(unpacked / "readme.txt", os.X_OK))
        self.assertTrue((unpacked / "emulator-link").is_symlink())


class AndroidFiles(unittest.TestCase):
    def test_the_emulators_ini_files_use_the_separator_of_the_system_they_are_on(self):
        self.assertEqual(instances.SEP, os.sep)

    def test_an_image_folder_is_read_back_from_either_kind_of_separator(self):
        for text in ("system-images/android-36/google_apis_playstore/x86_64/",
                     "system-images\\android-36\\google_apis_playstore\\x86_64\\"):
            api = text.split("android-")[-1].replace("\\", "/").split("/")[0]
            self.assertEqual(api, "36")


class Lock(unittest.TestCase):
    def emulator(self):
        from androidbox import emulator
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        return emulator.Emulator(mock.Mock(folder=folder)), folder

    def test_windows_keeps_the_pid_in_a_lock_folder_and_linux_in_a_lock_file(self):
        machine, folder = self.emulator()
        (folder / "hardware-qemu.ini.lock").mkdir()
        (folder / "hardware-qemu.ini.lock" / "pid").write_text("123")
        self.assertEqual(machine.qemu_pid(), 123)
        machine.clear_lock()
        self.assertFalse(machine.lock.exists())
        machine.lock.write_text("456\n")
        self.assertEqual(machine.qemu_pid(), 456)
        machine.clear_lock()
        self.assertFalse(machine.lock.exists())


class Desktop(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        for patch in (LINUX, mock.patch.dict(os.environ, {"ANDROIDBOX_COMMAND": "/usr/bin/androidbox"})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_shortcut_is_a_desktop_file_that_quotes_odd_names(self):
        file = self.folder / "Candy Crush on Android 1.desktop"
        system.shortcut(file, ["--instance", "a b", "--launch", "com.king.candy", "--fullscreen"],
                        "Opens Candy Crush in Androidbox")
        text = file.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Name=Candy Crush on Android 1", text)
        exec_line = next(line for line in text.splitlines() if line.startswith("Exec=")).removeprefix("Exec=")
        self.assertEqual(shlex.split(exec_line),
                         ["/usr/bin/androidbox", "--instance", "a b", "--launch", "com.king.candy", "--fullscreen"])
        self.assertIn("StartupWMClass=Androidbox", text)
        if sys.platform != "win32":
            self.assertTrue(os.access(file, os.X_OK))

    def test_a_percent_sign_in_a_name_is_not_taken_for_a_field_code(self):
        file = self.folder / "x.desktop"
        system.shortcut(file, ["--launch", "100%"], "d")
        line = next(line for line in file.read_text(encoding="utf-8").splitlines() if line.startswith("Exec="))
        self.assertIn("100%%", line)

    def test_starting_at_sign_in_writes_and_removes_an_autostart_entry(self):
        entry = self.folder / "autostart" / "androidbox.desktop"
        with mock.patch.object(system, "AUTOSTART_FILE", entry):
            self.assertFalse(system.starts_with_windows())
            system.start_with_windows(True)
            self.assertTrue(system.starts_with_windows())
            text = entry.read_text(encoding="utf-8")
            self.assertIn("Exec=/usr/bin/androidbox --background", text)
            system.start_with_windows(False)
            self.assertFalse(entry.exists())
            system.start_with_windows(False)

    def test_a_copy_not_installed_with_install_sh_leaves_updates_to_the_system(self):
        with mock.patch.dict(os.environ, {"ANDROIDBOX_INSTALL": "", "ANDROIDBOX_PREFIX": ""}):
            self.assertFalse(system.can_update())
            with self.assertRaises(OSError):
                system.install_update(self.folder / "x")

    @unittest.skipIf(sys.platform == "win32", "read-only folders are checked with statvfs, which Windows lacks")
    def test_a_copy_install_sh_put_in_the_users_folder_can_update(self):
        prefix = self.folder / "androidbox-app"
        (prefix / "app").mkdir(parents=True)
        (prefix / "app" / "Androidbox.pyw").write_text("")
        with mock.patch.dict(os.environ, {"ANDROIDBOX_INSTALL": "user", "ANDROIDBOX_PREFIX": str(prefix)}):
            self.assertEqual(system.linux_install(), ("user", prefix))
            self.assertTrue(system.can_update())
            with mock.patch.object(system, "read_only", return_value=True):
                self.assertFalse(system.can_update())
        with mock.patch.dict(os.environ, {"ANDROIDBOX_INSTALL": "system", "ANDROIDBOX_PREFIX": str(prefix)}):
            with mock.patch.object(shutil, "which", return_value="/usr/bin/pkexec"):
                self.assertTrue(system.can_update())
            with mock.patch.object(shutil, "which", return_value=None):
                self.assertFalse(system.can_update())
        with mock.patch.dict(os.environ, {"ANDROIDBOX_INSTALL": "user", "ANDROIDBOX_PREFIX": str(self.folder)}):
            self.assertIsNone(system.linux_install())

    def test_an_update_package_unpacks_to_the_folder_with_install_sh(self):
        import io
        import tarfile

        def package(name, members):
            archive = self.folder / name
            with tarfile.open(archive, "w:gz") as tar:
                for member, data in members:
                    info = tarfile.TarInfo(member)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            return archive

        good = package("good.tar.gz", [("Androidbox-9.9.9/Androidbox.pyw", b""),
                                       ("Androidbox-9.9.9/packaging/linux/install.sh", b"#!/bin/bash\n")])
        source = system.unpack(good, self.folder / "update-source")
        self.assertEqual(source, self.folder / "update-source" / "Androidbox-9.9.9")
        self.assertTrue((source / "packaging" / "linux" / "install.sh").is_file())

        other = package("other.tar.gz", [("something/packaging/linux/install.sh", b"")])
        with self.assertRaises(ValueError):
            system.unpack(other, self.folder / "update-source")

        escape = package("escape.tar.gz", [("Androidbox-9.9.9/Androidbox.pyw", b""),
                                           ("Androidbox-9.9.9/packaging/linux/install.sh", b""),
                                           ("../outside.txt", b"no")])
        with self.assertRaises(Exception):
            system.unpack(escape, self.folder / "update-source")
        self.assertFalse((self.folder / "outside.txt").exists())

    def test_an_update_runs_install_sh_after_the_app_quits(self):
        prefix = self.folder / "androidbox-app"
        (prefix / "app").mkdir(parents=True)
        (prefix / "app" / "Androidbox.pyw").write_text("")
        download = self.folder / "downloads" / "Androidbox-9.9.9-linux.tar.gz"
        download.parent.mkdir()
        with mock.patch.dict(os.environ, {"ANDROIDBOX_INSTALL": "system", "ANDROIDBOX_PREFIX": str(prefix)}), \
                mock.patch.object(system, "unpack", return_value=self.folder / "update-source" / "x") as unpack, \
                mock.patch.object(system, "after_exit") as after:
            system.install_update(download, relaunch=("/usr/bin/androidbox", ""))
        self.assertEqual(unpack.call_args.args[1], self.folder / "update-source")
        script, values = after.call_args.args[:2]
        self.assertIn("install.sh", script)
        self.assertEqual(values["UPDATE_AS"], "pkexec")
        self.assertEqual(values["UPDATE_OPTIONS"], "")
        self.assertEqual(values["UPDATE_PREFIX"], str(prefix))

    def test_a_python_launch_quotes_the_script_path(self):
        with mock.patch.dict(os.environ, {"ANDROIDBOX_COMMAND": ""}), \
                mock.patch.object(paths, "BUNDLE", Path("/opt/with space")):
            target, prefix = system.launcher()
            self.assertEqual(target, sys.executable)
            self.assertEqual([Path(word) for word in shlex.split(prefix)], [Path("/opt/with space/Androidbox.pyw")])

    @unittest.skipIf(sys.platform == "win32", "needs a POSIX shell with the process tools")
    def test_restarting_runs_the_launcher_after_this_process_has_gone(self):
        marker = self.folder / "started"
        code = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('yes')"
        with mock.patch.object(system, "launcher", lambda: (sys.executable, f"-c {shlex.quote(code)}")):
            helper = mock.Mock()
            real_popen = subprocess.Popen

            def start(args, **options):
                # Stand in for "this process": a short-lived one the helper waits for
                waiter = real_popen([sys.executable, "-c", "import time; time.sleep(0.4)"])
                options["env"] = {**options["env"], "ANDROIDBOX_WAIT_FOR": str(waiter.pid)}
                helper.process = real_popen(args, **options)
                helper.waiter = waiter

            with mock.patch.object(subprocess, "Popen", start):
                system.restart()
            helper.waiter.wait()
            helper.process.wait(timeout=20)
        self.assertEqual(marker.read_text(), "yes")


class Controls(unittest.TestCase):
    def test_global_shortcuts_are_refused_on_linux_instead_of_failing(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
        app = QCoreApplication.instance() or QCoreApplication([])
        if not hotkeys.LINUX:
            self.skipTest("Needs Linux")
        with mock.patch.object(hotkeys, "BACKENDS", ()):
            keys = hotkeys.Hotkeys(app)
            answers = []
            loop = QEventLoop()
            keys.refused.connect(lambda refused, why: (answers.append((refused, why)), loop.quit()))
            QTimer.singleShot(5000, loop.quit)
            keys.set({"Ctrl+Alt+B": lambda: None, "B": lambda: None})
            loop.exec()
        self.assertEqual(answers, [(["B", "Ctrl+Alt+B"], hotkeys.UNSUPPORTED)])
        self.assertEqual(keys.kind, "")

    def test_without_xinput_there_is_just_no_controller_instead_of_an_error(self):
        with LINUX:
            self.assertIsNone(gamepad.XInputPads().poll())


class Fonts(unittest.TestCase):
    def test_the_bundled_icon_font_has_every_icon_the_interface_uses(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QGuiApplication
        except ImportError:
            self.skipTest("PySide6 is not installed")
        from androidbox.ui import theme
        app = QGuiApplication.instance() or QGuiApplication([])
        self.assertGreaterEqual(QFontDatabase.addApplicationFont(str(paths.BUNDLE / "assets" / "androidbox-icons.ttf")), 0)
        metrics = QFontMetrics(QFont("Androidbox Icons"))
        missing = [name for name, glyph in theme.ICONS.items() if not metrics.inFontUcs4(ord(glyph))]
        self.assertEqual(missing, [])
        self.assertIsNotNone(app)

    def test_linux_text_falls_back_to_a_font_the_desktop_has(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        try:
            from PySide6.QtGui import QGuiApplication
        except ImportError:
            self.skipTest("PySide6 is not installed")
        from androidbox.ui import theme
        app = QGuiApplication.instance() or QGuiApplication([])
        before = (theme.Fonts.text, theme.Fonts.strong, theme.Fonts.icons, theme.Fonts.strong_weight)
        try:
            theme.Fonts.load_linux()
            self.assertEqual(theme.Fonts.icons, "Androidbox Icons")
            self.assertTrue(theme.Fonts.text)
            self.assertTrue(theme.Fonts.strong)
        finally:
            theme.Fonts.text, theme.Fonts.strong, theme.Fonts.icons, theme.Fonts.strong_weight = before
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
