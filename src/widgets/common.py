"""通用组件：标题栏 / 轻提示 / 图标按钮 / 空状态 / 标签 / 徽标 / 步骤条 / 产出缩略图。"""
import os

from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtGui import QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import config
import icons
import theme
from theme import (   # 复用设计系统里的基础组件
    Card, SegmentedControl, Switch, dot, hline, vline,
)

__all__ = [
    "IconButton", "Toast", "toast", "EmptyState", "TitleBar", "Pill", "TagDot",
    "SegmentedControl", "Card", "Switch", "section_label", "hspacer",
    "hline", "vline", "dot", "Badge", "ToolButton", "StepBar", "IconLabel",
    "ClickableFrame", "GradientHandle", "SideEdge", "BrowserTab",
    "open_dir", "ArtifactThumb", "ArtifactStrip", "is_video",
]

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")


def is_video(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in VIDEO_EXTS


def open_dir(path: str) -> None:
    """在系统文件管理器里打开一个目录（跨平台）。"""
    import subprocess
    import sys
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def ArtifactThumb(path: str, size: int = 150) -> QWidget:
    """一个产出文件的缩略图（图片直接显示，视频显示播放图标）。

    抽出来是因为「流水线跑完的结果弹窗」和「素材库详情」都要用 ——
    两边各写一份必然走样。
    """
    card = QWidget()
    card.setFixedSize(size, size + 18)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)

    lb = QLabel()
    lb.setFixedSize(size, size - 10)
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lb.setStyleSheet(
        f"background:{theme.BG_SUBTLE};border:1px solid {theme.LINE};border-radius:10px;")
    if is_video(path):
        lb.setPixmap(icons.pixmap("play", theme.PRIMARY, 34, 2.0))
    else:
        pm = QPixmap(path)
        if not pm.isNull():
            lb.setPixmap(pm.scaled(size, size - 10, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation))
    lb.setToolTip(path)
    lay.addWidget(lb)

    nm = QLabel(os.path.basename(path))
    nm.setStyleSheet(f"background:transparent;{theme.css_font(10.5)}color:{theme.TEXT_3};")
    nm.setAlignment(Qt.AlignmentFlag.AlignCenter)
    nm.setToolTip(path)
    lay.addWidget(nm)

    card.setCursor(Qt.CursorShape.PointingHandCursor)
    card.mousePressEvent = lambda _e, p=path: open_dir(os.path.dirname(p))
    return card


def ArtifactStrip(paths, height: int = 180, limit: int = 12,
                  thumb: int = 150) -> QWidget:
    """产出文件的横向缩略图条（会自动过滤掉不存在的文件）。"""
    files = [p for p in (paths or []) if p and os.path.exists(p)]
    strip = QScrollArea()
    strip.setWidgetResizable(True)
    strip.setFrameShape(QFrame.Shape.NoFrame)
    strip.setFixedHeight(height)
    strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner = QWidget()
    il = QHBoxLayout(inner)
    il.setContentsMargins(0, 0, 0, 0)
    il.setSpacing(8)
    for p in files[:limit]:
        il.addWidget(ArtifactThumb(p, thumb))
    if len(files) > limit:
        more = QLabel(f"还有 {len(files) - limit} 个…")
        more.setObjectName("Muted")
        il.addWidget(more)
    il.addStretch(1)
    strip.setWidget(inner)
    strip.setProperty("_df_files", files)
    return strip


