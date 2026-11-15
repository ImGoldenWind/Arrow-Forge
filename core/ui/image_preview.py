"""Read-only image inspection: native pixels, fit, anchored zoom and panning."""
from PyQt6.QtCore import Qt, QObject, QRunnable, pyqtSignal, QPoint
from PyQt6.QtGui import QImage, QPainter, QPixmap, QColor, QBrush
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget, QVBoxLayout, QHBoxLayout, QPushButton

from core.design_tokens import LayoutRole, Size
from core.style_helpers import ss_bg_dark
from core.translations import ui_text
from core.ui.editor_widgets import configure_button, configure_layout
from core.themes import P


class ImageLoadSignals(QObject):
    finished = pyqtSignal(int, str, object, object, str)


class ImageLoadJob(QRunnable):
    """Decode a named resource off-thread; the owner rejects stale tokens."""
    def __init__(self, signals, token, kind, root, path, name, language, *, loader):
        super().__init__()
        self.signals, self.token, self.kind = signals, token, kind
        self.root, self.path, self.name, self.language = root, path, name, language
        self.loader = loader

    def run(self):
        try:
            image, names, error = self.loader(self.root, self.path, self.name, self.language)
        except Exception as exc:
            image, names, error = None, (), str(exc)
        self.signals.finished.emit(self.token, self.kind, image, names, error)


class _ImageView(QGraphicsView):
    pixel_hovered = pyqtSignal(object)
    pixel_clicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet(ss_bg_dark())
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.fitted = True
        self.setMouseTracking(True)
        self.pixel_pick = False

    def _pixel(self, event):
        point = self.mapToScene(event.position().toPoint())
        import math
        return QPoint(math.floor(point.x()), math.floor(point.y()))

    def mouseMoveEvent(self, event):
        self.pixel_hovered.emit(self._pixel(event))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if self.pixel_pick and event.button() == Qt.MouseButton.LeftButton:
            self.pixel_clicked.emit(self._pixel(event))
            event.accept()
            return
        super().mousePressEvent(event)

    def fit(self):
        self.fitted = True
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitted:
            self.fit()

    def zoom(self, factor):
        scale = self.transform().m11() * factor
        if .02 <= scale <= 32:
            self.fitted = False
            self.scale(factor, factor)

    def wheelEvent(self, event):
        self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()


class ImagePreview(QWidget):
    def __init__(self, parent=None, *, maximum_height=360, minimum_height=240, compact=False):
        super().__init__(parent)
        layout = configure_layout(QVBoxLayout(self), LayoutRole.FIELD)
        actions = self.actions = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self.view = _ImageView()
        self.view.setMinimumHeight(minimum_height)
        if maximum_height is not None:
            self.view.setMaximumHeight(maximum_height)
        self.buttons = []
        for caption, action in ((ui_text('ui_texture_fit'), self.view.fit), ('1:1', self.actual_size),
                                ('−', lambda: self.view.zoom(1 / 1.2)), ('+', lambda: self.view.zoom(1.2))):
            button = configure_button(QPushButton(caption),
                                      height=Size.COMPACT_CONTROL if compact else Size.CONTROL)
            button.clicked.connect(action)
            actions.addWidget(button)
            self.buttons.append(button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(self.view, 1)
        self.set_image(None)

    def actual_size(self):
        self.view.fitted = False
        self.view.resetTransform()

    def set_checkerboard(self, enabled):
        """The checker is a view background, never baked into image pixels."""
        if enabled:
            tile = QPixmap(16, 16)
            tile.fill(QColor(P['bg_dark']))
            painter = QPainter(tile)
            painter.fillRect(0, 0, 8, 8, QColor(P['border']))
            painter.fillRect(8, 8, 8, 8, QColor(P['border']))
            painter.end()
            self.view.setBackgroundBrush(QBrush(tile))
        else:
            self.view.setBackgroundBrush(QBrush(QColor(P['bg_dark'])))

    def set_smooth(self, enabled):
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, enabled)

    def set_image(self, pil, *, preserve_view=False):
        center = self.view.mapToScene(self.view.viewport().rect().center())
        fitted = self.view.fitted
        self.view.scene().clear()
        for button in self.buttons:
            button.setEnabled(pil is not None)
        self.view.setVisible(pil is not None)
        if pil is not None:
            rgba = pil.convert('RGBA')
            data = rgba.tobytes()
            image = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
            self.view.scene().addPixmap(QPixmap.fromImage(image))
            self.view.setSceneRect(0, 0, rgba.width, rgba.height)
            if not preserve_view or fitted:
                self.view.fit()
            else:
                self.view.centerOn(center)
