from PySide6.QtGui import QFontDatabase

from .. import native, paths

CLASSIC = {
    "sidebar": "#10131a",
    "main": "#151921",
    "surface": "#1c212b",
    "raised": "#262c38",
    "hover": "#212733",
    "selected": "#2a3142",
    "input": "#0d1016",
    "line": "#252b38",
    "text": "#e6e9f0",
    "bright": "#fafbfe",
    "muted": "#a7aebd",
    "faint": "#7f8799",
    "dim": "#596073",
    "accent": "#3ddc84",
    "accent_hover": "#5ae497",
    "on_accent": "#0a1f12",
    "green": "#3ddc84",
    "red": "#f2766f",
    "danger": "#d9534c",
    "danger_hover": "#bf433d",
    "yellow": "#e8b64c",
}

# The wolklaw.dev look: deep indigo, mint, and two colour channels (magenta and cyan) that slip out of register
GLITCH = {
    "sidebar": "#0d0c20",
    "main": "#0a0919",
    "surface": "#141233",
    "raised": "#1b1948",
    "hover": "#17153c",
    "selected": "#252262",
    "input": "#07061a",
    "line": "#2a2760",
    "text": "#f1efff",
    "bright": "#ffffff",
    "muted": "#b3b0d2",
    "faint": "#8a86b4",
    "dim": "#5b5788",
    "accent": "#9be8b8",
    "accent_hover": "#b8f2cf",
    "on_accent": "#0a0919",
    "green": "#9be8b8",
    "red": "#ff2e88",
    "danger": "#ff2e88",
    "danger_hover": "#e02677",
    "yellow": "#f4c95d",
    "channel_a": "#ff2e88",
    "channel_b": "#22d8ff",
    "raised_hover": "#2a2766",
}

THEMES = {"classic": CLASSIC, "glitch": GLITCH}
NAMES = [("Classic", "classic"), ("Glitch (wolklaw.dev)", "glitch")]
CONFETTI = {"classic": ["#3ddc84", "#e8b64c", "#f2766f", "#6ea8fe", "#c792ea", "#5ae497", "#f5f6f7"],
            "glitch": ["#9be8b8", "#f4c95d", "#ff2e88", "#22d8ff", "#b9a6ff", "#ff9ebb", "#f1efff"]}

# Every module shares this one dictionary, so choosing a theme changes it in place before the windows are built
COLORS = {}
CURRENT = "classic"


def use(name):
    global CURRENT
    CURRENT = name if name in THEMES else "classic"
    COLORS.clear()
    COLORS.update({"channel_a": CLASSIC["red"], "channel_b": CLASSIC["accent"], "raised_hover": "#323a4b"})
    COLORS.update(THEMES[CURRENT])


def glitched():
    return CURRENT == "glitch"


use("classic")


ICONS = {
    "back": "",
    "home": "",
    "recents": "",
    "volume_up": "",
    "volume_down": "",
    "rotate": "",
    "camera": "",
    "record": "",
    "stop": "",
    "fullscreen": "",
    "keyboard": "",
    "game": "",
    "location": "",
    "install": "",
    "folder": "",
    "settings": "",
    "power": "",
    "add": "",
    "macro": "",
    "shake": "",
    "eco": "",
    "apps": "",
    "screen": "",
    "info": "",
    "sync": "",
    "more": "",
    "popout": "",
    "person": "",
    "chevron": "",
    "mute": "",
    "pin": "",
    "download": "",
    "library": "",
}