# ---------------------------------------------------------------- 侧栏手柄
class GradientHandle(QPushButton):
    """侧栏收起 / 展开手柄：骑在分界线上的细长渐变胶囊。

    设计取向参考 Notion / Linear 这类产品 —— 手柄平时**半透明**、不抢视线，
    鼠标移上去才完全显形。

    但「太含蓄」也是有代价的：第一版做到 18×44 + 0.55 透明度 + 12px 细箭头，
    贴在最底下，用户的原话是「不起作用，没有箭头」—— 根本没看见。
    现在放大到 20×50、常态透明度提到 0.85、箭头加粗到 2.6px，
    并且侧栏标题行里另有一个明确的 « 按钮兜底（见 sidebar.Sidebar）。
    """

    OPACITY_IDLE = 0.85
    OPACITY_HOVER = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SideHandle")
        self.setFixedSize(20, 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open = True
        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(self.OPACITY_IDLE)
        self.setGraphicsEffect(self._eff)
        self._anim = QPropertyAnimation(self._eff, b"opacity", self)
        self._anim.setDuration(130)
        self.set_open(True)

    def set_open(self, open_: bool):
        self._open = open_
        self.setIcon(icons.icon("chevron_left" if open_ else "chevron_right",
                                "#FFFFFF", 14, 2.6))
        self.setIconSize(QSize(14, 14))
        self.setToolTip("收起账号矩阵" if open_ else "展开账号矩阵")

    def _fade(self, to: float):
        self._anim.stop()
        self._anim.setEndValue(float(to))
        self._anim.start()

    def enterEvent(self, ev):
        self._fade(self.OPACITY_HOVER)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._fade(self.OPACITY_IDLE)
        super().leaveEvent(ev)


class SideEdge(QWidget):
    """侧栏右边缘的渐变指示线。

    比一个孤零零的按钮更含蓄：竖着的蓝→透明渐变，暗示「这条边可以收」。
    随侧栏一起显隐，宽度固定 3px。
    """

    W = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.W)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._grad = None

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())
        g = QLinearGradient(0, 0, 0, self.height())
        # 上淡下浓再淡出，形成一段「呼吸感」的指示
        c = QColor(theme.PRIMARY)
        g.setColorAt(0.00, QColor(c.red(), c.green(), c.blue(), 0))
        g.setColorAt(0.18, QColor(c.red(), c.green(), c.blue(), 70))
        g.setColorAt(0.50, QColor(c.red(), c.green(), c.blue(), 120))
        g.setColorAt(0.82, QColor(c.red(), c.green(), c.blue(), 70))
        g.setColorAt(1.00, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 1.5, 1.5)


# ---------------------------------------------------------------- 浏览器标签
class BrowserTab(QFrame):
    """浏览器区的一个账号标签，右侧带关闭 ×。"""

    selected = pyqtSignal(str)
    closed = pyqtSignal(str)

    def __init__(self, aid: str, name: str, active: bool = False, parent=None):
        super().__init__(parent)
        self.aid = aid
        self.setObjectName("BrowserTab")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("clickable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 4, 0)
        lay.setSpacing(6)

        self.lb = QLabel(name)
        self.lb.setStyleSheet(
            f"background:transparent;{theme.css_font(12.5, 400)}color:{theme.TEXT_2};")
        lay.addWidget(self.lb)

        self.btn_close = QPushButton()
        self.btn_close.setObjectName("TabClose")
        self.btn_close.setFixedSize(18, 18)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setIcon(icons.icon("close", theme.TEXT_3, 11))
        self.btn_close.setIconSize(QSize(11, 11))
        self.btn_close.setToolTip("关闭这个标签页")
        self.btn_close.clicked.connect(lambda: self.closed.emit(self.aid))
        lay.addWidget(self.btn_close)

        self.set_active(active)

    def set_active(self, on: bool):
        self.setProperty("active", bool(on))
        self.lb.setStyleSheet(
            f"background:transparent;"
            f"{theme.css_font(12.5, 600 if on else 400)}"
            f"color:{theme.PRIMARY if on else theme.TEXT_2};")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                ev.position().toPoint()):
            self.selected.emit(self.aid)
        super().mouseReleaseEvent(ev)


# ---------------------------------------------------------------- 图标按钮
class IconButton(QPushButton):
    def __init__(self, name: str, tip: str = "", size: int = 30, icon_size: int = 17,
                 color: str = None, hover_bg: str = None, parent=None):
        super().__init__(parent)
        self._name = name
        self._color = color or theme.TEXT_2
        self._icon_size = icon_size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icons.icon(name, self._color, icon_size))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setToolTip(tip)
        bg = hover_bg or theme.BG_HOVER
        self.setStyleSheet(f"""
            QPushButton {{ background:transparent; border:none; border-radius:6px; padding:0; }}
            QPushButton:hover {{ background:{bg}; }}
            QPushButton:pressed {{ background:{theme.LINE_SOFT}; }}
            QPushButton:disabled {{ background:transparent; }}
        """)

    def set_color(self, color: str):
        self._color = color
        self.setIcon(icons.icon(self._name, color, self._icon_size))

    def set_icon_name(self, name: str):
        self._name = name
        self.setIcon(icons.icon(name, self._color, self._icon_size))


