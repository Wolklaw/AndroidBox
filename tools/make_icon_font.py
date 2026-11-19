"""Draws Androidbox's icons and writes them into assets/androidbox-icons.ttf.

Windows has Segoe MDL2 Assets, which the interface uses for its icons, by code point. Linux has no such font and
Microsoft's isn't ours to ship, so this makes a small font with the same code points: nothing in the interface has to
know which one it got. Needs fontTools (pip install fonttools), and only to make the font, never to run Androidbox.

Run from the repo root: python tools/make_icon_font.py [--preview preview.png]"""
import math
import sys
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "assets" / "androidbox-icons.ttf"
FAMILY = "Androidbox Icons"

# Icons are drawn on a 24 x 24 grid with y pointing down, then placed on a 1000 unit em. Every contour is made
# so that overlapping shapes add up and holes are cut where exactly one shape lies, which is all a nonzero fill needs
EM, ASCENT, DESCENT = 1000, 880, -120
SCALE = 40


def place(x, y):
    return round(x * SCALE + 20), round(380 + (12 - y) * SCALE)


# A shape is a list of contours: (points, hole)
def disc(cx, cy, r, n=48):
    return [([(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)],
             False)]


def poly(points):
    return [(list(points), False)]


def rect(x0, y0, x1, y1):
    return poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def cut(shape):
    return [(points, True) for points, _ in shape]


def ring(cx, cy, r, width):
    return disc(cx, cy, r) + cut(disc(cx, cy, r - width))


def frame(x0, y0, x1, y1, width):
    return rect(x0, y0, x1, y1) + cut(rect(x0 + width, y0 + width, x1 - width, y1 - width))


def line(p, q, width, round_caps=True):
    (x0, y0), (x1, y1) = p, q
    length = math.hypot(x1 - x0, y1 - y0)
    nx, ny = -(y1 - y0) / length * width / 2, (x1 - x0) / length * width / 2
    shape = poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])
    if round_caps:
        shape += disc(x0, y0, width / 2, 16) + disc(x1, y1, width / 2, 16)
    return shape


def polyline(points, width):
    shape = []
    for a, b in zip(points, points[1:]):
        shape += line(a, b, width)
    return shape


def arc(cx, cy, r, start, end, width, steps=40):
    """A stroked arc, angles in degrees, growing clockwise on screen"""
    outer, inner = [], []
    for i in range(steps + 1):
        angle = math.radians(start + (end - start) * i / steps)
        outer.append((cx + (r + width / 2) * math.cos(angle), cy + (r + width / 2) * math.sin(angle)))
        inner.append((cx + (r - width / 2) * math.cos(angle), cy + (r - width / 2) * math.sin(angle)))
    shape = poly(outer + inner[::-1])
    for angle in (start, end):
        a = math.radians(angle)
        shape += disc(cx + r * math.cos(a), cy + r * math.sin(a), width / 2, 16)
    return shape


def head(cx, cy, r, angle, size=3.6):
    """An arrow head for the end of an arc, pointing the way the arc is going"""
    a = math.radians(angle)
    point = (cx + r * math.cos(a), cy + r * math.sin(a))
    tx, ty = -math.sin(a), math.cos(a)
    nx, ny = -ty, tx
    return poly([(point[0] + tx * size, point[1] + ty * size), (point[0] + nx * size, point[1] + ny * size),
                 (point[0] - nx * size, point[1] - ny * size)])


def turned(shape_points, cx, cy, angle):
    a = math.radians(angle)
    return [(cx + (x - cx) * math.cos(a) - (y - cy) * math.sin(a), cy + (x - cx) * math.sin(a) + (y - cy) * math.cos(a))
            for x, y in shape_points]


def curve(a, control, b, steps=20):
    return [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * control[0] + t * t * b[0],
             (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * control[1] + t * t * b[1])
            for t in (i / steps for i in range(steps + 1))]


SPEAKER = poly([(2.5, 9), (6.5, 9), (11, 4.5), (11, 19.5), (6.5, 15), (2.5, 15)])


def gear():
    shape = disc(12, 12, 7)
    for i in range(8):
        shape += poly(turned([(10.4, 2.8), (13.6, 2.8), (13.6, 7), (10.4, 7)], 12, 12, i * 45))
    return shape + cut(disc(12, 12, 3.2))


def leaf():
    a, b = (4.5, 19.5), (19.5, 4.5)
    outline = curve(a, (3.5, 4.5), b)[:-1] + curve(b, (19.5, 20.5), a)[:-1]
    return poly(outline) + cut(poly([(5.6, 19.4), (6.4, 20.2), (13.2, 12.6), (12.4, 11.8)]))


