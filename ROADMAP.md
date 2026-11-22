# Roadmap

What is planned for Androidbox, roughly in order. Nothing here is a promise or a date.

## Done recently
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
- Separate front and back cameras when the PC has two webcams

## Next
- Check the Linux build on a real SparkOS desktop: start an instance, controllers, the tray and desktop shortcuts, the
  Graphics card setting under Wayland
- Linux: the Android 4.1 image (needs the older emulator's Linux build checked), and global shortcuts through the
  desktop's GlobalShortcuts portal
- Check macro smart steps on a running instance and tune how strict Strict, Normal and Loose are, and how fast
  the picture search is on a busy game screen
- Check every new feature on a running instance, on Android 16 and on the Android 4.1 image
- Split the main window and pages code into smaller parts before the bigger work below adds to them
- Finish code signing through the SignPath Foundation, so Windows and antivirus tools stop flagging the installer

## Bigger work

### 1. ARM games that crash
Some 64-bit ARM games (BitLife and other Unity games) crash a few seconds in, because Google's ARM translator
can't hand a memory fault in a copy routine back to the game. A fix has been prototyped: patch a copy of the
Android 16 system image so the game's own copy routines run instead. It worked on a test program, not yet on a
real game, and the code has to be rebuilt.
- Patch the image on first use, keep the patched copy, and turn it on per instance
- Cover the other routines the translator replaces, and Android 15 and 11
- Done when BitLife and two other Unity games run for 30 minutes

### 2. A shared game list
A public GitHub repository with one entry per game: which Android version to use, whether it needs the ARM fix,
a keymap, macros, an FPS cap, and whether it works, partly works or doesn't. Androidbox reads the list from
GitHub, so no new server is involved. Anyone can add a game with a pull request, and setting up a game becomes
one click.

### 3. A helper app inside Android
A small open-source app, installed only if you choose to, that makes these possible:
- Typing non-Latin text and emoji (Persian, Arabic, CJK), which Android's `input text` cannot do
- Clipboard shared both ways with Windows
- Dropping files onto the window
- Android notifications shown in Windows
- Memory use per app on the Apps page
- Faster and more reliable screen text for Claude

### 4. Several instances together
- Clone an instance
- See instances in a grid, side by side
- Send the same keys and taps to several instances at once
- Limit each instance's CPU and memory use
- Start and stop groups of instances

### 5. Scripts on top of macros
Macros stay as they are. For people who outgrow them: a script runtime with picture search, reading text off
the screen ("tap Collect"), variables and schedules, across several instances. A recorded macro can be turned
into a script to start from. Scripts play by the game's rules; nothing here hides the emulator from a game.

### 6. Testing apps from the command line and CI
- An `androidbox` command: create, start, install, run, screenshot and record, with no window
- A GitHub Action that starts an instance on a runner and runs a test script or a Claude session
- Run a test script repeatedly, with a report of screenshots and video
- More Claude tools: clipboard and permission control

### 7. macOS on Apple Silicon
On an M-series Mac the Android Emulator runs ARM apps without a translator, so the crashes in item 1 don't
happen there. Most of the platform work done for Linux carries over. It needs an arm64 build, a notarised
download and testing on a real Mac.

### 8. Play from your phone or browser
Watch and control an instance from another device on your network: the screen streamed over WebRTC, touch and
controller input sent back. Local network only unless you set it up otherwise.

## Not planned
- Bundling software we have no licence to redistribute, such as the OUYA framework. Install it from your own file
  with Install APK
- Hiding the emulator from games that refuse to run on one
