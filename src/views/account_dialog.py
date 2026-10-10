"""账号新增 / 编辑对话框。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

import platforms as PF
import store
import theme
from widgets.common import IconButton
from widgets.dialogs import BaseDialog, MessageDialog

NEW_PLATFORM = "__new__"


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


class AccountDialog(BaseDialog):
    def __init__(self, parent=None, aid: str = None, platform_key: str = None):
        self.aid = aid
        self.db = store.load_accounts()
        acc = store.get_account(self.db, aid) if aid else None

        super().__init__(parent, "编辑账号" if acc else "添加账号",
                         "账号只保存名称与备注，不保存任何密码。登录请在内嵌浏览器里手动完成。",
                         width=580)

        body = self.body

        row = QHBoxLayout()
        row.setSpacing(12)
        self.cb_platform = QComboBox()
        self._fill_platforms()
        if acc:
            i = self.cb_platform.findData(acc["platform"])
            if i >= 0:
                self.cb_platform.setCurrentIndex(i)
            self.cb_platform.setEnabled(False)
        elif platform_key:
            i = self.cb_platform.findData(platform_key)
            if i >= 0:
                self.cb_platform.setCurrentIndex(i)
        self.cb_platform.currentIndexChanged.connect(self._on_platform_changed)
        row.addWidget(_field("平台", self.cb_platform), 1)

        self.btn_edit_pf = IconButton("settings2", "编辑该平台", 30, 15)
        self.btn_edit_pf.clicked.connect(self._edit_platform)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 18, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self.btn_edit_pf)
        hl.addStretch(1)
        row.addWidget(holder, 0)

        self.ed_name = QLineEdit(acc["name"] if acc else "")
        self.ed_name.setPlaceholderText("例如：公考干货号 A")
        row.addWidget(_field("账号名称", self.ed_name), 2)
        body.addLayout(row)

        self.lb_pf_hint = QLabel("")
        self.lb_pf_hint.setObjectName("Hint")
        self.lb_pf_hint.setWordWrap(True)
        body.addWidget(self.lb_pf_hint)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.ed_nick = QLineEdit(acc.get("nickname", "") if acc else "")
        self.ed_nick.setPlaceholderText("平台上的显示昵称（选填）")
        row2.addWidget(_field("昵称", self.ed_nick), 1)

        self.ed_group = QLineEdit(acc.get("group", "") if acc else "")
        self.ed_group.setPlaceholderText("例如：省考项目 / 矩阵一")
        row2.addWidget(_field("分组", self.ed_group), 1)
        body.addLayout(row2)

        self.ed_persona = QLineEdit(acc.get("persona", "") if acc else "")
        self.ed_persona.setPlaceholderText("例如：深耕公考十年的教研老师（会注入 AI 提示）")
        body.addWidget(_field("账号人设", self.ed_persona,
                              "填了以后，内容工坊的「账号人设」下拉里就能直接选"))

        self.cb_status = QComboBox()
        for s in store.ACCOUNT_STATUS:
            self.cb_status.addItem(s, s)
        if acc:
            i = self.cb_status.findData(acc.get("status", "正常"))
            if i >= 0:
                self.cb_status.setCurrentIndex(i)
        body.addWidget(_field("状态", self.cb_status))

        self.ed_note = QPlainTextEdit(acc.get("note", "") if acc else "")
        self.ed_note.setPlaceholderText("备注（选填）")
        self.ed_note.setFixedHeight(64)
        body.addWidget(_field("备注", self.ed_note))

        self.add_stretch()
        self.add_button("取消", "Soft", self.reject)
        self.add_button("保存", "Primary", self._on_ok, default=True)

        self._on_platform_changed()

    # ---------------------------------------------------------- 平台
    def _fill_platforms(self):
        """填充平台下拉。最后一项固定是「＋ 新增平台…」。"""
        cur = getattr(self, "_last_key", None) or self.cb_platform.currentData()
        if cur == NEW_PLATFORM:
            cur = None
        self.cb_platform.blockSignals(True)
        self.cb_platform.clear()
        for p in PF.enabled_platforms():
            label = p["name"] + ("" if p.get("builtin") else "（自定义）")
            self.cb_platform.addItem(label, p["key"])
        self.cb_platform.insertSeparator(self.cb_platform.count())
        self.cb_platform.addItem("＋ 新增平台…", NEW_PLATFORM)
        if cur:
            i = self.cb_platform.findData(cur)
            if i >= 0:
                self.cb_platform.setCurrentIndex(i)
        self.cb_platform.blockSignals(False)

    def _select(self, key: str):
        i = self.cb_platform.findData(key)
        if i >= 0:
            self.cb_platform.setCurrentIndex(i)
        self._on_platform_changed()

    def _on_platform_changed(self):
        key = self.cb_platform.currentData()
        if key == NEW_PLATFORM:
            # 用户点了「新增平台」→ 立刻弹新建框
            self._new_platform()
            return
        self._last_key = key or ""
        p = PF.get(key) or {}
        if not key:
            self.lb_pf_hint.setText("")
        elif p.get("builtin"):
            self.lb_pf_hint.setText("内置平台，自带自动填充脚本。")
        else:
            self.lb_pf_hint.setText(
                f"自定义平台 · 发布页：{p.get('publish_url') or '（未填）'}")
        self.btn_edit_pf.setVisible(bool(key) and not p.get("builtin"))

    def _new_platform(self):
        from views.platform_dialog import PlatformDialog
        d = PlatformDialog(self.window())
        ok = d.exec()
        self._fill_platforms()
        if ok and d.result_key():
            self._select(d.result_key())
        else:
            self._select(getattr(self, "_last_key", ""))

    def _edit_platform(self):
        key = self.cb_platform.currentData()
        p = PF.get(key) or {}
        if not key or key == NEW_PLATFORM or p.get("builtin"):
            return
        from views.platform_dialog import PlatformDialog
        d = PlatformDialog(self.window(), key)
        if d.exec():
            self._fill_platforms()
            self._select(key)

    # ---------------------------------------------------------- 保存
    def _on_ok(self):
        name = self.ed_name.text().strip()
        if not name:
            MessageDialog.alert(self, "还差一点", "账号名称不能为空", "warn")
            return
        key = self.cb_platform.currentData()
        if not key or key == NEW_PLATFORM:
            MessageDialog.alert(self, "还差一点", "请先选择或新增一个平台", "warn")
            return
        fields = {
            "nickname": self.ed_nick.text().strip(),
            "group": self.ed_group.text().strip(),
            "persona": self.ed_persona.text().strip(),
            "status": self.cb_status.currentData(),
            "note": self.ed_note.toPlainText().strip(),
        }
        try:
            if self.aid:
                store.update_account(self.db, self.aid, dict(fields, name=name))
            else:
                store.add_account(self.db, key, name, **fields)
        except Exception as e:
            MessageDialog.alert(self, "保存失败", str(e), "err")
            return
        self.accept()