class Fonts:
    text = "Segoe UI"
    strong = "Segoe UI Semibold"
    icons = "Segoe MDL2 Assets"
    # Added to every heading style: a family that is already semibold needs nothing, one that isn't gets the weight
    strong_weight = ""

    @classmethod
    def load(cls):
        if not native.WINDOWS:
            cls.load_linux()
            return
        available = set(QFontDatabase.families())

        def pick(*names):
            return next((name for name in names if name in available), names[-1])

        cls.text = pick("Inter", "Segoe UI Variable Text", "Segoe UI") if glitched() else             pick("Segoe UI Variable Text", "Segoe UI")
        cls.strong = pick("Chakra Petch SemiBold", "Chakra Petch", "Bahnschrift SemiBold", "Bahnschrift",
                          "Segoe UI Semibold", "Segoe UI") if glitched() else pick("Segoe UI Semibold", "Segoe UI")
        cls.icons = pick("Segoe Fluent Icons", "Segoe MDL2 Assets")

    @classmethod
    def load_linux(cls):
        # Segoe isn't there. The icons come from the font Androidbox ships (tools/make_icon_font.py), and the text
        # from the first of the usual desktop fonts that is installed, else whatever the desktop itself uses
        for file in (paths.BUNDLE / "assets").glob("androidbox-icons.ttf"):
            if QFontDatabase.addApplicationFont(str(file)) >= 0:
                cls.icons = "Androidbox Icons"
        available = set(QFontDatabase.families())
        system = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
        names = ("Inter", "Noto Sans", "Cantarell", "Open Sans", "DejaVu Sans")
        cls.text = next((name for name in names if name in available), system)
        heading = next((name for name in ("Chakra Petch SemiBold", "Chakra Petch") if name in available), None)             if glitched() else None
        cls.strong = heading or cls.text
        cls.strong_weight = "" if heading == "Chakra Petch SemiBold" else "font-weight: 600;"


