"""
Render to qt from agg
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import six

import ctypes
import traceback

from matplotlib import cbook
from matplotlib.figure import Figure
from matplotlib.transforms import Bbox

from .backend_agg import FigureCanvasAgg
from .backend_qt5 import (
    QtCore, QtGui, FigureCanvasQT, FigureManagerQT, NavigationToolbar2QT,
    backend_version, draw_if_interactive, show)
from .qt_compat import QT_API


def new_figure_manager(num, *args, **kwargs):
    """
    Create a new figure manager instance
    """
    FigureClass = kwargs.pop('FigureClass', Figure)
    thisFig = FigureClass(*args, **kwargs)
    return new_figure_manager_given_figure(num, thisFig)


def new_figure_manager_given_figure(num, figure):
    """
    Create a new figure manager instance for the given figure.
    """
    canvas = FigureCanvasQTAgg(figure)
    return FigureManagerQT(canvas, num)


class FigureCanvasQTAggBase(FigureCanvasAgg):
    """
    The canvas the figure renders into.  Calls the draw and print fig
    methods, creates the renderers, etc...

    Attributes
    ----------
    figure : `matplotlib.figure.Figure`
        A high-level Figure instance

    """

    def __init__(self, figure):
        super(FigureCanvasQTAggBase, self).__init__(figure=figure)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent)
        self._agg_draw_pending = False
        self._bbox_queue = []
        self._drawRect = None

    def drawRectangle(self, rect):
        if rect is not None:
            self._drawRect = [pt / self._dpi_ratio for pt in rect]
        else:
            self._drawRect = None
        self.update()

    @property
    @cbook.deprecated("2.1")
    def blitbox(self):
        return self._bbox_queue

    def paintEvent(self, e):
        """Copy the image from the Agg canvas to the qt.drawable.

        In Qt, all drawing should be done inside of here when a widget is
        shown onscreen.
        """
        # if the canvas does not have a renderer, then give up and wait for
        # FigureCanvasAgg.draw(self) to be called
        if not hasattr(self, 'renderer'):
            return

        painter = QtGui.QPainter(self)

        if self._bbox_queue:
            bbox_queue = self._bbox_queue
        else:
            painter.eraseRect(self.rect())
            bbox_queue = [
                Bbox([[0, 0], [self.renderer.width, self.renderer.height]])]
        self._bbox_queue = []
        for bbox in bbox_queue:
            l, b, r, t = map(int, bbox.extents)
            w = r - l
            h = t - b
            reg = self.copy_from_bbox(bbox)
            buf = reg.to_string_argb()
            qimage = QtGui.QImage(buf, w, h, QtGui.QImage.Format_ARGB32)
            if hasattr(qimage, 'setDevicePixelRatio'):
                # Not available on Qt4 or some older Qt5.
                qimage.setDevicePixelRatio(self._dpi_ratio)
            origin = QtCore.QPoint(l, self.renderer.height - t)
            painter.drawImage(origin / self._dpi_ratio, qimage)
            # Adjust the buf reference count to work around a memory
            # leak bug in QImage under PySide on Python 3.
            if QT_API == 'PySide' and six.PY3:
                ctypes.c_long.from_address(id(buf)).value = 1

        # draw the zoom rectangle to the QPainter
        if self._drawRect is not None:
            pen = QtGui.QPen(QtCore.Qt.black, 1 / self._dpi_ratio,
                             QtCore.Qt.DotLine)
            painter.setPen(pen)
            x, y, w, h = self._drawRect
            painter.drawRect(x, y, w, h)

        painter.end()

    def draw(self):
        """Draw the figure with Agg, and queue a request for a Qt draw.
        """
        # The Agg draw is done here; delaying causes problems with code that
        # uses the result of the draw() to update plot elements.
        super(FigureCanvasQTAggBase, self).draw()
        self.update()

    def draw_idle(self):
        """Queue redraw of the Agg buffer and request Qt paintEvent.
        """
        # The Agg draw needs to be handled by the same thread matplotlib
        # modifies the scene graph from. Post Agg draw request to the
        # current event loop in order to ensure thread affinity and to
        # accumulate multiple draw requests from event handling.
        # TODO: queued signal connection might be safer than singleShot
        if not self._agg_draw_pending:
            self._agg_draw_pending = True
            QtCore.QTimer.singleShot(0, self.__draw_idle_agg)

    def __draw_idle_agg(self, *args):
        if self.height() < 0 or self.width() < 0:
            self._agg_draw_pending = False
            return
        try:
            self.draw()
        except Exception:
            # Uncaught exceptions are fatal for PyQt5, so catch them instead.
            traceback.print_exc()
        finally:
            self._agg_draw_pending = False

    def blit(self, bbox=None):
        """Blit the region in bbox.
        """
        # If bbox is None, blit the entire canvas. Otherwise
        # blit only the area defined by the bbox.
        if bbox is None and self.figure:
            bbox = self.figure.bbox

        self._bbox_queue.append(bbox)

        # repaint uses logical pixels, not physical pixels like the renderer.
        l, b, w, h = [pt / self._dpi_ratio for pt in bbox.bounds]
        t = b + h
        self.repaint(l, self.renderer.height / self._dpi_ratio - t, w, h)

    def print_figure(self, *args, **kwargs):
        super(FigureCanvasQTAggBase, self).print_figure(*args, **kwargs)
        self.draw()


class FigureCanvasQTAgg(FigureCanvasQTAggBase, FigureCanvasQT):
    """
    The canvas the figure renders into.  Calls the draw and print fig
    methods, creates the renderers, etc.

    Modified to import from Qt5 backend for new-style mouse events.

    Attributes
    ----------
    figure : `matplotlib.figure.Figure`
        A high-level Figure instance

    """

    def __init__(self, figure):
        super(FigureCanvasQTAgg, self).__init__(figure=figure)
        # We don't want to scale up the figure DPI more than once.
        # Note, we don't handle a signal for changing DPI yet.
        if not hasattr(self.figure, '_original_dpi'):
            self.figure._original_dpi = self.figure.dpi
        self.figure.dpi = self._dpi_ratio * self.figure._original_dpi


FigureCanvas = FigureCanvasQTAgg
FigureManager = FigureManagerQT
