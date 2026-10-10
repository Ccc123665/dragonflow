"""流水线输入表单：把 `Pipeline.inputs()` 渲染成控件，再把值读回来。

抽成公共模块是因为有两个地方要用同一套渲染逻辑：
  · 内容工坊 —— 能力面板上的内嵌表单（一次填完，直接跑）
  · 参数弹窗 —— 单独跑一条流水线时的独立对话框

两边如果各写一套，控件类型 / 默认值 / 必填校验很容易走偏，
最后表现成「弹窗里填得好好的，工坊里却读不到值」。
"""
from typing import Any, Dict, List

from PyQt6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QWidget

from theme import Switch

__all__ = ["make_input_editor", "read_values", "missing_required", "merge_inputs"]


def make_input_editor(inp, topic: str = "", prefill: str = "",
                      values: Dict[str, str] = None) -> QWidget:
    """按 Input 的 kind 造一个编辑控件。

    三种「带进来的值」，优先级从高到低：

      · values  —— {key: 值} 的**按 key 预填**。弹窗「上次填过什么」用这个，
                   命中就整份覆盖（包括用户手动清空的情况，值是 "" 也算命中）
      · topic   —— 工坊里输入的选题，灌进 key 为 topic / title 的框
      · prefill —— 上一段流水线产出的正文，灌进 key 为 text / body 的框

    ⚠ 为什么不把 prefill 一视同仁地灌给所有 textarea：pipeline 弹窗里
    prefill 是「上游产出的整篇正文」，全灌的话「补充要求」这种小框也会被塞满。
    所以老的两个参数保留「只给特定 key」的语义，新加 values 才是通用的。
    """
    given = (values or {}).get(inp.key)
    has_given = given is not None

    if inp.kind == "textarea":
        ed = QPlainTextEdit()
        ed.setPlaceholderText(inp.placeholder)
        ed.setFixedHeight(min(220, max(64, inp.rows * 24 + 20)))
        if has_given:
            ed.setPlainText(given)
        else:
            val = prefill if inp.key in ("text", "body") else ""
            ed.setPlainText(val or inp.default)
        return ed
    if inp.kind == "choice":
        cb = QComboBox()
        cb.addItems(inp.choices or [])
        target = given if has_given else inp.default
        if target in (inp.choices or []):
            cb.setCurrentText(target)
        return cb
    if inp.kind == "switch":
        raw = given if has_given else inp.default
        return Switch(checked=str(raw).lower() in ("1", "true", "yes", "on"))
    ed = QLineEdit()
    ed.setPlaceholderText(inp.placeholder)
    if has_given:
        ed.setText(given)
    else:
        ed.setText(topic if (inp.key in ("topic", "title") and topic) else inp.default)
    ed.setMinimumHeight(36)
    return ed


def read_values(inputs, editors: Dict[str, QWidget]) -> Dict[str, str]:
    """把控件里的值读成一个 {key: str} 字典。"""
    out: Dict[str, str] = {}
    for inp in inputs:
        w = editors.get(inp.key)
        if w is None:
            continue
        if isinstance(w, QPlainTextEdit):
            out[inp.key] = w.toPlainText().strip()
        elif isinstance(w, QComboBox):
            out[inp.key] = w.currentText().strip()
        elif isinstance(w, Switch):
            out[inp.key] = "1" if w.isChecked() else ""
        elif isinstance(w, QLineEdit):
            out[inp.key] = w.text().strip()
    return out


def missing_required(inputs, values: Dict[str, str]) -> str:
    """返回第一个没填的必填项标签（空串 = 都填了）。"""
    for inp in inputs:
        if inp.required and not values.get(inp.key):
            return inp.label
    return ""


def merge_inputs(input_groups: List[List[Any]]) -> List[Any]:
    """把多组输入合并成一组：**同 key 只留一个**。

    这是「一个输入喂多个能力」的关键 —— 勾了「公众号链接转图文」和
    「链接转口播视频」时，它们都要「公众号链接」，界面上就该只有一个输入框，
    而不是让用户填两遍。
    """
    out: List[Any] = []
    seen = set()
    for group in input_groups:
        for inp in group or []:
            if inp.key in seen:
                continue
            seen.add(inp.key)
            out.append(inp)
    return out
