# PyInstaller build for Windows, run by build.ps1: the windowed app and the console exe for the `androidbox`
# command, in one folder so they share the same Python, Qt and libraries
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ICON = os.path.join(ROOT, "assets", "androidbox.ico")
VERSION = os.path.join(ROOT, "build", "version_info.txt")

datas, binaries, hidden = [(ICON, "assets")], [], []
for package in ("sdl2dll", "av"):
    found = collect_all(package)
    datas += found[0]
    binaries += found[1]
    hidden += found[2]


def analysis(script):
    return Analysis([script], pathex=[ROOT], datas=datas, binaries=binaries, hiddenimports=hidden,
                    excludes=["tkinter"], noarchive=False)


def program(found, name, console):
    return EXE(PYZ(found.pure), found.scripts, [], exclude_binaries=True, name=name, console=console,
               upx=False, icon=ICON, version=VERSION if os.path.exists(VERSION) else None)


app = analysis(os.path.join(ROOT, "Androidbox.pyw"))
command = analysis(os.path.join(SPECPATH, "androidbox-cli.py"))

COLLECT(program(app, "Androidbox", console=False), app.binaries, app.datas,
        program(command, "androidbox-cli", console=True), command.binaries, command.datas,
        name="Androidbox", upx=False)
