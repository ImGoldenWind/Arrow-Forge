"""Prepare a widget window for OpenGL tools before its first native show."""
from PyQt6.QtOpenGLWidgets import QOpenGLWidget


def prepare_opengl_window(window):
    # Qt 6.4+ can destroy/recreate the native window when its first
    # QOpenGLWidget is added after show(). A hidden child reserves the GL
    # composition surface at initial creation, without loading a renderer.
    # Keep it parented to the window itself so rebuilding the UI cannot remove it.
    anchor = QOpenGLWidget(window)
    anchor.setObjectName('OpenGLSurfaceAnchor')
    anchor.setFixedSize(1, 1)
    anchor.hide()
    window._opengl_surface_anchor = anchor
