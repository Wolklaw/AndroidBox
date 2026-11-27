# Roadmap

What is planned for Androidbox, roughly in order. Nothing here is a promise or a date.

## Done recently
- Linux: the Android 4.1 image for OUYA and GameStick games, on the Linux build of the older emulator
- Game list: a shared list on GitHub of how well games run, with a frame rate and controls to start from. Browse
  it from the sidebar, see it on the Apps page, get a game's setup offered the first time you open it, and share
  your own setup as a file for a pull request or a game report
- Internet trouble in Android: the diagnostics export checks the proxy step by step, the PC's own connection,
  and DNS and VPN inside Android
- Macro smart steps: wait until a marked part of the screen looks the same or until the screen stops changing,
  If ... End if, Repeat ... until, and tapping a marked picture wherever it shows up, each with a limit and
  editable settings
- Apps page: search, running apps first, Stop, Stop all, Force stop, Clear data, Install APK
- Claude helper: list_apps, current_app, wait_for_app, open_url, clear_app_data, push_file, pull_file, rotate,
  and type_text that quotes special characters
- Readable non-Latin screen text for Claude (UTF-8 output)
- Linux build for SparkOS, checked by tests and a headless start in CI
- Linux: global shortcuts and the boss key (GlobalShortcuts portal, X11 key grabs, or the keyboards for the input
  group), self-update for copies installed with install.sh, and eco mode that can be turned off again
- Separate front and back cameras when the PC has two webcams

## Next
- Check the Linux build on a real SparkOS desktop: start an instance, controllers, the tray and desktop shortcuts, the
  Graphics card setting under Wayland
- Linux: check global shortcuts through the GlobalShortcuts portal on KDE Plasma and GNOME, and a self-update from
  one published release to the next
- Check macro smart steps on a running instance and tune how strict Strict, Normal and Loose are, and how fast
  the picture search is on a busy game screen
- Check every new feature on a running instance, on Android 16 and on the Android 4.1 image
- Split the main window and pages code into smaller parts before the bigger work below adds to them
- Finish code signing through the SignPath Foundation, so Windows and antivirus tools stop flagging the installer

## Bigger work

### 1. More on the game list
- Check the list's frame rates and controls on a running instance with real games, and grow the list past the
  first entries
- Macros in an entry, for games where a recorded routine is the setup that matters. They only play on the display
  they were recorded on, so an entry needs to say which one
- Let a game's entry suggest the instance settings it needs, such as Android 11 for 32-bit-only games

### 2. A helper app inside Android
A small open-source app, installed only if you choose to, that makes these possible:
- Typing non-Latin text and emoji (Persian, Arabic, CJK), which Android's `input text` cannot do
- Clipboard shared both ways with Windows
- Dropping files onto the window
- Android notifications shown in Windows
- Memory use per app on the Apps page
- Faster and more reliable screen text for Claude

### 3. Several instances together
- Clone an instance
- See instances in a grid, side by side
- Send the same keys and taps to several instances at once
- Limit each instance's CPU and memory use
- Start and stop groups of instances

### 4. Scripts on top of macros
Macros stay as they are. For people who outgrow them: a script runtime with picture search, reading text off
the screen ("tap Collect"), variables and schedules, across several instances. A recorded macro can be turned
into a script to start from. Scripts play by the game's rules; nothing here hides the emulator from a game.

### 5. Testing apps from the command line and CI
- An `androidbox` command: create, start, install, run, screenshot and record, with no window
- A GitHub Action that starts an instance on a runner and runs a test script or a Claude session
- Run a test script repeatedly, with a report of screenshots and video
- More Claude tools: clipboard and permission control

### 6. macOS on Apple Silicon
On an M-series Mac the Android Emulator runs ARM apps natively instead of through a translator, so ARM-only
games run faster. Most of the platform work done for Linux carries over. It needs an arm64 build, a notarised
download and testing on a real Mac.

### 7. Play from your phone or browser
Watch and control an instance from another device on your network: the screen streamed over WebRTC, touch and
controller input sent back. Local network only unless you set it up otherwise.

## Not planned
- Bundling software we have no licence to redistribute, such as the OUYA framework. Install it from your own file
  with Install APK
- Hiding the emulator from games that refuse to run on one
