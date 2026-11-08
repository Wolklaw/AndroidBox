# Roadmap

What is planned for Androidbox, roughly in order. Nothing here is a promise or a date.

## Done recently
- Apps page: search, running apps first, Stop, Stop all, Force stop, Clear data, Install APK
- Claude helper: list_apps, current_app, wait_for_app, open_url, clear_app_data, push_file, pull_file, rotate,
  and type_text that quotes special characters
- Readable non-Latin screen text for Claude (UTF-8 output)
- DroidCore 1.9.x copies move back to Androidbox, and a notice after an update
- Tests, run before every release

## Next
- Check every new feature on a running instance, on Android 16 and on the Android 4.1 image
- Typing non-Latin text (Persian, Arabic, CJK, emoji) for Claude and the app. Android's `input text` cannot do it,
  so this needs the emulator's clipboard channel or a small helper app on the device
- Apps page: select several apps and act on them together, sort by last used, show each app's memory use
- Internet trouble in Android (DNS, proxy, VPN): a check in the diagnostics export

## Later
- Clone an instance, and a side-by-side view of two instances
- More Claude tools: clipboard, permission control, a way to run a test script repeatedly
- Open the Apps page in the build's start-up smoke test

## Not planned
- Bundling software we have no licence to redistribute, such as the OUYA framework. Install it from your own file
  with Install APK
- Hiding the emulator from games that refuse to run on one
