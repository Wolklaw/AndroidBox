"""The effects behind the Glitch theme, taken from wolklaw.dev: a faint scanline texture, one sweep when the
window opens, and short bursts where the magenta and cyan channels slip out of register. Never a strobe: a burst
lasts about a third of a second and comes every several seconds. With Windows' animation effects switched off,
only the still colour split remains."""
import ctypes
import random

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from . import theme

BURST_FRAMES = 6
SPI_GETCLIENTAREAANIMATION = 0x1042


def animations_allowed():
    on = ctypes.c_int(1)
    try:
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(on), 0)
    except (AttributeError, OSError):
        pass
    return bool(on.value)


class SplitLabel(QLabel):
    """Text with its colour channels a hair out of register, which tears for a moment now and then."""
    shown = []

    def __init__(self, text=""):
        super().__init__(text)
        self.shift = 0
        self.slice = None
        SplitLabel.shown.append(self)
        self.destroyed.connect(lambda *_: SplitLabel.shown.remove(self) if self in SplitLabel.shown else None)

    def tear(self, shift, band):
        self.shift, self.slice = shift, band
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        rect = self.contentsRect()
        flags = int(self.alignment()) | (int(Qt.TextFlag.TextWordWrap) if self.wordWrap() else 0)
        reach = 1 + abs(self.shift)
        for color, dx in ((theme.COLORS["channel_a"], reach), (theme.COLORS["channel_b"], -reach)):
            painter.setPen(QColor(color))
            painter.setClipping(False)
            if self.slice is not None:
                painter.setClipRect(QRect(0, self.slice[0], self.width(), self.slice[1]))
            painter.drawText(rect.translated(dx, 0), flags, self.text())
        painter.setClipping(False)
        painter.setPen(QColor(theme.COLORS["bright"]))
        painter.drawText(rect, flags, self.text())


class Fault(QWidget):
    """Sits over the sidebar, header and pages (never over the Android screen) and draws the scanlines, the opening
    sweep and the occasional tear."""

    def __init__(self, parent, regions):
        super().__init__(parent)
        self.regions = regions
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.sweep = None
        self.frame = 0
        self.bands = []
        self.snapshot = None
        self.allowed = animations_allowed()
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        self.ticker = QTimer(self, interval=60, timeout=self.step)
        self.waiter = QTimer(self, singleShot=True, timeout=self.burst)
        if self.allowed:
            QTimer.singleShot(250, self.start_sweep)
            self.waiter.start(random.randint(4500, 8000))

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() in (event.Type.Resize, event.Type.Show, event.Type.LayoutRequest):
            self.setGeometry(watched.rect())
            self.raise_()
        return False

    def start_sweep(self):
        self.sweep = 0.0
        self.ticker.start()

    def burst(self):
        if self.isVisible() and self.window().isActiveWindow() and not self.ticker.isActive() or self.sweep is None \
                and self.isVisible() and not self.ticker.isActive():
            self.frame = BURST_FRAMES
            self.ticker.start()
            self.new_bands()
            tearable = [label for label in SplitLabel.shown if label.isVisible()]
            if tearable:
                label = random.choice(tearable)
                label.tear(random.randint(3, 6), (random.randint(0, max(1, label.height() - 6)), random.randint(4, 10)))
        self.waiter.start(random.randint(7000, 12000))

    def new_bands(self):
        areas = self.areas()
        self.bands = []
        if not areas:
            return
        for _ in range(random.randint(2, 3)):
            area = random.choice(areas)
            height = random.randint(6, 26)
            top = random.randint(area.top(), max(area.top(), area.bottom() - height))
            self.bands.append((QRect(area.left(), top, area.width(), height), random.choice((-1, 1)) * random.randint(6, 18)))
        self.hide()
        self.snapshot = self.parent().grab()
        self.show()

    def step(self):
        if self.sweep is not None:
            self.sweep += 0.07
            if self.sweep >= 1:
                self.sweep = None
                self.ticker.stop()
        elif self.frame > 0:
            self.frame -= 1
            if self.frame % 2 == 0:
                self.new_bands()
            if self.frame == 0:
                self.bands, self.snapshot = [], None
                for label in SplitLabel.shown:
                    label.tear(0, None)
                self.ticker.stop()
        else:
            self.ticker.stop()
        self.update()

    def areas(self):
        return [area for area in self.regions() if area.width() > 0 and area.height() > 0]

    def paintEvent(self, event):
        painter = QPainter(self)
        areas = self.areas()
        for area in areas:
            painter.save()
            painter.setClipRect(area)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 7))
            for y in range(area.top(), area.bottom(), 3):
                painter.drawRect(area.left(), y, area.width(), 1)
            if self.sweep is not None:
                top = area.top() + self.sweep * area.height()
                fade = QLinearGradient(area.left(), 0, area.right(), 0)
                a, b = QColor(theme.COLORS["channel_b"]), QColor(theme.COLORS["channel_a"])
                for color in (a, b):
                    color.setAlpha(int(200 * (1 - self.sweep)))
                fade.setColorAt(0, QColor(0, 0, 0, 0))
                fade.setColorAt(0.3, a)
                fade.setColorAt(0.7, b)
                fade.setColorAt(1, QColor(0, 0, 0, 0))
                painter.setBrush(fade)
                painter.drawRect(QRectF(area.left(), top, area.width(), 3))
            painter.restore()
        for band, dx in self.bands:
            for area in areas:
                clip = band.intersected(area)
                if clip.isEmpty():
                    continue
                painter.save()
                painter.setClipRect(clip)
                if self.snapshot is not None:
                    painter.drawPixmap(QPoint(dx, 0), self.snapshot)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                painter.fillRect(clip.translated(3, 0), QColor(255, 46, 136, 46))
                painter.fillRect(clip.translated(-3, 0), QColor(34, 216, 255, 46))
                painter.restore()
