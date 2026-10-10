"""无边框窗口的缩放热区。

为什么不用 `windowHandle().startSystemResize()`：
  它要求鼠标事件能冒泡到承载窗口的那个 widget。但本应用里内容控件铺满整窗，
  落在边缘的点击常被 QLineEdit / QListWidget 之类「会接受点击」的控件吃掉，
  于是窗口边缘在某些位置就是拖不动 —— 表现为「上下左右偶尔能拖，偶尔不能」。

这里改成在窗口四边与四角放一层**置顶的透明热区控件**：
  它们在最上层，事件必然先到它们手里，不依赖任何冒泡，行为稳定。
代价是窗口外圈 5px 不再响应内容点击 —— 这恰好就是缩放该有的语义。
"""
from typing import Optional

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QWidget

EDGE = 5


class ResizeGrip(QWidget):
    """一个方向（或角）的缩放热区。"""

    # 用位标记表示方向
    L, R, T, B = 1, 2, 4, 8

    _CURSORS = {
        L: Qt.CursorShape.SizeHorCursor,
        R: Qt.CursorShape.SizeHorCursor,
        T: Qt.CursorShape.SizeVerCursor,
        B: Qt.CursorShape.SizeVerCursor,
        L | T: Qt.CursorShape.SizeFDiagCursor,
        R | B: Qt.CursorShape.SizeFDiagCursor,
        R | T: Qt.CursorShape.SizeBDiagCursor,
        L | B: Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, win: QWidget, edges: int, parent: QWidget):
        super().__init__(parent)
        self.win = win
        self.edges = edges
        self.setMouseTracking(True)
        self.setCursor(self._CURSORS.get(edges, Qt.CursorShape.ArrowCursor))
        self._start_geo = None
        self._start_pos: Optional[QPoint] = None
        self.setToolTip("拖动可调整窗口大小")

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        if self.win.isMaximized():
            return super().mousePressEvent(ev)
        self._start_geo = self.win.geometry()
        self._start_pos = ev.globalPosition().toPoint()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._start_geo is None or self._start_pos is None:
            return super().mouseMoveEvent(ev)
        if not (ev.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(ev)

        g = self._start_geo
        d = ev.globalPosition().toPoint() - self._start_pos
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        min_w = max(760, self.win.minimumWidth())
        min_h = max(520, self.win.minimumHeight())

        if self.edges & self.L:
            nx = x + d.x()
            nw = w - d.x()
            if nw >= min_w:
                x, w = nx, nw
        if self.edges & self.R:
            w = max(min_w, w + d.x())
        if self.edges & self.T:
            ny = y + d.y()
            nh = h - d.y()
            if nh >= min_h:
                y, h = ny, nh
        if self.edges & self.B:
            h = max(min_h, h + d.y())

        self.win.setGeometry(x, y, w, h)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._start_geo = None
        self._start_pos = None
        super().mouseReleaseEvent(ev)


class WindowResizer:
    """在窗口根容器上铺 8 个缩放热区，并在窗口尺寸变化时重新贴合。"""

    def __init__(self, win: QWidget, root: QWidget, edge: int = EDGE):
        self.win = win
        self.root = root
        self.edge = edge
        self.grips = []
        combos = (
            ResizeGrip.L, ResizeGrip.R, ResizeGrip.T, ResizeGrip.B,
            ResizeGrip.L | ResizeGrip.T, ResizeGrip.R | ResizeGrip.T,
            ResizeGrip.L | ResizeGrip.B, ResizeGrip.R | ResizeGrip.B,
        )
        for c in combos:
            g = ResizeGrip(win, c, root)
            g.show()
            self.grips.append(g)

    def relayout(self):
        """按当前窗口尺寸摆放热区；最大化时隐藏（此时不该能缩放）。"""
        w, h = self.root.width(), self.root.height()
        e = self.edge
        visible = not self.win.isMaximized() and not self.win.isFullScreen()
        geo = {
            ResizeGrip.L: (0, e, e, max(0, h - 2 * e)),
            ResizeGrip.R: (w - e, e, e, max(0, h - 2 * e)),
            ResizeGrip.T: (e, 0, max(0, w - 2 * e), e),
            ResizeGrip.B: (e, h - e, max(0, w - 2 * e), e),
            ResizeGrip.L | ResizeGrip.T: (0, 0, e, e),
            ResizeGrip.R | ResizeGrip.T: (w - e, 0, e, e),
            ResizeGrip.L | ResizeGrip.B: (0, h - e, e, e),
            ResizeGrip.R | ResizeGrip.B: (w - e, h - e, e, e),
        }
        for g in self.grips:
            x, y, gw, gh = geo[g.edges]
            g.setGeometry(x, y, max(1, gw), max(1, gh))
            g.setVisible(visible)
            g.raise_()
