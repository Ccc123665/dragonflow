"""矩阵分配：内容 × 账号 的分配与差异化。

解决的具体问题
  一个平台挂了 5 个账号，工坊只生成了 1 条内容 —— 5 个账号发一模一样的东西，
  平台很容易判成搬运 / 重复内容。这里可以：
    · 勾选哪几个账号参与本次填充（不用每次都去「目标账号」里翻）
    · 给同一平台的每个账号单独生成一份差异化版本（换标题 / 换开头 / 换话题）
  差异化版本存在草稿的 variants 里，填充时按账号取用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

import icons
import llm
import platforms as PF
import skills as SK
import store
import theme
from widgets.common import Badge, Pill
from widgets.dialogs import BaseDialog, MessageDialog

VAR_SYSTEM = (
    "你是新媒体内容编辑。任务是在不改变核心信息、结论和事实的前提下，"
    "把同一份内容改写成「同平台不同账号」的版本，避免平台判定为重复内容。"
    "只输出 JSON，不要解释。不使用「包过」「保过」「押题」「最」「第一」「100%」等违规词。"
)

VAR_PROMPT = """把下面这份内容改写成一个新版本，供同平台的另一个账号发布。

【平台】{platform}
【该账号人设】{persona}
【原内容（JSON）】
{content}

改写要求：
1. 标题必须重写：换个说法、换个钩子类型（原来是疑问就改成数字，原来是结论就改成场景），字数不超过 {title_max} 字。
2. 正文开头两段必须重写：换切入角度和第一句话，后面主体保留信息点，但措辞要换掉，不许整句照抄。
3. 话题标签重新组合：保留一部分，替换一部分，顺序打乱。
4. 封面文案换一个说法。
5. 核心信息、数字、结论一个字都不能改，也不能新增原文没有的内容。
6. 输出 JSON，字段与原文完全一致：{fields}