class IconLabel(QLabel):
    """带圆形/圆角底色的图标徽标。"""

    def __init__(self, name: str, color: str = None, bg: str = None,
                 box: int = 34, icon_size: int = 17, radius: int = 10, parent=None):
        super().__init__(parent)
        color = color or theme.PRIMARY
        bg = bg or theme.PRIMARY_TINT
        self.setFixedSize(box, box)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(icons.pixmap(name, color, icon_size, 2.0))
        self.setStyleSheet(f"background:{bg};border-radius:{radius}px;")


# ---------------------------------------------------------------- 轻提示
class Toast(QWidget):
    """iOS 风格顶部轻提示，自动消失。"""

    _queue = []

    def __init__(self, parent: QWidget, text: str, kind: str = "info", msec: int = 2400):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        color = {"info": theme.PRIMARY, "ok": theme.SUCCESS,
                 "warn": theme.WARNING, "err": theme.DANGER}.get(kind, theme.PRIMARY)
        name = {"info": "check", "ok": "check", "warn": "warn", "err": "warn"}.get(kind, "check")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 16, 9)
        lay.setSpacing(9)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(name, color, 16, 2.0))
        ic.setStyleSheet("background:transparent;")
        lb = QLabel(text)
        lb.setStyleSheet(
            f"background:transparent;color:{theme.TEXT_1};"
            f"font-family:'{theme.FONT_FAMILY}';font-size:13px;font-weight:500;"
        )
        lay.addWidget(ic)
        lay.addWidget(lb)

        self.setStyleSheet(
            f"QWidget{{background:{theme.BG_CARD};border:1px solid {theme.LINE};"
            f"border-radius:10px;}}"
        )
        self.adjustSize()

        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        self._anim = QPropertyAnimation(eff, b"opacity", self)
        self._anim.setDuration(200)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

        QTimer.singleShot(msec, self._close)
        self._place()

    def _place(self):
        p = self.parentWidget()
        if not p:
            return
        # 放到底部居中，避免压住顶部导航条 / 各页自己的操作栏
        x = max(12, (p.width() - self.width()) // 2)
        y = max(12, p.height() - self.height() - 26)
        self.move(x, y)
        self.raise_()

    def _close(self):
        eff = self.graphicsEffect()
        if not eff:
            self.deleteLater()
            return
        a = QPropertyAnimation(eff, b"opacity", self)
        a.setDuration(180)
        a.setStartValue(eff.opacity())
        a.setEndValue(0.0)
        a.setEasingCurve(QEasingCurve.Type.InCubic)
        a.finished.connect(self.deleteLater)
        a.start()
        self._fade = a


def toast(parent: QWidget, text: str, kind: str = "info", msec: int = 2400):
    if parent is None:
        return
    t = Toast(parent, text, kind, msec)
    t.show()
    t.raise_()
    return t


# ---------------------------------------------------------------- 空状态
class EmptyState(QWidget):
    def __init__(self, title: str, desc: str = "", icon_name: str = "folder", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 48, 24, 48)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ic = QLabel()
        ic.setFixedSize(56, 56)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(icons.pixmap(icon_name, theme.PRIMARY, 24, 1.9))
        ic.setStyleSheet(
            f"background:{theme.BG_INPUT};border:1px solid {theme.LINE};border-radius:17px;")
        ic.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        t = QLabel(title)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"background:transparent;{theme.css_font(14, 600)}color:{theme.TEXT_2};")

        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(t)
        if desc:
            d = QLabel(desc)
            d.setAlignment(Qt.AlignmentFlag.AlignCenter)
            d.setWordWrap(True)
            d.setMaximumWidth(360)
            d.setStyleSheet(f"background:transparent;{theme.css_font(12.5)}color:{theme.TEXT_3};")
            lay.addWidget(d, 0, Qt.AlignmentFlag.AlignHCenter)


