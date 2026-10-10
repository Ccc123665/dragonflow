"""Skill 模板编辑对话框。"""
from typing import Any, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

import platforms as PF
import store
import theme
from widgets.dialogs import BaseDialog, MessageDialog

PLACEHOLDERS = (
    "{topic} 选题　{persona} 人设　{audience} 人群　{hook} 钩子　"
    "{tone} 语气　{case} 素材角度　{cta} 结尾引导　{extra} 补充要求"
)


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


class SkillDialog(BaseDialog):
    def __init__(self, parent=None, skill: Dict[str, Any] = None):
        self.skill = dict(skill or {})
        self.is_new = not self.skill.get("id")
        title = "新建 Skill 模板" if self.is_new else f"编辑模板 · {self.skill.get('name','')}"
        super().__init__(parent, title, "改完点「保存」生效。内置模板的修改只存在本机，不会覆盖内置文件。",
                         width=700, height=680)

        body = self.body

        # 名称 / 平台 / 形态 / 字段
        row = QHBoxLayout()
        row.setSpacing(12)
        self.ed_name = QLineEdit(self.skill.get("name", ""))
        self.ed_name.setPlaceholderText("例如：小红书爆款笔记")
        row.addWidget(_field("名称", self.ed_name), 2)

        self.cb_platform = QComboBox()
        for p in PF.enabled_platforms():
            self.cb_platform.addItem(p["name"], p["key"])
        i = self.cb_platform.findData(self.skill.get("platform", "xhs"))
        if i >= 0:
            self.cb_platform.setCurrentIndex(i)
        row.addWidget(_field("所属平台", self.cb_platform), 1)

        self.ed_type = QLineEdit(self.skill.get("content_type", "图文"))
        row.addWidget(_field("内容形态", self.ed_type), 1)
        body.addLayout(row)

        self.ed_desc = QLineEdit(self.skill.get("desc", ""))
        self.ed_desc.setPlaceholderText("一句话说明这个模板产出什么")
        body.addWidget(_field("说明", self.ed_desc))

        self.ed_fields = QLineEdit(
            ",".join(self.skill.get("fields") or ["title", "body", "topics"]))
        self.ed_fields.setPlaceholderText("title,body,topics")
        body.addWidget(_field(
            "输出字段", self.ed_fields,
            "可选：title 标题 / body 正文 / topics 话题 / cover 封面文案 / "
            "image_hint 配图建议 / hook 开头钩子 / cta 结尾引导 / digest 摘要"))

        self.ed_system = QPlainTextEdit(self.skill.get("system", ""))
        self.ed_system.setFixedHeight(96)
        self.ed_system.setPlaceholderText("定义角色与红线，例如：你是教育培训行业的小红书内容编辑…")
        body.addWidget(_field("System 提示（角色与红线）", self.ed_system))

        self.ed_prompt = QPlainTextEdit(self.skill.get("prompt", ""))
        self.ed_prompt.setMinimumHeight(160)
        self.ed_prompt.setPlaceholderText(
            "围绕选题「{topic}」写一篇…\n\n可用占位符：" + PLACEHOLDERS)
        body.addWidget(_field("Prompt 模板（核心）", self.ed_prompt,
                              "可用占位符：" + PLACEHOLDERS), 1)

        if not self.is_new and self.skill.get("builtin"):
            self.add_button("恢复出厂内容", "Soft", self._reset)
        self.add_stretch()
        self.add_button("取消", "Soft", self.reject)
        self.add_button("保存", "Primary", self._on_ok, default=True)

    def _reset(self):
        import skills as SK
        sid = self.skill.get("id")
        SK.reset_skill(sid)
        fresh = SK.get_skill(sid)
        if fresh:
            self.ed_name.setText(fresh.get("name", ""))
            self.ed_desc.setText(fresh.get("desc", ""))
            self.ed_fields.setText(",".join(fresh.get("fields") or []))
            self.ed_system.setPlainText(fresh.get("system", ""))
            self.ed_prompt.setPlainText(fresh.get("prompt", ""))
            from widgets.common import toast
            toast(self, "已恢复出厂内容，点保存生效", "ok")

    def _on_ok(self):
        name = self.ed_name.text().strip()
        if not name:
            MessageDialog.alert(self, "还差一点", "模板名称不能为空", "warn")
            return
        if not self.ed_prompt.toPlainText().strip():
            MessageDialog.alert(self, "还差一点", "Prompt 模板不能为空", "warn")
            return
        import skills as SK
        skill = dict(self.skill)
        skill.update({
            "name": name,
            "platform": self.cb_platform.currentData(),
            "content_type": self.ed_type.text().strip(),
            "desc": self.ed_desc.text().strip(),
            "fields": [f.strip() for f in self.ed_fields.text().split(",") if f.strip()],
            "system": self.ed_system.toPlainText().strip(),
            "prompt": self.ed_prompt.toPlainText().strip(),
        })
        if self.is_new:
            skill["builtin"] = False
            skill["locked"] = False
        SK.upsert_skill(skill)
        self.accept()
