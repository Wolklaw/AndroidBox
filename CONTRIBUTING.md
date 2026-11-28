# Contributing to Androidbox

Androidbox is my project: I decide where it goes, what's on the [roadmap](ROADMAP.md) and what gets merged. Anyone
can offer changes, though, and pull requests are welcome. Fixes, game list entries, translations and roadmap items
have all come in from people who use it.

## What I accept, what to ask about first, and what I won't take

**Send a pull request straight away for:**

- Bug fixes, with a line on how to make the bug happen
- Game list entries and fixes to existing ones. See [Game list](README.md#game-list) in the README; **Send on
  GitHub** in the app fills the file in for you
- Fixes for a Linux distribution, a controller, a graphics card or a Windows version that doesn't work
- Better wording, typos and README fixes
- Tests for code that has none

**Open an [issue](https://github.com/Wolklaw/Androidbox/issues/new/choose) first, or comment on the one that
exists, for:**

- New features, including the ones on the [roadmap](ROADMAP.md). Say which part you're taking, so two people don't
  build the same thing
- Translations. The way they plug into the app isn't settled yet
- New pages, settings, sidebar entries, or changes to how the window is laid out
- New dependencies, or a new download from somewhere other than Google, GitHub or Mozilla
- New Claude helper tools
- Anything that changes the installer, `install.sh`, the build or the update check

That way you'll know whether it fits before you put the work in.

**I won't merge:**

- Anything that hides the emulator from apps or games, fakes a device's identity or location for them, hides
  root, or gets around an app's or game's checks
- Cheats, memory editing, or bots that break an online game's rules. Macros and scripts play the game the
  way a person could
- Ads, telemetry, crash reports sent without asking, accounts, or anything else that sends data off the PC
  unless the user turns it on
- Downloads that aren't checked against a fixed checksum, or code that fetches and runs something new at runtime
- Bundled software we have no licence to redistribute, such as Google's apps or the OUYA framework, and links to
  pirated apps
- Code copied from a project whose licence doesn't allow it in an MIT project, or binaries without their source
- Changes to the release, signing or update workflows from outside the project. Report a problem there in an issue
- Large rewrites, reformatting, or a new look for the whole app that nobody asked for
- Code you haven't run

## Making a pull request easy to merge

Fill in the template GitHub shows when you open a pull request. A pull request is easiest to merge when it:

- **does one thing.** A fix, a feature and a translation should be three pull requests. One that mixes several gets
  sent back to be split, because a single part I can't take holds up all the others.
- **is based on the current `main`.** Rebase before you open it, and again if `main` moves a lot.
- **passes the tests.** Add tests for what you change where it can be tested without a running Android
  (see `tests/`). Run them with:
  ```
  QT_QPA_PLATFORM=offscreen python -m unittest discover tests
  ```
- **works on Windows and Linux,** or says plainly which one you tested on. Code that differs between the two
  belongs in `androidbox/native.py`.
- **matches the code around it** in style and naming, with no new dependency unless it's needed. If you add one,
  pin its version in `requirements.txt`.
- **keeps the wording plain.** Labels and messages use short, plain verbs and say exactly what happens. If you
  change something users see, update the README too.
- **leaves the version alone.** I raise `VERSION` when I make a release.

Changes to the Claude helper go in `androidbox/claude.py`. Then run `python tools/build_plugin.py` so the plugin
copy in `plugin/` matches.

## How review works

I read every pull request, but there's no fixed turnaround. I might:

- **merge it as it is,**
- **ask for changes,** or
- **take the idea and write it differently.** When that happens I say so in the pull request, and the
  commit or release notes credit you.

A pull request that's closed without merging isn't a judgment on you. It usually means the change doesn't fit
where Androidbox is going, or it overlaps with something already planned.

AI-assisted pull requests are fine, as long as you've run the change yourself and can answer questions about it.

## Licence

Androidbox is under the [MIT License](LICENSE). By sending a pull request you agree that your contribution is
released under that licence too. There's no contributor agreement to sign. Your name stays on your commits, and
releases mention who contributed.

## Security problems

Don't open a public issue for those. Use GitHub's
[private vulnerability reporting](https://github.com/Wolklaw/Androidbox/security/advisories/new) instead.
