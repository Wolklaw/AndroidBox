# The game list

How well games run on Androidbox, and a setup to start from. Androidbox downloads `index.json` from here once a day
and shows it on its **Game list** page and next to each game on the **Apps** page. A game's setup (its frame rate
and controls) can be copied into your profile with **Use setup**, and Androidbox offers it the first time you open
a game you haven't set up yourself. Nothing is sent back, and the list can be turned off in Androidbox's settings.

## Let Androidbox draft entries as you play

Turn on **Draft game list entries as I play** in Androidbox's settings (it is off unless you do). Androidbox then
notes, on your PC only, how long each game you installed is in front and whether Android closes it with a crash or
an "isn't responding" dialog. Once you've played a game for about 10 minutes, and the list doesn't say how it runs on
your Android version, Androidbox offers its entry with how it runs and a note filled in from what it saw, plus your
frame rate and controls. The same drafts wait on the **Game list** page under **Played here, not on the list**.

Check the draft, then **Send on GitHub**: GitHub's page for adding a file opens with the entry in it, and committing
it there opens the pull request from your own GitHub account. Nothing is sent unless you do that.

## Add a game

1. In Androidbox, set the game up the way that works: its frame rate on the **Apps** page and its controls with
   Ctrl+Shift+E.
2. On the **Apps** page, open the game's **⋯** menu and choose **Share to the game list…**. Say how well it runs and
   anything worth knowing.
3. Choose **Send on GitHub** to open GitHub with the file filled in, and commit it there to open a pull request. Or
   choose **Save file…** and add the file to this folder in a pull request yourself; it is named after the game's
   package, such as `com.example.game.json`.

A check runs on the pull request. Once it is merged, `index.json` is rewritten by itself and Androidbox picks
the game up within a day. To check a file on your own PC first, run `python tools/build_games.py --entries`.

Not on GitHub's side of things? [Open a game report](https://github.com/Wolklaw/Androidbox/issues/new?template=game_report.yml)
instead, and attach the file or just say how the game runs.

Only add what you have checked yourself, on the Android version you name.

## What an entry holds

```json
{
 "package": "com.example.game",
 "name": "Example Game",
 "works": "yes",
 "android": "36",
 "fps": 60,
 "notes": "Turn graphics to Medium in the game's own settings.",
 "controls": [
  {"kind": "joystick", "x": 0.14, "y": 0.68, "keys": ["W", "A", "S", "D"]},
  {"kind": "tap", "x": 0.88, "y": 0.66, "key": "Space"}
 ]
}
```

| Field | Needed | What it is |
|---|---|---|
| `package` | Yes | The app's package name. The file is named after it |
| `name` | Yes | The game's name, up to 60 characters |
| `works` | Yes | `yes`, `partly` or `no` |
| `android` | No | The Android version it was checked on, as its API level: `36` (Android 16), `35` (Android 15), `30` (Android 11) or `16` (Android 4.1, for OUYA and GameStick games) |
| `fps` | No | A frame rate that suits it: 30, 60, 90, 120, 144 or 240 |
| `notes` | No | Up to 300 characters: what to change, what doesn't work |
| `controls` | No | The game's controls layout, in the same form as an exported layout. Positions are fractions of the screen, from 0 to 1. Macro controls are left out, because they play macros only you have |

## Not accepted

- Ways to get around a game's emulator detection, anti-cheat or licence check. Mark the game `no` and say it
  refuses to run on an emulator
- Links to APKs or other downloads