def stylesheet():
    c = COLORS
    sharp = glitched()
    big, mid, small, pill = ("3px", "3px", "2px", "3px") if sharp else ("16px", "10px", "8px", "14px")
    tag = "3px" if sharp else "12px"
    handle, item = ("2px", "2px") if sharp else ("4px", "6px")
    dock, dialog, menu = ("3px", "3px", "3px") if sharp else ("20px", "18px", "12px")
    split = f"""
    QPushButton:hover {{
        border-left: 3px solid {c["channel_a"]};
        border-right: 3px solid {c["channel_b"]};
        padding: 0 15px;
    }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
        border: 1px solid {c["channel_b"]};
        border-left: 3px solid {c["channel_a"]};
    }}
    #Card {{
        border: 1px solid {c["line"]};
        border-left: 2px solid {c["channel_a"]};
        border-right: 2px solid {c["channel_b"]};
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c["channel_b"]};
    }}
    QToolTip {{
        border-left: 3px solid {c["channel_a"]};
        border-right: 3px solid {c["channel_b"]};
    }}
    QPushButton[kind="link"]:hover, QPushButton[kind="chip"]:hover {{
        border-left: none;
        border-right: none;
    }}
    """ if sharp else ""
    return f"""
    QWidget {{
        color: {c["text"]};
        font-family: "{Fonts.text}";
        font-size: 10pt;
    }}
    QMainWindow, #Main, #Page, QStackedWidget {{
        background: {c["main"]};
    }}
    #Sidebar, #Tools, #Inspector {{
        background: {c["sidebar"]};
    }}
    #Inspector {{
        border-left: 1px solid {c["line"]};
    }}
    #Header {{
        border-bottom: 1px solid {c["line"]};
    }}
    #Dock {{
        background: {c["raised"]};
        border: 1px solid {c["line"]};
        border-radius: {dock};
    }}
    #Chip {{
        background: {c["surface"]};
        color: {c["muted"]};
        border-radius: {tag};
        padding: 4px 10px;
        font-size: 9pt;
    }}
    #HeaderTitle {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}"; {Fonts.strong_weight}
        font-size: 14pt;
    }}
    #Brand {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}"; {Fonts.strong_weight}
        font-size: 12pt;
    }}
    #Title {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}"; {Fonts.strong_weight}
        font-size: 11pt;
    }}
    #Heading {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}"; {Fonts.strong_weight}
        font-size: 18pt;
    }}
    #Subheading {{
        color: {c["bright"]};
        font-family: "{Fonts.strong}"; {Fonts.strong_weight}
        font-size: 10.5pt;
    }}
    #Section {{
        color: {c["faint"]};
        font-family: "{Fonts.strong}"; {Fonts.strong_weight}
        font-size: 9pt;
    }}
    #Muted {{
        color: {c["muted"]};
    }}
    #Small {{
        color: {c["faint"]};
        font-size: 9pt;
    }}
    #Card {{
        background: {c["surface"]};
        border-radius: {big};
    }}
    #Divider {{
        background: {c["line"]};
        max-height: 1px;
        min-height: 1px;
    }}
    QPushButton {{
        border: none;
        border-radius: {mid};
        padding: 0 18px;
        min-height: 36px;
        font-family: "{Fonts.strong}"; {Fonts.strong_weight}
        font-size: 10pt;
        color: {c["on_accent"]};
        background: {c["accent"]};
    }}
    QPushButton:hover {{
        background: {c["accent_hover"]};
    }}
    QPushButton:disabled {{
        background: {c["raised"]};
        color: {c["dim"]};
    }}
    QPushButton[kind="secondary"] {{
        background: {c["raised"]};
        color: {c["text"]};
    }}
    QPushButton[kind="secondary"]:hover {{
        background: {c["raised_hover"]};
    }}
    QPushButton[kind="danger"] {{
        background: {c["danger"]};
        color: #ffffff;
    }}
    QPushButton[kind="danger"]:hover {{
        background: {c["danger_hover"]};
    }}
    QPushButton[kind="link"] {{
        background: transparent;
        color: {c["accent"]};
        font-family: "{Fonts.text}";
        padding: 0 8px;
    }}
    QPushButton[kind="link"]:hover {{
        text-decoration: underline;
    }}
    QPushButton[kind="chip"] {{
        background: {c["surface"]};
        color: {c["muted"]};
        border-radius: {pill};
        min-height: 28px;
        padding: 0 12px;
    }}
    QPushButton[kind="chip"]:hover {{
        background: {c["raised"]};
        color: {c["bright"]};
    }}
    QPushButton[size="large"] {{
        min-height: 40px;
        padding: 0 24px;
    }}
    QLineEdit, QComboBox, QAbstractSpinBox {{
        background: {c["input"]};
        border: 1px solid {c["line"]};
        border-radius: {mid};
        padding: 0 12px;
        min-height: 36px;
        color: {c["text"]};
        selection-background-color: {c["accent"]};
        selection-color: {c["on_accent"]};
    }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
        border: 1px solid {c["accent"]};
    }}
    QListWidget {{
        background: {c["input"]};
        border: 1px solid {c["line"]};
        border-radius: {small};
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 7px 10px;
        border-radius: {item};
    }}
    QListWidget::item:hover {{
        background: {c["hover"]};
    }}
    QListWidget::item:selected {{
        background: {c["selected"]};
        color: {c["bright"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox::down-arrow {{
        image: none;
        width: 0;
    }}
    QComboBox QAbstractItemView {{
        background: {c["surface"]};
        border: 1px solid {c["line"]};
        padding: 4px;
        outline: none;
        selection-background-color: {c["selected"]};
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c["raised"]};
        border-radius: {handle};
        min-height: 32px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0;
        background: transparent;
    }}
    QToolTip {{
        background: {c["raised"]};
        color: {c["bright"]};
        border: 1px solid {c["line"]};
        padding: 5px 8px;
        font-size: 9pt;
    }}
    QMenu {{
        background: {c["surface"]};
        border: 1px solid {c["line"]};
        border-radius: {menu};
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 16px;
        border-radius: {small};
        color: {c["text"]};
    }}
    QMenu::item:selected {{
        background: {c["selected"]};
        color: {c["bright"]};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c["line"]};
        margin: 4px 6px;
    }}
    #Toast {{
        background: {c["raised"]};
        color: {c["bright"]};
        border-radius: {small};
        padding: 10px 16px;
    }}
    #Dialog {{
        background: {c["surface"]};
        border: 1px solid {c["line"]};
        border-radius: {dialog};
    }}
    """ + split