只输出这个 JSON。
"""


# ================================================================ 差异化线程
class VariantTask(QThread):
    step = pyqtSignal(int, int, str)
    done = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def __init__(self, jobs: List[Tuple[Any, Dict[str, Any], Dict[str, Any]]],
                 parent=None):
        """jobs: [(draft_item, account_dict, skill_dict), ...]"""
        super().__init__(parent)
        self.jobs = jobs
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        settings = store.load_settings()
        if not (settings.get("api_key") or "").strip():
            self.failed.emit("还没有配置 API Key，请先到「设置」里填写")
            return
        ok = 0
        errs: List[str] = []
        total = len(self.jobs)
        for i, (item, acc, skill) in enumerate(self.jobs, start=1):
            if self._stop:
                break
            self.step.emit(i, total, f"{PF.name_of(item.platform_key)}·{acc.get('name', '')}")
            try:
                fields = skill.get("fields") or list(item.content.keys())
                limits = skill.get("limits") or {}
                payload = {f: item.content.get(f, "") for f in fields}
                import json
                raw = llm.chat(
                    settings, VAR_SYSTEM,
                    VAR_PROMPT.format(
                        platform=PF.name_of(item.platform_key),
                        persona=acc.get("persona") or "（未设置，按平台惯例）",
                        content=json.dumps(payload, ensure_ascii=False, indent=1),
                        title_max=int(limits.get("title") or 20),
                        fields=", ".join(fields)),
                    max_tokens=3000, temperature=0.95)
                data = llm.extract_json(raw)
                if not data:
                    errs.append(f"{acc.get('name', '')}：模型没返回 JSON")
                    continue
                new = {}
                for f in fields:
                    if f in data:
                        new[f] = data[f]
                if not new.get("title") and not new.get("body"):
                    errs.append(f"{acc.get('name', '')}：改写结果为空")
                    continue
                item.variants[acc["id"]] = new
                ok += 1
            except Exception as e:
                errs.append(f"{acc.get('name', '')}：{e}")
        self.done.emit(ok, "；".join(errs[:3]))


# ================================================================ 弹窗
class MatrixDialog(BaseDialog):
    def __init__(self, parent, wb, items: List[Any], accounts: Dict[str, List[Dict]],
                 checked: set):
        super().__init__(
            parent, "矩阵分配",
            "一条内容 × 一个账号 = 一次填充。同一平台多个账号拿同一份内容容易被判重复，"
            "可以给每个账号单独生成差异化版本。",
            width=760)
        self.wb = wb
        self.items = items
        self.accounts = accounts
        # 一个都没勾过时（第一次进这个弹窗），默认全勾 —— 和「目标账号」
        # 里「新出现的账号默认勾上」保持一致
        if not checked:
            checked = {a["id"] for accs in accounts.values() for a in accs}
        self._sel: Dict[str, QCheckBox] = {}
        self._var: Dict[str, QCheckBox] = {}
        self._task: Optional[VariantTask] = None

        # ---- 概览
        head = QHBoxLayout()
        head.setSpacing(8)
        self.lb_count = QLabel("")
        self.lb_count.setObjectName("Muted")
        head.addWidget(self.lb_count)
        head.addStretch(1)
        self.btn_all = QPushButton("全选")
        self.btn_all.setObjectName("Ghost")
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none = QPushButton("全不选")
        self.btn_none.setObjectName("Ghost")
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        head.addWidget(self.btn_all)
        head.addWidget(self.btn_none)
        self.body.addLayout(head)

        self.sc = QScrollArea()
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QFrame.Shape.NoFrame)
        self.sc.setMinimumHeight(300)
        self.sc.setMaximumHeight(460)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 6, 0)
        bl.setSpacing(12)

        for it in items:
            accs = accounts.get(it.platform_key) or []
            bl.addWidget(self._platform_block(it, accs, checked))
        bl.addStretch(1)
        self.sc.setWidget(box)
        self.body.addWidget(self.sc, 1)

        # ---- 差异化执行区
        run = QHBoxLayout()
        run.setSpacing(8)
        self.btn_var = QPushButton("为勾选账号生成差异化版本")
        self.btn_var.setObjectName("Soft")
        self.btn_var.setIcon(icons.icon("sparkle", theme.TEXT_2, 14))
        self.btn_var.clicked.connect(self._make_variants)
        run.addWidget(self.btn_var)
        run.addStretch(1)
        self.lb_var = QLabel("")
        self.lb_var.setObjectName("Hint")
        run.addWidget(self.lb_var)
        self.body.addLayout(run)

        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.setFixedHeight(6)
        self.prog.setTextVisible(False)
        self.prog.setVisible(False)
        self.body.addWidget(self.prog)

        self.add_stretch()
        self.add_button("取消", "Soft", self.reject)
        self.add_button("确定", "Primary", self._ok, default=True)
        self._refresh_count()

    # ---------------------------------------------------------- 组装
    def _platform_block(self, item, accs: List[Dict], checked: set) -> QWidget:
        card = QWidget()
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(card, theme.BG_SUBTLE)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(8)
        nm = QLabel(PF.name_of(item.platform_key))
        nm.setStyleSheet(f"background:transparent;{theme.css_font(13.5, 600)}color:{theme.TEXT_1};")
        head.addWidget(nm)
        head.addWidget(Badge(str(len(accs))))
        head.addStretch(1)
        title = str(item.content.get("title") or item.topic or "（无标题）")[:34]
        t = QLabel(title)
        t.setStyleSheet(f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_3};")
        head.addWidget(t)
        lay.addLayout(head)

        if not accs:
            h = QLabel("这个平台还没有账号，先到左侧「账号矩阵」添加")
            h.setStyleSheet(f"background:transparent;{theme.css_font(12)}color:{theme.WARNING};")
            lay.addWidget(h)
            return card

        for a in accs:
            row = QHBoxLayout()
            row.setSpacing(10)
            cb = QCheckBox(f"{a.get('name', '')}    ·  {a.get('status', '正常')}")
            cb.setChecked(a["id"] in checked)
            cb.setProperty("_pk", item.platform_key)
            cb.setProperty("_aid", a["id"])
            cb.toggled.connect(lambda *_: self._refresh_count())
            self._sel[a["id"]] = cb
            row.addWidget(cb, 1)

            v = QCheckBox("差异化")
            v.setToolTip("为这个账号生成一份改写版本（换标题 / 换开头 / 换话题）")
            v.setChecked(item.has_variant(a["id"]))
            v.setProperty("_aid", a["id"])
            v.setEnabled(cb.isChecked())
            cb.toggled.connect(lambda on, w=v: w.setEnabled(on))
            self._var[a["id"]] = v
            row.addWidget(v)

            if item.has_variant(a["id"]):
                row.addWidget(Pill("已有版本", theme.SUCCESS, theme.SUCCESS_TINT))
            lay.addLayout(row)
        return card

    def _set_all(self, on: bool):
        for cb in self._sel.values():
            cb.setChecked(on)

    def _refresh_count(self):
        n = len(self.checked())
        rows = len([it for it in self.items if self.accounts.get(it.platform_key)])
        self.lb_count.setText(f"{rows} 条内容 · 已选 {n} 个账号 → 共 {n} 次填充")

    # ---------------------------------------------------------- 差异化
    def _jobs(self) -> List[Tuple[Any, Dict, Dict]]:
        out = []
        checked = self.checked()
        for it in self.items:
            accs = {a["id"]: a for a in (self.accounts.get(it.platform_key) or [])}
            skill = SK.get_skill(it.skill_id) or {"fields": list(it.content.keys())}
            for aid in checked:
                if aid not in accs:
                    continue
                v = self._var.get(aid)
                if v is None or not v.isChecked():
                    continue
                out.append((it, accs[aid], skill))
        return out

    def _make_variants(self):
        jobs = self._jobs()
        if not jobs:
            toast_msg = "先勾选账号，并给要差异化的账号打上「差异化」勾"
            MessageDialog.alert(self.window(), "没有需要生成的目标", toast_msg, kind="info")
            return
        ok = MessageDialog.confirm(
            self.window(), "生成差异化版本",
            f"将为 {len(jobs)} 个账号各生成一份改写版本。",
            kind="ask",
            detail="每个账号一次模型调用，账号多时耗时较长。改写只换说法，不改事实与数字。",
            ok_text="开始生成", cancel_text="取消")
        if not ok:
            return
        self.btn_var.setEnabled(False)
        self.prog.setVisible(True)
        self.prog.setRange(0, len(jobs))
        self.prog.setValue(0)
        self._task = VariantTask(jobs, self)
        self._task.step.connect(self._on_step)
        self._task.done.connect(self._on_done)
        self._task.failed.connect(self._on_fail)
        self._task.start()

    def _on_step(self, i: int, total: int, name: str):
        self.prog.setValue(i - 1)
        self.lb_var.setText(f"正在改写 {i}/{total}：{name}")

    def _on_done(self, n: int, errs: str):
        self.prog.setValue(self.prog.maximum())
        self.btn_var.setEnabled(True)
        self.lb_var.setText(f"已生成 {n} 个差异化版本" + (f"；失败：{errs}" if errs else ""))
        # 刷新「已有版本」标签
        self._rebuild_marks()

    def _on_fail(self, err: str):
        self.btn_var.setEnabled(True)
        self.prog.setVisible(False)
        self.lb_var.setText("")
        MessageDialog.alert(self.window(), "生成失败", err, kind="err")

    def _rebuild_marks(self):
        for it in self.items:
            for a in (self.accounts.get(it.platform_key) or []):
                v = self._var.get(a["id"])
                if v is not None and it.has_variant(a["id"]):
                    v.setChecked(True)

    # ---------------------------------------------------------- 结果
    def checked(self) -> set:
        return {aid for aid, cb in self._sel.items() if cb.isChecked()}

    def _ok(self):
        if not self.checked():
            MessageDialog.alert(self.window(), "没有选中账号",
                                "至少要勾选一个账号参与本次填充。", kind="warn")
            return
        self.accept()

    def closeEvent(self, ev):
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(4000)
        super().closeEvent(ev)