def sector(cx, cy, r, start, end, steps=30):
    return poly([(cx + r * math.cos(math.radians(start + (end - start) * i / steps)),
                  cy + r * math.sin(math.radians(start + (end - start) * i / steps))) for i in range(steps + 1)])


GLYPHS = {
    0xE72B: ("back", polyline([(20, 12), (5, 12)], 2) + polyline([(11, 6), (5, 12), (11, 18)], 2)),
    0xE80F: ("home", poly([(12, 2.5), (22, 12), (19, 12), (19, 21.5), (5, 21.5), (5, 12), (2, 12)])
            + cut(rect(10, 14, 14, 21.5))),
    0xE7C4: ("recents", frame(4, 4, 20, 20, 2)),
    0xE995: ("volume_up", SPEAKER + arc(11, 12, 5.5, -50, 50, 1.8) + arc(11, 12, 9.5, -50, 50, 1.8)),
    0xE993: ("volume_down", SPEAKER + arc(11, 12, 6, -50, 50, 1.8)),
    0xE74F: ("mute", SPEAKER + line((14, 9), (20, 15), 1.8) + line((20, 9), (14, 15), 1.8)),
    0xE7AD: ("rotate", arc(12, 12, 7.5, 20, 320, 2) + head(12, 12, 7.5, 320)),
    0xE722: ("camera", rect(3, 8, 21, 20) + poly([(8, 8), (9.5, 5), (14.5, 5), (16, 8)]) + cut(disc(12, 14, 4))),
    0xE7C8: ("record", ring(12, 12, 9.5, 2) + disc(12, 12, 5)),
    0xE71A: ("stop", rect(5.5, 5.5, 18.5, 18.5)),
    0xE740: ("fullscreen", polyline([(4, 9), (4, 4), (9, 4)], 2) + polyline([(15, 4), (20, 4), (20, 9)], 2)
            + polyline([(4, 15), (4, 20), (9, 20)], 2) + polyline([(15, 20), (20, 20), (20, 15)], 2)),
    0xE765: ("keyboard", frame(2, 6, 22, 18, 1.8) + rect(5, 9, 7, 10.8) + rect(9, 9, 11, 10.8) + rect(13, 9, 15, 10.8)
            + rect(17, 9, 19, 10.8) + rect(5, 11.8, 7, 13.6) + rect(9, 11.8, 11, 13.6) + rect(13, 11.8, 15, 13.6)
            + rect(17, 11.8, 19, 13.6) + rect(8, 14.4, 16, 15.8)),
    0xE7FC: ("game", poly([(6, 8), (18, 8), (22, 13), (21, 18.5), (17.5, 18.5), (15, 15.5), (9, 15.5), (6.5, 18.5),
                           (3, 18.5), (2, 13)])
            + cut(rect(5, 11.8, 9, 13.2)) + cut(rect(6.3, 10.5, 7.7, 14.5)) + cut(disc(16, 11.6, 1.1, 16))
            + cut(disc(18.6, 13.8, 1.1, 16))),
    0xE707: ("location", disc(12, 9.5, 6.5) + poly([(6.4, 12.5), (17.6, 12.5), (12, 22.5)]) + cut(disc(12, 9.5, 2.5))),
    0xE896: ("install", polyline([(12, 3), (12, 15)], 2) + polyline([(6.5, 10.5), (12, 16), (17.5, 10.5)], 2)
            + polyline([(4, 20.5), (20, 20.5)], 2)),
    0xE8B7: ("folder", poly([(2, 5), (9, 5), (11.5, 7.5), (22, 7.5), (22, 19.5), (2, 19.5)])),
    0xE713: ("settings", gear()),
    0xE7E8: ("power", arc(12, 13, 8, -50, 230, 2) + line((12, 3), (12, 12), 2)),
    0xE710: ("add", line((12, 4), (12, 20), 2.2) + line((4, 12), (20, 12), 2.2)),
    0xE945: ("macro", ring(12, 12, 9.5, 2) + poly([(10, 8), (16, 12), (10, 16)])),
    0xE8B1: ("shake", frame(8, 3.5, 16, 20.5, 1.8) + line((4, 8), (4, 16), 1.8) + line((20, 8), (20, 16), 1.8)),
    0xEC0A: ("eco", leaf()),
    0xF0E2: ("apps", rect(3.5, 3.5, 10.5, 10.5) + rect(13.5, 3.5, 20.5, 10.5) + rect(3.5, 13.5, 10.5, 20.5)
            + rect(13.5, 13.5, 20.5, 20.5)),
    0xE7F4: ("screen", frame(2.5, 4, 21.5, 17, 1.8) + line((12, 17), (12, 20), 2) + line((7, 20.5), (17, 20.5), 2)),
    0xE946: ("info", ring(12, 12, 9.5, 2) + disc(12, 7.6, 1.4) + rect(11, 10.5, 13, 17.2)),
    0xE8AB: ("sync", arc(12, 12, 7.5, -160, -20, 2) + head(12, 12, 7.5, -20) + arc(12, 12, 7.5, 20, 160, 2)
            + head(12, 12, 7.5, 160)),
    0xE712: ("more", disc(5, 12, 1.9, 24) + disc(12, 12, 1.9, 24) + disc(19, 12, 1.9, 24)),
    0xE8A7: ("popout", polyline([(10, 5), (4, 5), (4, 20), (19, 20), (19, 14)], 2) + polyline([(11, 13), (20.5, 3.5)], 2)
            + polyline([(14.5, 3.5), (20.5, 3.5), (20.5, 9.5)], 2)),
    0xE77B: ("person", disc(12, 7.5, 4.2) + sector(12, 21, 8.5, 180, 360)),
    0xE70D: ("chevron", polyline([(6, 9), (12, 15), (18, 9)], 2.2)),
    0xE718: ("pin", line((7, 4), (17, 4), 2) + poly([(9, 4), (9, 10.5), (6, 15), (18, 15), (15, 10.5), (15, 4)])
            + line((12, 15), (12, 21.5), 1.8)),
    0xE8F1: ("library", rect(3.5, 4, 8, 20) + rect(9.5, 4, 14, 20) + poly([(15.5, 5), (19.5, 4), (21.5, 19), (17.5, 20)])),
}


