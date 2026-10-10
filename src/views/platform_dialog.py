"""自定义平台对话框：新增 / 编辑一个内置列表里没有的平台。

自定义平台没有适配脚本（adapters/*.js），所以发布时自动降级为
「复制到剪贴板 + 打开发布页」由人工粘贴 —— 这也是既有兜底逻辑。
"""
from typing import Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

import platforms as PF
import theme
from widgets.common import TagDot
from widgets.dialogs import BaseDialog, MessageDialog


def _field(label: str, widget: QWidget, hint: str = "") -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    lb = QLabel(label)
    lb.setObjectName("FieldLabel")
    lay.addWidget(lb)
    lay.addWidget(widget)
    if hint:
        h = QLabel(hint)
        h.setObjectName("Hint")
        h.setWordWrap(True)
        lay.addWidget(h)
    return box


class ColorPicker(QWidget):
    """一排色块，点一下选中。不引入 QColorDialog，少一个系统弹窗。"""

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self._value = current or PF.COLOR_CHOICES[0]
        self._swatches: Dict[str, QWidget] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for c in PF.COLOR_CHOICES:
            sw = QWidget()
            sw.setFixedSize(26, 26)
            sw.setProperty("clickable", True)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip(c)
            sw.mouseReleaseEvent = (lambda _ev, col=c: self.set_value(col))
            theme.paint_bg(sw, c)          # 建立 objectName + 打开背景绘制
            self._swatches[c] = sw
            lay.addWidget(sw)
        lay.addStretch(1)
        self._paint()

    def _paint(self):
        for c, sw in self._swatches.items():
            on = (c == self._value)
            cls = sw.metaObject().className()
            border = theme.TEXT_1 if on else "transparent"
            sw.setStyleSheet(
                f"{cls}#{sw.objectName()} {{"
                f"background:{c}; border-radius:8px; border:2px solid {border}; }}"
            )

    def set_value(self, color: str):
        self._value = color
        self._paint()

    def value(self) -> str:
        return self._value


class PlatformDialog(BaseDialog):
    def __init__(self, parent=None, key: str = "", preset_name: str = ""):
        self.key = key or ""
        editing = bool(self.key)
        p = PF.get(self.key) if editing else None
        p = p or {}

        super().__init__(
            parent,
            "编辑平台" if editing else "新增平台",
            "内置平台改不了，这里新增的平台存在本机。自定义平台没有自动填充脚本，"
            "发布时会复制内容并打开发布页，由你手动粘贴。",
            width=600)

        body = self.body

        row = QHBoxLayout()
        row.setSpacing(12)
        self.ed_name = QLineEdit(p.get("name", preset_name))
        self.ed_name.setPlaceholderText("例如：知乎 / B站 / 百家号")
        row.addWidget(_field("平台名称", self.ed_name), 3)

        self.ed_short = QLineEdit(p.get("short", ""))
        self.ed_short.setPlaceholderText("自动取首字")
        self.ed_short.setMaxLength(2)
        row.addWidget(_field("简称（图标里的字）", self.ed_short), 2)
        body.addLayout(row)

        # 预览
        pv = QHBoxLayout()
        pv.setSpacing(8)
        pv.addWidget(_field("图标预览", self._preview_row()))
        body.addLayout(pv)

        self.picker = ColorPicker(p.get("color", ""))
        body.addWidget(_field("主题色", self.picker))

        self.ed_publish = QLineEdit(p.get("publish_url", ""))
        self.ed_publish.setPlaceholderText("https://…  发布/创作页地址（必填其一）")
        body.addWidget(_field("发布页网址", self.ed_publish,
                              "点账号行、点「打开发布页」都会走这个地址"))

        self.ed_login = QLineEdit(p.get("login_url", ""))
        self.ed_login.setPlaceholderText("https://…  登录页（选填）")
        body.addWidget(_field("登录页网址", self.ed_login))

        self.ed_home = QLineEdit(p.get("home_url", ""))
        self.ed_home.setPlaceholderText("https://…  后台首页（选填）")
        body.addWidget(_field("后台首页网址", self.ed_home))

        self.add_stretch()
        if editing:
            self.add_button("删除该平台", "Danger", self._on_delete)
        self.add_button("取消", "Soft", self.reject)
        self.add_button("保存", "Primary", self._on_ok, default=True)

        self.ed_name.textChanged.connect(self._refresh_preview)
        self.ed_short.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    # ---------------------------------------------------------- 预览
    def _preview_row(self) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._pv_dot_host = QWidget()
        ph = QHBoxLayout(self._pv_dot_host)
        ph.setContentsMargins(0, 0, 0, 0)
        self._pv_name = QLabel("")
        self._pv_name.setObjectName("Muted")
        lay.addWidget(self._pv_dot_host)
        lay.addWidget(self._pv_name)
        lay.addStretch(1)
        return box

    def _refresh_preview(self):
        name = self.ed_name.text().strip() or "新平台"
        short = (self.ed_short.text().strip() or name[:1]) or "?"
        theme.clear_layout(self._pv_dot_host.layout())
        self._pv_dot_host.layout().addWidget(TagDot(short, self.picker.value(), size=22))
        self._pv_name.setText(name)

    # ---------------------------------------------------------- 保存
    def _collect(self) -> Dict[str, str]:
        name = self.ed_name.text().strip()
        short = self.ed_short.text().strip() or name[:1]
        return {
            "name": name,
            "short": short,
            "color": self.picker.value(),
            "publish_url": self.ed_publish.text().strip(),
            "login_url": self.ed_login.text().strip(),
            "home_url": self.ed_home.text().strip(),
        }

    def _on_ok(self):
        f = self._collect()
        if not f["name"]:
            MessageDialog.alert(self, "还差一点", "平台名称不能为空", "warn")
            return
        if not (f["publish_url"] or f["login_url"] or f["home_url"]):
            MessageDialog.alert(self, "还差一点", "至少要填一个网址", "warn")
            return
        try:
            if self.key:
                PF.update_custom(self.key, f)
            else:
                item = PF.add_custom(**f)
                self.key = item["key"]
        except Exception as e:
            MessageDialog.alert(self, "保存失败", str(e), "err")
            return
        self.accept()

    def _on_delete(self):
        if not self.key:
            return
        ok = MessageDialog.confirm(
            self.window(), "删除平台",
            f"确定删除「{PF.name_of(self.key)}」这个自定义平台吗？",
            kind="err", ok_text="删除", destructive=True,
            detail="已经添加的账号不会被删除，但会失去平台定义（打不开网址）。")
        if not ok:
            return
        PF.delete_custom(self.key)
        self.key = ""
        self.reject()

    def result_key(self) -> str:
        return self.key
