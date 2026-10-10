"""流水线模板的参数弹窗 + 运行进度 + 结果预览。

prompt 型模板是「填选题 → 点生成」，参数只有一个选题；
pipeline 型模板要填链接、页数、音色等一堆参数，还要跑几十秒甚至几分钟，
所以单独给一个弹窗：填参数 → 看进度 → 看产物 → 采用到卡片。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import config
import icons
import store
import theme
from widgets.common import ArtifactStrip, Badge, Switch, open_dir, toast
from widgets.dialogs import BaseDialog, MessageDialog


# ================================================================ 运行线程
class PipelineTask(QThread):
    log = pyqtSignal(str)
    prog = pyqtSignal(float, str)
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, pipe, values: Dict[str, str], parent=None):
        super().__init__(parent)
        self.pipe = pipe
        self.values = dict(values)
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        from pipelines.base import Ctx
        try:
            out_dir = self.pipe.output_dir(self.values.get("title")
                                           or self.values.get("topic") or "output")
            ctx = Ctx(store.load_settings(), out_dir,
                      log=self.log.emit, progress=self.prog.emit,
                      cancelled=lambda: self._stop)
            result = self.pipe.run(self.values, ctx)
            if self._stop:
                return
            self.done.emit(result or {})
        except InterruptedError:
            return
        except Exception as e:
            if not self._stop:
                self.failed.emit(str(e))


# ================================================================ 输入控件
def _label(text: str, required: bool = False) -> QLabel:
    lb = QLabel(text + ("  *" if required else ""))
    lb.setObjectName("FieldLabel")
    return lb


def _hint(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("Hint")
    lb.setWordWrap(True)
    return lb


# ================================================================ 主弹窗
class PipelineDialog(BaseDialog):
    def __init__(self, parent, pipe, topic: str = "", prefill: str = ""):
        super().__init__(parent, pipe.name, pipe.desc, width=680)
        self.pipe = pipe
        self._result: Optional[Dict[str, Any]] = None
        self._task: Optional[PipelineTask] = None
        self._editors: Dict[str, QWidget] = {}
        self._running = False

        self.form = QWidget()
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(12)

        if getattr(pipe, "note", ""):
            note = QLabel(pipe.note)
            note.setWordWrap(True)
            note.setStyleSheet(
                f"background:{theme.PRIMARY_TINT};color:{theme.PRIMARY};"
                f"border-radius:8px;padding:9px 12px;{theme.css_font(12)}")
            fl.addWidget(note)

        for inp in pipe.inputs():
            fl.addWidget(_label(inp.label, inp.required))
            w = self._make_editor(inp, topic, prefill)
            self._editors[inp.key] = w
            fl.addWidget(w)
            if inp.help:
                fl.addWidget(_hint(inp.help))
        fl.addStretch(1)
        self.body.addWidget(self.form)

        # ---- 运行区（默认隐藏）
        self.run_box = QWidget()
        rl = QVBoxLayout(self.run_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.lb_stage = QLabel("准备中…")
        self.lb_stage.setObjectName("Muted")
        row.addWidget(self.lb_stage, 1)
        rl.addLayout(row)

        self.prog = QProgressBar()
        self.prog.setRange(0, 1000)
        self.prog.setValue(0)
        self.prog.setFixedHeight(8)
        self.prog.setTextVisible(False)
        rl.addWidget(self.prog)

        self.lb_log = QLabel("")
        self.lb_log.setObjectName("Hint")
        self.lb_log.setWordWrap(True)
        rl.addWidget(self.lb_log)

        self.result_box = QWidget()
        self.result_box.setVisible(False)
        self.result_lay = QVBoxLayout(self.result_box)
        self.result_lay.setContentsMargins(0, 0, 0, 0)
        self.result_lay.setSpacing(10)
        rl.addWidget(self.result_box)

        self.run_box.setVisible(False)
        self.body.addWidget(self.run_box)

        self.add_stretch()
        self.btn_cancel = self.add_button("取消", "Soft", self._on_cancel)
        self.btn_go = self.add_button("开始生成", "Primary", self._start, default=True)

    # ---------------------------------------------------------- 控件
    def _make_editor(self, inp, topic: str, prefill: str) -> QWidget:
        if inp.kind == "textarea":
            ed = QPlainTextEdit()
            ed.setPlaceholderText(inp.placeholder)
            ed.setFixedHeight(min(220, max(64, inp.rows * 24 + 20)))
            val = prefill if inp.key in ("text", "body") else ""
            ed.setPlainText(val or inp.default)
            return ed
        if inp.kind == "choice":
            cb = QComboBox()
            cb.addItems(inp.choices or [])
            if inp.default in (inp.choices or []):
                cb.setCurrentText(inp.default)
            return cb
        if inp.kind == "switch":
            return Switch(checked=str(inp.default).lower() in ("1", "true", "yes", "on"))
        ed = QLineEdit()
        ed.setPlaceholderText(inp.placeholder)
        ed.setText(topic if (inp.key in ("topic", "title") and topic) else inp.default)
        ed.setMinimumHeight(36)
        return ed

    def values(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for inp in self.pipe.inputs():
            w = self._editors.get(inp.key)
            if isinstance(w, QPlainTextEdit):
                out[inp.key] = w.toPlainText().strip()
            elif isinstance(w, QComboBox):
                out[inp.key] = w.currentText().strip()
            elif isinstance(w, Switch):
                out[inp.key] = "1" if w.isChecked() else ""
            elif isinstance(w, QLineEdit):
                out[inp.key] = w.text().strip()
        return out

    # ---------------------------------------------------------- 运行
    def _start(self):
        vals = self.values()
        for inp in self.pipe.inputs():
            if inp.required and not vals.get(inp.key):
                toast(self.window(), f"请填写「{inp.label}」", "warn")
                return
        self._running = True
        self.form.setVisible(False)
        self.run_box.setVisible(True)
        self.btn_go.setEnabled(False)
        self.btn_go.setText("生成中…")
        self.btn_cancel.setText("停止")
        self.prog.setValue(0)
        self._fit_to_screen()

        self._task = PipelineTask(self.pipe, vals, self)
        self._task.log.connect(self._on_log)
        self._task.prog.connect(self._on_prog)
        self._task.done.connect(self._on_done)
        self._task.failed.connect(self._on_fail)
        self._task.start()

    def _on_log(self, msg: str):
        self.lb_log.setText(msg)

    def _on_prog(self, pct: float, msg: str):
        self.prog.setValue(int(max(0.0, min(1.0, pct)) * 1000))
        if msg:
            self.lb_stage.setText(msg)

    def _on_done(self, result: Dict[str, Any]):
        self._result = result
        self._running = False
        self.prog.setValue(1000)
        self.lb_stage.setText("完成")
        self.btn_go.setEnabled(True)
        self.btn_go.setText("采用这份内容")
        try:
            self.btn_go.clicked.disconnect()
        except Exception:
            pass
        self.btn_go.clicked.connect(self._adopt)
        self.btn_cancel.setText("放弃")
        self._show_artifacts(result)
        self._fit_to_screen()

    def _on_fail(self, err: str):
        self._running = False
        self.lb_stage.setText("失败")
        self.btn_go.setEnabled(True)
        self.btn_go.setText("重试")
        self.btn_cancel.setText("取消")
        try:
            self.btn_go.clicked.disconnect()
        except Exception:
            pass
        self.btn_go.clicked.connect(self._start)
        store.log(f"pipeline {self.pipe.key} 失败：{err}")
        MessageDialog.alert(self.window(), "生成失败", err, kind="err")

    def _show_artifacts(self, result: Dict[str, Any]):
        theme.clear_layout(self.result_lay)
        files = [p for p in (result.get("_artifacts") or []) if os.path.exists(p)]
        if files:
            head = QHBoxLayout()
            head.setSpacing(8)
            t = QLabel("产出文件")
            t.setObjectName("FieldLabel")
            head.addWidget(t)
            head.addWidget(Badge(str(len(files))))
            head.addStretch(1)
            b = QPushButton("打开目录")
            b.setObjectName("Ghost")
            b.clicked.connect(lambda _=False, p=files[0]: open_dir(os.path.dirname(p)))
            head.addWidget(b)
            self.result_lay.addLayout(head)

            strip = ArtifactStrip(files)
            self.result_lay.addWidget(strip)
        self.result_box.setVisible(True)

    def _adopt(self):
        self.accept()

    def _on_cancel(self):
        if self._running and self._task is not None:
            self._task.cancel()
            self.lb_stage.setText("正在停止…")
            self.btn_cancel.setEnabled(False)
            return
        self.reject()

    def result(self) -> Dict[str, Any]:
        return self._result or {}

    def closeEvent(self, ev):
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(4000)
        super().closeEvent(ev)
