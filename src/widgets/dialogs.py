"""统一弹窗体系：自绘标题栏 · 圆角 · 投影 · 字体分级。

为什么要自建而不是用 QMessageBox / QInputDialog：
  · Qt 默认弹窗是系统配色，和本应用的 iOS 风格设计系统完全不搭
  · QInputDialog 的按钮是 "OK / Cancel" 且没有字号层级，观感非常基础
  · 自建后可以统一控制标题字重、正文行高、按钮主次、危险色

对外主要 API：
    BaseDialog(parent, title, subtitle="")   → 空壳，往 .body 里塞内容
    MessageDialog.alert(...)                 → 只有一个「知道了」按钮
    MessageDialog.confirm(...)               → 返回 bool
    TextInputDialog.get_text(...)            → 单行
    TextInputDialog.get_multiline(...)       → 多行（批量导入选题用）
"""
from typing import List, Optional, Tuple

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import icons
import theme
from widgets.common import IconButton


class BaseDialog(QDialog):
    """自绘标题栏的对话框基类。

    结构：
        ┌──────────────────────────────┐  ← 投影
        │ 标题                 [×]     │  ← .head（可拖动）
        │ 副标题说明                    │
        ├──────────────────────────────┤
        │  .body   ← 内容往这里塞       │
        ├──────────────────────────────┤
        │              [取消] [确定]    │  ← .foot（可选）
        └──────────────────────────────┘
    """

    def __init__(self, parent=None, title: str = "", subtitle: str = "",
                 width: int = 520, height: int = 0):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._drag_pos: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)   # 给投影留出空间
        outer.setSpacing(0)

        self.card = QWidget()
        self.card.setObjectName("DlgCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 23, 28, 46))
        self.card.setGraphicsEffect(shadow)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------- 头部
        self.head = QWidget()
        self.head.setObjectName("DlgHead")
        self.head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(24, 18, 14, 16)
        hl.setSpacing(12)

        col = QVBoxLayout()
        col.setSpacing(3)
        self.lb_title = QLabel(title)
        self.lb_title.setObjectName("DlgTitle")
        col.addWidget(self.lb_title)
        self.lb_sub = QLabel(subtitle)
        self.lb_sub.setObjectName("DlgSub")
        self.lb_sub.setWordWrap(True)
        self.lb_sub.setVisible(bool(subtitle))
        col.addWidget(self.lb_sub)
        hl.addLayout(col, 1)

        self.btn_close = IconButton("close", "关闭", 28, 14)
        self.btn_close.clicked.connect(self.reject)
        hl.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.head)

        # ---------------- 内容
        # 用滚动区承载：内容比窗口高时滚动，而不是把控件硬挤到重叠
        # （曾经踩过：SkillDialog 的 Prompt 编辑框被挤到底部，下面的提示文字
        #   直接压在了编辑框上，看起来像渲染花了，实际是布局空间不够）
        self.body_host = QWidget()
        self.body_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(self.body_host, "#FFFFFF")
        self.body = QVBoxLayout(self.body_host)
        self.body.setContentsMargins(24, 4, 24, 20)
        self.body.setSpacing(14)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.body_host)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 让滚动区的 sizeHint 跟随内容 —— 否则弹窗永远按「最小可滚动尺寸」开，
        # 屏幕明明放得下也会出现滚动条
        self.scroll.setSizeAdjustPolicy(
            QScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        theme.paint_bg(self.scroll, "#FFFFFF")
        theme.paint_bg(self.scroll.viewport(), "#FFFFFF")
        root.addWidget(self.scroll, 1)

        # ---------------- 底部（有按钮时才显示）
        self.foot = QWidget()
        self.foot.setObjectName("DlgFoot")
        self.foot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.foot.setVisible(False)
        self.foot_lay = QHBoxLayout(self.foot)
        self.foot_lay.setContentsMargins(24, 14, 24, 14)
        self.foot_lay.setSpacing(10)
        root.addWidget(self.foot)

        self._width = width
        self._fitted = False
        if width:
            self.setMinimumWidth(width + 40)
        if height:
            self.setMinimumHeight(height + 40)

        # 头部可拖动
        self.head.mousePressEvent = self._head_press
        self.head.mouseMoveEvent = self._head_move
        self.head.mouseReleaseEvent = self._head_release

    # ---------------------------------------------------------- 自适应尺寸
    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._fitted:
            self._fitted = True
            self._fit_to_screen()

    def _fit_to_screen(self):
        """按内容高度自适应，超出可用区域时交给滚动区，并把窗口居中。

        为什么不直接用 sizeHint：滚动区的 sizeHint 不会老实反映内容高度，
        即使设了 AdjustToContents 也偏小 —— 结果就是屏幕明明放得下也冒出滚动条。
        所以这里显式按 head + body_host + foot 求和。
        """
        ref = self._ref_rect()
        max_w = max(360, int(ref.width() * 0.94))
        max_h = max(320, int(ref.height() * 0.9))

        # 屏幕/父窗比最小尺寸还小时，把下限压到可用范围，否则 resize 会被顶回去
        if self.minimumWidth() > max_w:
            self.setMinimumWidth(max_w)
        if self.minimumHeight() > max_h:
            self.setMinimumHeight(max_h)

        hint = self.sizeHint()
        w = min(max(hint.width(), self.minimumWidth()), max_w)
        self.resize(w, self.height())

        self.layout().activate()
        need_h = (self.head.sizeHint().height()
                  + self.body_host.sizeHint().height()
                  + 42)                       # 42 = 上下投影外边距
        if self.foot.isVisible():
            need_h += self.foot.sizeHint().height()
        h = min(max(need_h, self.minimumHeight()), max_h)
        self.resize(w, h)

        self.move(ref.center().x() - w // 2, ref.center().y() - h // 2)

    def _ref_rect(self):
        """参照矩形：优先父窗口（弹窗不该比父窗还大），否则退回屏幕可用区。"""
        par = self.parentWidget()
        if par is not None:
            top = par.window()
            if top is not None and top.isVisible():
                g = top.frameGeometry()
                if g.width() >= 480 and g.height() >= 400:
                    return g
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry() if scr is not None else self.geometry()

    # ---------------------------------------------------------- 拖动
    def _head_press(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def _head_move(self, ev):
        if self._drag_pos is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
            ev.accept()

    def _head_release(self, _ev):
        self._drag_pos = None

    # ---------------------------------------------------------- 按钮区
    def add_button(self, text: str, kind: str = "Soft", on_click=None,
                   default: bool = False) -> QPushButton:
        b = QPushButton(text)
        if kind:
            b.setObjectName(kind)
        b.setMinimumWidth(88)
        b.setMinimumHeight(34)
        if on_click is not None:
            b.clicked.connect(on_click)
        if default:
            b.setDefault(True)
        self.foot_lay.addWidget(b)
        self.foot.setVisible(True)
        return b

    def add_stretch(self):
        self.foot_lay.addStretch(1)


# ================================================================ 提示 / 确认
class MessageDialog(BaseDialog):
    KIND = {
        "info": (theme.PRIMARY, theme.PRIMARY_TINT, "check"),
        "ok": (theme.SUCCESS, theme.SUCCESS_TINT, "check"),
        "warn": (theme.WARNING, theme.WARNING_TINT, "warn"),
        "err": (theme.DANGER, theme.DANGER_TINT, "warn"),
        "ask": (theme.PRIMARY, theme.PRIMARY_TINT, "warn"),
    }

    def __init__(self, parent=None, title: str = "", text: str = "",
                 kind: str = "info", confirm: bool = False,
                 ok_text: str = "知道了", cancel_text: str = "取消",
                 detail: str = "", destructive: bool = False):
        super().__init__(parent, title, width=460)
        self._result = False
        color, tint, icon_name = self.KIND.get(kind, self.KIND["info"])

        row = QHBoxLayout()
        row.setSpacing(14)

        badge = QLabel()
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap(icon_name, color, 19, 2.0))
        badge.setStyleSheet(f"background:{tint};border-radius:11px;")
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(6)
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet(f"background:transparent;{theme.css_font(14, 400)}color:{theme.TEXT_1};")
        col.addWidget(lb)
        if detail:
            d = QLabel(detail)
            d.setWordWrap(True)
            d.setStyleSheet(f"background:transparent;{theme.css_font(12.5, 400)}color:{theme.TEXT_3};")
            col.addWidget(d)
        row.addLayout(col, 1)
        self.body.addLayout(row)

        self.add_stretch()
        ok_kind = "Danger" if destructive else "Primary"
        if confirm:
            self.add_button(cancel_text, "Soft", self.reject)
            self.add_button(ok_text, ok_kind, self._ok, default=not destructive)
        else:
            self.add_button(ok_text, ok_kind, self._ok, default=True)

    def _ok(self):
        self._result = True
        self.accept()

    # ---------------------------------------------------------- 快捷方法
    @staticmethod
    def alert(parent, title: str, text: str, kind: str = "info",
              detail: str = "", ok_text: str = "知道了") -> None:
        d = MessageDialog(parent, title, text, kind, confirm=False,
                          ok_text=ok_text, detail=detail)
        d.exec()

    @staticmethod
    def confirm(parent, title: str, text: str, kind: str = "ask",
                detail: str = "", ok_text: str = "确定",
                cancel_text: str = "取消", destructive: bool = False) -> bool:
        d = MessageDialog(parent, title, text, kind, confirm=True,
                          ok_text=ok_text, cancel_text=cancel_text,
                          detail=detail, destructive=destructive)
        d.exec()
        return d._result


# ================================================================ 文本输入
class TextInputDialog(BaseDialog):
    def __init__(self, parent=None, title: str = "输入", label: str = "",
                 text: str = "", multiline: bool = False,
                 placeholder: str = "", ok_text: str = "确定",
                 width: int = 520, min_lines: int = 8):
        super().__init__(parent, title, width=width)
        self._multiline = multiline

        if label:
            lb = QLabel(label)
            lb.setObjectName("FieldLabel")
            self.body.addWidget(lb)

        if multiline:
            self.editor = QPlainTextEdit()
            self.editor.setPlainText(text)
            self.editor.setPlaceholderText(placeholder)
            self.editor.setMinimumHeight(min_lines * 22 + 24)
            self.body.addWidget(self.editor, 1)
        else:
            from PyQt6.QtWidgets import QLineEdit
            self.editor = QLineEdit(text)
            self.editor.setPlaceholderText(placeholder)
            self.editor.setMinimumHeight(36)
            self.body.addWidget(self.editor)

        if multiline:
            self.lb_count = QLabel("")
            self.lb_count.setObjectName("Hint")
            self.lb_count.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.body.addWidget(self.lb_count)
            self.editor.textChanged.connect(self._on_change)
            self._on_change()

        self.add_stretch()
        self.add_button("取消", "Soft", self.reject)
        self.add_button(ok_text, "Primary", self._ok, default=True)

    def _on_change(self):
        n = len([x for x in self.editor.toPlainText().split("\n") if x.strip()])
        self.lb_count.setText(f"共 {n} 条" if n else "")

    def _ok(self):
        self.accept()

    def value(self) -> str:
        if self._multiline:
            return self.editor.toPlainText()
        return self.editor.text()

    # ---------------------------------------------------------- 快捷方法
    @staticmethod
    def get_multiline(parent, title: str, label: str = "", text: str = "",
                      placeholder: str = "", ok_text: str = "确定",
                      width: int = 560) -> Tuple[str, bool]:
        d = TextInputDialog(parent, title, label, text, True, placeholder,
                            ok_text, width)
        ok = d.exec() == QDialog.DialogCode.Accepted
        return d.value(), ok

    @staticmethod
    def get_text(parent, title: str, label: str = "", text: str = "",
                 placeholder: str = "", ok_text: str = "确定") -> Tuple[str, bool]:
        d = TextInputDialog(parent, title, label, text, False, placeholder, ok_text)
        ok = d.exec() == QDialog.DialogCode.Accepted
        return d.value(), ok


# ================================================================ 通用分组卡
class FormSection(QWidget):
    """弹窗里用的分组标题 + 内容容器。"""

    def __init__(self, title: str, hint: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setObjectName("FieldLabel")
            lay.addWidget(t)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        lay.addLayout(self.body)
        if hint:
            h = QLabel(hint)
            h.setObjectName("Hint")
            h.setWordWrap(True)
            lay.addWidget(h)


def paint_round_rect(widget: QWidget, radius: int, color: str) -> None:
    """给一个裸 QWidget 画圆角底色（少数场景需要自绘）。"""
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, widget.width(), widget.height(), radius, radius)
    p.fillPath(path, QColor(color))
    p.end()


__all__ = ["BaseDialog", "MessageDialog", "TextInputDialog", "FormSection"]
