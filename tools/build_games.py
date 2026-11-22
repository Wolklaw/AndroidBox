"""Checks every game in the games folder and writes games/index.json, the file Androidbox downloads.

    python tools/build_games.py            check the entries and rewrite the index
    python tools/build_games.py --check    only report problems and whether the index is out of date
    python tools/build_games.py --entries  only check the entries (what pull requests are checked with)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from androidbox import gamelist  # noqa: E402

FOLDER = ROOT / gamelist.FOLDER
INDEX = FOLDER / gamelist.INDEX


def entries():
    """Each game's file with what is wrong with it, if anything"""
    found = []
    for path in sorted(FOLDER.glob("*.json")):
        if path.name == gamelist.INDEX:
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            found.append((path, None, [f"Not valid JSON: {error}"]))
            continue
        wrong = gamelist.problems(entry)
        if not wrong and path.stem != entry["package"]:
            wrong = [f"The file must be named {entry['package']}.json"]
        found.append((path, entry, wrong))
    return found


def duplicates(found):
    seen = {}
    for path, entry, _ in found:
        if entry:
            seen.setdefault(entry["package"], []).append(path.name)
    return [f"{package} is in more than one file: {', '.join(names)}" for package, names in seen.items()
            if len(names) > 1]


def main(check=False, only_entries=False):
    found = entries()
    failed = [(path, wrong) for path, _, wrong in found if wrong]
    for path, wrong in failed:
        for problem in wrong:
            print(f"{path.name}: {problem}")
    for problem in duplicates(found):
        print(problem)
    if failed or duplicates(found):
        return 1
    if only_entries:
        print(f"{len(found)} games, all fine")
        return 0
    text = gamelist.build(entry for _, entry, _ in found)
    current = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
    if check:
        if current != text:
            print("games/index.json is out of date. Run: python tools/build_games.py")
            return 1
        print(f"{len(found)} games, all fine")
        return 0
    INDEX.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {INDEX.relative_to(ROOT).as_posix()} with {len(found)} games")
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:], only_entries="--entries" in sys.argv[1:]))