def signed_area(points):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1])) / 2


def draw(shape):
    pen = TTGlyphPen(None)
    for points, hole in shape:
        placed = [place(*point) for point in points]
        # TrueType fills clockwise contours (in its y-up space) and cuts counter-clockwise ones
        if (signed_area(placed) < 0) == hole:
            placed.reverse()
        pen.moveTo(placed[0])
        for point in placed[1:]:
            pen.lineTo(point)
        pen.closePath()
    return pen.glyph()


def build():
    order = [".notdef"] + [f"uni{code:04X}" for code in GLYPHS]
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    for code, (_, shape) in GLYPHS.items():
        glyphs[f"uni{code:04X}"] = draw(shape)
    font = FontBuilder(EM, isTTF=True)
    font.setupGlyphOrder(order)
    font.setupCharacterMap({code: f"uni{code:04X}" for code in GLYPHS})
    font.setupGlyf(glyphs)
    table = font.font["glyf"]
    font.setupHorizontalMetrics({name: (EM, getattr(table[name], "xMin", 0) if table[name].numberOfContours else 0)
                                 for name in order})
    font.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    font.setupNameTable({"familyName": FAMILY, "styleName": "Regular"})
    font.setupOS2(sTypoAscender=ASCENT, sTypoDescender=DESCENT, usWinAscent=ASCENT, usWinDescent=-DESCENT,
                  achVendID="WLKL")
    font.setupPost()
    OUTPUT.parent.mkdir(exist_ok=True)
    font.save(str(OUTPUT))
    return OUTPUT


def preview(target):
    """A sheet of every icon at 16, 32 and 64 pixels, drawn by Qt from the finished font"""
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    assert QFontDatabase.addApplicationFont(str(OUTPUT)) >= 0, "Qt could not load the font"
    cell = 84
    columns = 8
    rows = -(-len(GLYPHS) // columns)
    image = QImage(columns * cell, rows * cell, QImage.Format.Format_ARGB32)
    image.fill(QColor("#1b1b24"))
    painter = QPainter(image)
    painter.setPen(QColor("#e8e8f0"))
    for index, code in enumerate(GLYPHS):
        x, y = index % columns * cell, index // columns * cell
        for size, offset in ((16, 4), (32, 26), (-1, 0)):
            if size > 0:
                font = QFont(FAMILY)
                font.setPixelSize(size)
                painter.setFont(font)
                painter.drawText(x + offset, y + 4, 40, 40, 0x84, chr(code))
        font = QFont(FAMILY)
        font.setPixelSize(24)
        painter.setFont(font)
        painter.drawText(x + 4, y + 50, cell - 8, 30, 0x81, f"{GLYPHS[code][0]}")
    painter.end()
    image.save(str(target))
    del app


if __name__ == "__main__":
    print("wrote", build())
    if "--preview" in sys.argv:
        preview(sys.argv[sys.argv.index("--preview") + 1])