# ---------------------------------------------------------------- 标题栏
class TitleBar(QWidget):
    """自绘标题栏：拖动移动窗口 · 双击最大化 · 窗口按钮。

    顶部这一条同时承载品牌区、主导航（由主窗口塞进 .center）和窗口按钮 ——
    少一行导航栏，竖向空间全留给内容。
    """

    minimize = pyqtSignal()
    maximize = pyqtSignal()
    close = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(58)
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(10)

        mark = QLabel()
        mark.setFixedSize(24, 24)
        mark.setStyleSheet(
            f"background:{theme.PRIMARY};border-radius:7px;color:#fff;"
            f"{theme.css_font(13, 700)}"
        )
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setText("D")

        name = QLabel(config.APP_NAME)
        name.setObjectName("TitleMark")

        self.lb_sub = QLabel("· " + config.APP_SUBTITLE)
        self.lb_sub.setObjectName("TitleText")

        lay.addWidget(mark)
        lay.addWidget(name)
        lay.addWidget(self.lb_sub)
        lay.addSpacing(14)

        # 导航槽位：主窗口把 SegmentedControl 塞进来
        self.center = QWidget()
        self.center_lay = QHBoxLayout(self.center)
        self.center_lay.setContentsMargins(0, 0, 0, 0)
        self.center_lay.setSpacing(8)
        lay.addWidget(self.center)

        lay.addStretch(1)

        # 右侧操作槽位（设置按钮等）
        self.actions = QWidget()
        self.actions_lay = QHBoxLayout(self.actions)
        self.actions_lay.setContentsMargins(0, 0, 0, 0)
        self.actions_lay.setSpacing(8)
        lay.addWidget(self.actions)

        lay.addSpacing(4)
        self.btn_min = IconButton("minus", "最小化", 30, 16)
        self.btn_max = IconButton("max", "最大化", 30, 15)
        self.btn_close = IconButton("close", "关闭", 30, 16, hover_bg=theme.DANGER)
        self.btn_min.clicked.connect(self.minimize.emit)
        self.btn_max.clicked.connect(self.maximize.emit)
        self.btn_close.clicked.connect(self.close.emit)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

    def add_action(self, w: QWidget):
        self.actions_lay.addWidget(w)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 窗口窄的时候先砍副标题，别把导航挤变形
        self.lb_sub.setVisible(self.width() >= 1240)

    # ---------------------------------------------------------- 拖动窗口
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._drag_pos = (ev.globalPosition().toPoint()
                              - win.frameGeometry().topLeft())
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_pos is None or not (ev.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(ev)
        win = self.window()
        # 最大化状态下拖动 → 先还原，并让光标保持在标题栏相对位置
        if win.isMaximized():
            ratio = ev.globalPosition().toPoint().x() / max(1, win.width())
            win.showNormal()
            new_x = int(ev.globalPosition().toPoint().x() - win.width() * ratio)
            win.move(new_x, max(0, ev.globalPosition().toPoint().y() - 20))
            self._drag_pos = (ev.globalPosition().toPoint()
                              - win.frameGeometry().topLeft())
            return
        win.move(ev.globalPosition().toPoint() - self._drag_pos)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.maximize.emit()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def refresh(self):
        self.btn_close.set_color(theme.TEXT_2)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{ background:transparent; border:none; border-radius:6px; padding:0; }}
            QPushButton:hover {{ background:{theme.DANGER}; }}
        """)
        self.btn_close.setIcon(icons.icon("close", "#FFFFFF", 16))


# ---------------------------------------------------------------- 小标签
class Pill(QLabel):
    def __init__(self, text: str, color: str = None, bg: str = None, parent=None,
                 bold: bool = False):
        super().__init__(text, parent)
        color = color or theme.TEXT_2
        bg = bg or theme.BG_INPUT
        self.setStyleSheet(
            f"background:{bg};color:{color};border-radius:9px;"
            f"padding:3px 9px;{theme.css_font(11.5, 600 if bold else 500)}"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class Badge(QLabel):
    """数字/文字徽标（账号数量等）。"""

    def __init__(self, text: str = "", color: str = None, bg: str = None, parent=None):
        super().__init__(text, parent)
        self.set_color(color or theme.TEXT_3, bg or theme.BG_INPUT)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_color(self, color: str, bg: str):
        self.setStyleSheet(
            f"background:{bg};color:{color};border-radius:8px;"
            f"padding:1px 7px;{theme.css_font(11, 600)}"
        )


class TagDot(QWidget):
    """平台标识小圆点 + 简称。"""

    def __init__(self, short: str, color: str, parent=None, size: int = 20):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._short = short
        self._color = color
        self._size = size

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        p.drawRoundedRect(QRectF(0, 0, self._size, self._size),
                          self._size * 0.3, self._size * 0.3)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(theme.font(int(self._size * 0.5), 600))
        p.drawText(QRectF(0, 0, self._size, self._size),
                   Qt.AlignmentFlag.AlignCenter, self._short)
        p.end()


class ClickableFrame(QFrame):
    """带悬停反馈的可点击容器（列表行等）。"""

    clicked = pyqtSignal()

    def __init__(self, parent=None, object_name: str = "CardHover"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                ev.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


# ---------------------------------------------------------------- 工具按钮
class ToolButton(QPushButton):
    """工具栏按钮：图标 + 文字，可选角标。"""

    def __init__(self, text: str, icon_name: str = "", kind: str = "Soft",
                 tip: str = "", parent=None):
        super().__init__(text, parent)
        self._icon_name = icon_name
        self._kind = kind
        self.setObjectName(kind)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setToolTip(tip or text)
        if icon_name:
            color = "#FFFFFF" if kind in ("Primary", "Danger") else theme.TEXT_2
            self.setIcon(icons.icon(icon_name, color, 15))
            self.setIconSize(QSize(15, 15))

    def set_icon_name(self, name: str):
        self._icon_name = name
        color = "#FFFFFF" if self._kind in ("Primary", "Danger") else theme.TEXT_2
        self.setIcon(icons.icon(name, color, 15))


# ---------------------------------------------------------------- 步骤条
class StepBar(QWidget):
    """横向步骤指示器：① 打开发布页 → ② 一键填充 → ③ 核对 → ④ 一键发布。"""

    def __init__(self, steps: list, parent=None):
        super().__init__(parent)
        self._steps = list(steps)
        self._current = 0
        self._labels: list = []
        self._dots: list = []
        self._bars: list = []

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for i, text in enumerate(self._steps):
            dot_lb = QLabel(str(i + 1))
            dot_lb.setFixedSize(18, 18)
            dot_lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(dot_lb)
            self._dots.append(dot_lb)

            lb = QLabel(text)
            lay.addWidget(lb)
            self._labels.append(lb)

            if i < len(self._steps) - 1:
                bar = QWidget()
                bar.setFixedHeight(2)
                bar.setMinimumWidth(18)
                bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                lay.addWidget(bar, 1)
                self._bars.append(bar)
        self.set_step(0)

    def set_step(self, idx: int):
        self._current = idx
        for i, (d, lb) in enumerate(zip(self._dots, self._labels)):
            if i < idx:
                d.setStyleSheet(f"background:{theme.SUCCESS_TINT};color:{theme.SUCCESS};"
                                f"border-radius:9px;{theme.css_font(11, 700)}")
                lb.setStyleSheet(f"background:transparent;{theme.css_font(12, 400)}"
                                 f"color:{theme.TEXT_3};")
            elif i == idx:
                d.setStyleSheet(f"background:{theme.PRIMARY};color:#FFFFFF;"
                                f"border-radius:9px;{theme.css_font(11, 700)}")
                lb.setStyleSheet(f"background:transparent;{theme.css_font(12, 600)}"
                                 f"color:{theme.PRIMARY};")
            else:
                d.setStyleSheet(f"background:{theme.BG_INPUT};color:{theme.TEXT_4};"
                                f"border-radius:9px;{theme.css_font(11, 600)}")
                lb.setStyleSheet(f"background:transparent;{theme.css_font(12, 400)}"
                                 f"color:{theme.TEXT_4};")
        for i, bar in enumerate(self._bars):
            color = theme.SUCCESS if i < idx else theme.LINE
            bar.setStyleSheet(f"background:{color};border-radius:1px;")


def section_label(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("SectionLabel")
    return lb


def hspacer() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w
