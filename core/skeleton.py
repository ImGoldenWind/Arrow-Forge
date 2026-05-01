from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QWidget
from PyQt6.QtCore import QTimer
from core.themes import P


# Shared animation clock
# All SkeletonBars share one timer and animate in perfect sync.

_STEP = 0
_COLORS: list[str] = []
_SUBSCRIBERS: list = []
_TIMER: QTimer | None = None
_TOTAL_STEPS = 20   # steps per half-cycle (dark -> light)
_INTERVAL_MS = 40   # ms per step  ->  full cycle ~ 1.6 s


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    return "#{:02x}{:02x}{:02x}".format(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


def reset_palette():
    """Call this whenever the theme changes so colors are rebuilt on next use."""
    global _COLORS
    _COLORS = []


def _build_palette():
    global _COLORS
    if _COLORS:
        return
    dark, light = P["bg_card"], P["mid"]
    fwd = [_lerp_hex(dark, light, i / (_TOTAL_STEPS - 1)) for i in range(_TOTAL_STEPS)]
    # ping-pong: forward then reverse, no duplicate endpoints
    _COLORS = fwd + list(reversed(fwd[1:-1]))


def _tick():
    global _STEP
    _STEP = (_STEP + 1) % len(_COLORS)
    color = _COLORS[_STEP]
    alive = []
    for bar in _SUBSCRIBERS:
        try:
            if bar.isVisible():
                bar.setStyleSheet(f"background-color: {color}; border-radius: {bar._corner_radius}px;")
                alive.append(bar)
        except (RuntimeError, AttributeError):
            pass
    _SUBSCRIBERS[:] = alive
    if not alive:
        global _TIMER
        if _TIMER:
            _TIMER.stop()
            _TIMER = None


def _subscribe(bar):
    global _TIMER
    _build_palette()
    _SUBSCRIBERS.append(bar)
    if _TIMER is None:
        _TIMER = QTimer()
        _TIMER.timeout.connect(_tick)
        _TIMER.start(_INTERVAL_MS)


# Widgets

class SkeletonBar(QFrame):
    """Smoothly pulsing placeholder bar (shares one global timer)."""

    def __init__(self, parent=None, height=14, corner_radius=6, width=0):
        super().__init__(parent)
        self._corner_radius = corner_radius
        self.setFixedHeight(height)
        if width > 0:
            self.setFixedWidth(width)
        self.setStyleSheet(f"background-color: {P['bg_card']}; border-radius: {corner_radius}px;")
        _subscribe(self)


class SkeletonCard(QFrame):
    """Skeleton placeholder shaped like a ToolCard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"SkeletonCard {{ background-color: {P['bg_card']}; border-radius: 8px; "
            f"border: 1px solid {P['border']}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        row = QHBoxLayout()
        layout.addLayout(row)

        icon_skel = SkeletonBar(self, height=32, corner_radius=6, width=32)
        row.addWidget(icon_skel)

        texts = QVBoxLayout()
        texts.setSpacing(5)
        row.addLayout(texts, 1)

        texts.addWidget(SkeletonBar(self, height=14, corner_radius=4))
        texts.addWidget(SkeletonBar(self, height=11, corner_radius=3))


class SkeletonListRow(QFrame):
    """Skeleton placeholder shaped like a character list button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setStyleSheet("background-color: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(0)

        inner = QFrame(self)
        inner.setStyleSheet(
            f"background-color: {P['bg_card']}; border-radius: 6px;"
        )
        layout.addWidget(inner)

        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(10, 6, 10, 5)
        inner_layout.setSpacing(3)
        inner_layout.addWidget(SkeletonBar(inner, height=13, corner_radius=3))
        inner_layout.addWidget(SkeletonBar(inner, height=10, corner_radius=3))
