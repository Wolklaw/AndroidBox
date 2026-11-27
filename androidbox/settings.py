import json

from . import native, paths, profiles, system

LOCAL = {
    "selected": None,
    # On by default where Androidbox can update itself. A Linux copy it can't replace (SparkOS's, or one run from
    # source) gets new versions from the system or git, so it doesn't nag about GitHub
    "check_updates": native.WINDOWS or system.can_update(),
    "auto_update": True,
    "skipped_version": "",
    "seen_version": "",
    "claude_access": False,
    "close_to_tray": False,
    "boss_key": "",
    "always_on_top": False,
    "compact_tools": False,
    "theme": "classic",
    "inspector": True,
    "default_storage_path": "",
    "mirrors": [],
    # The shared game list, read from GitHub once a day, and the games whose setup was already offered
    "game_list": True,
    "game_list_offered": [],
}

PROFILE = {
    "game_controls": True,
    "show_hints": True,
    "show_fps": False,
    "sync_input": False,
}


def profile_file():
    return profiles.folder() / "settings.json"


def read(path):
    values = profiles.read_json(path, {})
    return values if isinstance(values, dict) else {}


def load():
    local, shared = read(paths.SETTINGS), read(profile_file())
    return {**LOCAL, **PROFILE,
            **{key: value for key, value in local.items() if key in LOCAL},
            **{key: value for key, value in shared.items() if key in PROFILE}}


def save(values, key):
    if key in PROFILE:
        profiles.write_json(profile_file(), {name: values[name] for name in PROFILE})
    else:
        paths.write_text(paths.SETTINGS, json.dumps({name: values[name] for name in LOCAL}, indent=2))
