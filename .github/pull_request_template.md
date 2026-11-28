<!-- Thanks for sending a change. Read CONTRIBUTING.md first: it says what gets merged and what doesn't.
     One change per pull request. Delete the parts that don't apply. -->

## What kind of change is it?

- [ ] Bug fix
- [ ] Game list entry, or a fix to one
- [ ] Fix for a Linux distribution, controller, graphics card or Windows version
- [ ] Wording, typos or docs
- [ ] Tests
- [ ] New feature or bigger change. Issue where it was agreed: #

## What it changes, and why

<!-- What does someone using Androidbox notice? For a bug fix, how did the bug happen? -->

## How I checked it

<!-- What you ran it on, and what you did to try it. -->

- System: <!-- Windows 10 / Windows 11 / SparkOS / Fedora / Ubuntu ... -->
- Android: <!-- 16 / 11 / 4.1, or "not needed" -->
- What I tried:

## Screenshots

<!-- For anything you can see in the window. Use invented data, not your own accounts. -->

## Checklist

- [ ] It does one thing, and it's based on the current `main`
- [ ] The tests pass: `QT_QPA_PLATFORM=offscreen python -m unittest discover tests`
- [ ] I ran the change myself, not just the tests
- [ ] The README is updated if users will see the change
- [ ] `VERSION` is untouched
- [ ] It's nothing on the "I won't merge" list in [CONTRIBUTING.md](https://github.com/Wolklaw/Androidbox/blob/main/CONTRIBUTING.md), and I'm
      fine with it being released under the MIT License
