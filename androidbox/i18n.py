"""Gettext .po/.pot based internationalization for Androidbox."""

from pathlib import Path

from . import paths

LANGUAGES = [
    ("en", "English"),
    ("zh_TW", "繁體中文"),
]
DEFAULT_LANGUAGE = "en"

_current_language = DEFAULT_LANGUAGE
_catalog: dict[str, str] = {}


def _unquote(token: str) -> str:
    """Decode a quoted .po string literal."""
    s = token.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return (
        s.replace(r"\\", "\x00")
        .replace(r"\n", "\n")
        .replace(r"\t", "\t")
        .replace(r"\"", '"')
        .replace("\x00", "\\")
    )


def parse_po(text: str) -> dict[str, str]:
    """Parse GNU gettext .po file contents into a {msgid: msgstr} dict."""
    translations: dict[str, str] = {}
    msgid_parts: list[str] = []
    msgstr_parts: list[str] = []
    mode: str | None = None
    fuzzy = False

    def flush():
        nonlocal msgid_parts, msgstr_parts, mode, fuzzy
        if mode is not None:
            key = "".join(msgid_parts)
            val = "".join(msgstr_parts)
            if key and val and not fuzzy:
                translations[key] = val
        msgid_parts = []
        msgstr_parts = []
        mode = None
        fuzzy = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            continue
        if line.startswith("msgid "):
            if mode is not None:
                flush()
            mode = "id"
            msgid_parts.append(_unquote(line[6:]))
        elif line.startswith("msgstr "):
            mode = "str"
            msgstr_parts.append(_unquote(line[7:]))
        elif line.startswith('"') and mode == "id":
            msgid_parts.append(_unquote(line))
        elif line.startswith('"') and mode == "str":
            msgstr_parts.append(_unquote(line))
    flush()
    return translations


def po_path(lang: str, base_dir: Path | None = None) -> Path:
    root = base_dir if base_dir is not None else paths.LOCALES
    return root / lang / "LC_MESSAGES" / "androidbox.po"


def load_po(lang: str, base_dir: Path | None = None) -> dict[str, str]:
    if not lang or lang == DEFAULT_LANGUAGE:
        return {}
    path = po_path(lang, base_dir)
    if not path.is_file():
        return {}
    return parse_po(path.read_text(encoding="utf-8"))


def use(lang: str, base_dir: Path | None = None) -> str:
    """Activate a UI language ('en' or 'zh_TW')."""
    global _current_language, _catalog
    valid = {code for code, _ in LANGUAGES}
    chosen = lang if lang in valid else DEFAULT_LANGUAGE
    _current_language = chosen
    _catalog = load_po(chosen, base_dir)
    return chosen


def current() -> str:
    return _current_language


def t(text: str, **kwargs) -> str:
    """Translate a UI string using the active .po catalog, falling back to English."""
    translated = _catalog.get(text, text)
    if kwargs:
        try:
            return translated.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            return text.format(**kwargs)
    return translated
