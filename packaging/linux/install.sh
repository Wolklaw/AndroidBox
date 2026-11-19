#!/usr/bin/env bash
# Install Androidbox on Linux, from a checkout of this repository:
#
#   bash packaging/linux/install.sh [--user] [--deps] [--prefix DIR] [--no-test] [--uninstall]
#
# Without options it installs for every user and needs root: the program goes under /usr/lib/androidbox, the
# `androidbox` command in /usr/bin, and the menu entry and icon under /usr/share. That is what the SparkOS image
# build does.
#
# --user       install for the current user only (~/.local), no root needed
# --deps       install the system libraries it needs with dnf, skipping what is already there. Other
#              distributions: see "Linux" in the README for the package names
# --prefix     put the program somewhere else than /usr/lib/androidbox (or ~/.local/share/androidbox-app)
# --python     the Python to use, if you don't want the one it finds. Androidbox's Qt packages support Python 3.10
#              to 3.14, so a newer system Python (Fedora 45 has 3.15) is passed over for python3.13
# --no-test    skip the check at the end that the app starts
# --uninstall  remove what this script installed. Android images and instances (~/.local/share/Androidbox) stay
#
# Python packages are pinned in requirements.txt and installed into a virtual environment beside the program,
# so nothing here touches the system Python.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
MODE=system
DEPS=0
TEST=1
UNINSTALL=0
PREFIX=
PYTHON=
while [ $# -gt 0 ]; do
  case "$1" in
    --user) MODE=user ;;
    --deps) DEPS=1 ;;
    --no-test) TEST=0 ;;
    --uninstall) UNINSTALL=1 ;;
    --prefix) PREFIX=$2; shift ;;
    --python) PYTHON=$2; shift ;;
    *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$MODE" = user ]; then
  : "${PREFIX:=$HOME/.local/share/androidbox-app}"
  BIN=$HOME/.local/bin
  DATA=${XDG_DATA_HOME:-$HOME/.local/share}
else
  : "${PREFIX:=/usr/lib/androidbox}"
  BIN=/usr/bin
  DATA=/usr/share
  if [ "$(id -u)" != 0 ]; then
    echo "Installing for every user needs root. Use sudo, or add --user to install just for you." >&2
    exit 1
  fi
fi
APPS=$DATA/applications
ICONS=$DATA/icons/hicolor/256x256/apps
APP_ID=dev.wolklaw.Androidbox

# A Python that Qt for Python (PySide6) has packages for: 3.10 to 3.14. A newer one has none yet
find_python() {
  local candidate
  for candidate in "$PYTHON" python3.13 python3.12 python3.14 python3.11 python3.10 python3; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 14)))' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

if [ "$UNINSTALL" = 1 ]; then
  rm -rf "$PREFIX" "$BIN/androidbox" "$APPS/$APP_ID.desktop" "$ICONS/androidbox.png"
  echo "Androidbox removed. Its Android images and instances are still in ~/.local/share/Androidbox"
  exit 0
fi

if [ "$DEPS" = 1 ]; then
  if [ "$(id -u)" != 0 ]; then
    echo "--deps needs root." >&2
    exit 1
  fi
  command -v dnf >/dev/null || { echo "--deps only knows dnf. Install the libraries listed in the README by hand." >&2; exit 1; }
  missing=()
  # The rest are what Qt (the window), SDL (controllers) and Google's emulator load
  for pkg in SDL2 xcb-util-cursor libxkbcommon-x11 libxkbfile mesa-libGL mesa-libEGL \
             mesa-libgbm alsa-lib pulseaudio-libs nss libXcomposite libXcursor libXdamage libXi libXrandr libXtst; do
    rpm -q --whatprovides "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  # Fedora's python3 can be too new for Qt's packages, so it brings the 3.13 that is kept for such cases
  find_python >/dev/null || missing+=(python3.13)
  if [ ${#missing[@]} -gt 0 ]; then
    echo "--- installing: ${missing[*]}"
    dnf -y install --setopt=install_weak_deps=False "${missing[@]}"
  fi
fi

PYTHON=$(find_python) || {
  echo "Androidbox needs Python 3.10 to 3.14 (Qt for Python has no packages for a newer one). Install python3.13," >&2
  echo "or run this with --deps on Fedora, or pass --python /path/to/python." >&2
  exit 1
}
echo "--- using $PYTHON ($("$PYTHON" -c 'import sys; print(sys.version.split()[0])'))"

version=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$root/androidbox/__init__.py")
echo "--- installing Androidbox $version into $PREFIX"

# 1. the program. The old tree goes first, so files a newer version dropped don't linger
rm -rf "$PREFIX/app"
install -d "$PREFIX/app/assets"
cp -r "$root/androidbox" "$PREFIX/app/androidbox"
find "$PREFIX/app" -name __pycache__ -prune -exec rm -rf {} +
install -m 0644 "$root/Androidbox.pyw" "$PREFIX/app/Androidbox.pyw"
install -m 0644 "$root/assets/androidbox.png" "$root/assets/androidbox-icons.ttf" "$PREFIX/app/assets/"

# 2. its Python packages
# --clear: a venv left by an older install may be on a Python that has since changed
"$PYTHON" -m venv --clear "$PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install --quiet --disable-pip-version-check --no-cache-dir \
  -r "$root/requirements.txt"

# 3. the command. ANDROIDBOX_COMMAND tells the app how to start itself again, for its restart,
#    sign-in entry and desktop shortcuts
install -d "$BIN"
cat > "$BIN/androidbox" <<EOF
#!/bin/sh
export ANDROIDBOX_COMMAND="$BIN/androidbox"
exec "$PREFIX/venv/bin/python" "$PREFIX/app/Androidbox.pyw" "\$@"
EOF
chmod 0755 "$BIN/androidbox"

# 4. the menu entry and icon
install -d "$APPS" "$ICONS"
install -m 0644 "$root/assets/androidbox.png" "$ICONS/androidbox.png"
cat > "$APPS/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Androidbox
GenericName=Android emulator
Comment=Android on your PC. No ads.
Exec=$BIN/androidbox
Icon=androidbox
Terminal=false
Categories=Game;Emulator;
Keywords=android;emulator;apk;games;
StartupWMClass=Androidbox
EOF
chmod 0644 "$APPS/$APP_ID.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && [ "$MODE" = system ] && gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true

# 5. check that it starts: Qt and every module import, without opening a window
if [ "$TEST" = 1 ]; then
  test -x "$BIN/androidbox"
  test -f "$APPS/$APP_ID.desktop"
  QT_QPA_PLATFORM=offscreen "$BIN/androidbox" --version
  QT_QPA_PLATFORM=offscreen "$PREFIX/venv/bin/python" -c \
    "import sys; sys.path.insert(0, '$PREFIX/app'); import androidbox.ui.app, androidbox.ui.window"
fi

echo "Androidbox $version installed. Open it from the application menu, or run: androidbox"
if [ ! -e /dev/kvm ]; then
  echo "Note: /dev/kvm is missing. Android needs virtualization (SVM or VT-x) turned on in the BIOS." >&2
elif [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
  echo "Note: this user can't open /dev/kvm. Add yourself to the kvm group and sign in again." >&2
fi
