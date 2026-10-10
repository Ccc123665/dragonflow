"""内容工坊：选能力 → 填输入（弹窗）→ 生成。

工作逻辑（v1.4）
  页面只做两件事，输入收进弹窗：

    ① 用**下拉**选能力 —— 可以多选，选中的能力以胶囊列在下面。
       下拉里每一项只写「名称 · 形态 · 平台」，详细说明放 tooltip ——
       不把每条能力铺成一张大卡片（十几条就是满满一屏）。
    ② 点「填写输入」开弹窗，把所选能力需要的输入一次填完。
       多个能力**共用的输入只出现一次**，填一次两边都用。
    ③ 生成 —— 进度就地显示，产出按能力分卡片。

能力从哪来（见 skills.STUDIO_KINDS）
  工坊只列**「真能干活的」**形态：
    · bundle   —— 从「设置 → 内容模板 Skill」整包导入的 SKILL.md 方法论
    · pipeline —— 多步骤流水线：抓网页 / 出图 / 渲染视频（那三条内置流水线）
  不列 `prompt`（单次模型调用型模板）—— 用户明确说「只要 skill，不要其他内置」，
  那 6 个 prompt 模板是随软件发的基础样板，只产文字、干不了实事，
  不占工坊的位置。它们仍然都在设置里可查看 / 停用 / 编辑 / 恢复。
  要放开只需改 skills.STUDIO_KINDS 这一个元组。

视觉（v1.3 重做 → v1.4 精简）
  v1.3 是「能力实体卡片列表 + 页内输入表单」，用户反馈「不用把所有能力都
  详细列出来」+「填写输入改成弹窗」。v1.4 因此把页面压到三块：
  一块 hero、一块「选能力 + 填输入」操作卡、一条生成动作条，下面是结果区。
"""
from typing import Any, Dict, List, Optional, Tuple
import time

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

import bus as BUSMOD
import config
import icons
import llm
import platforms as PF
import skills as SK
import store
import theme
from bus import BUS, Batch, DraftItem
from widgets.common import Card, EmptyState, toast
from widgets.content_card import ContentCard
from widgets.dialogs import BaseDialog
from widgets.pipeline_form import make_input_editor, merge_inputs, missing_required, read_values


# ================================================================ 小组件
def _chip(text: str, on: bool = False) -> QLabel:
    """结果区头部的小标签（「N 项」）。"""
    lb = QLabel(text)
    lb.setObjectName("MetaChip")
    lb.setProperty("on", bool(on))
    return lb


def _rgba(color: str, alpha: float) -> str:
    """把 "#2C6BE8" 变成 "rgba(44,107,232,0.10)"。

    Qt 的 QSS **不认 8 位 hex**（`#RRGGBBAA`）—— 它会按 `#AARRGGBB` 解析，
    颜色会整个错掉。带透明度一律用 rgba()。
    """
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:g})"


def _step_badge(num: str) -> QLabel:
    lb = QLabel(num)
    lb.setObjectName("StepBadge")
    lb.setFixedSize(22, 22)
    lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lb


def _step_head(card: Card, num: str, title: str, note: str = "") -> QHBoxLayout:
    """给步骤卡加一行头：编号徽标 + 标题 +（可选）说明。

    返回这行布局，调用方可以再往里 addWidget 右侧的动作按钮 ——
    头里已经 addStretch(1)，后加的会自然靠右。
    """
    head = QHBoxLayout()
    head.setSpacing(9)
    head.addWidget(_step_badge(num), 0, Qt.AlignmentFlag.AlignVCenter)
    t = QLabel(title)
    t.setObjectName("StepTitle")
    head.addWidget(t, 0, Qt.AlignmentFlag.AlignVCenter)
    if note:
        n = QLabel(note)
        n.setObjectName("StepNote")
        head.addWidget(n, 0, Qt.AlignmentFlag.AlignVCenter)
    head.addStretch(1)
    card.body.addLayout(head)
    return head


def _open_path(path: str):
    import os
    import subprocess
    import sys
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)          # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _ability_label(skill: Dict[str, Any]) -> str:
    """下拉里一行显示什么：名称 · 形态 · 平台（一行装下，不铺描述）。

    已选 / 不可用的标记**不走文字**：勾选标记用 item icon（`setItemIcon`），
    不可用只加一个「（不可用）」后缀 —— 试过用「✓」字符打头，
    在字体不全的环境里直接渲染成豆腐块（口）。
    """
    parts = [str(skill.get("name") or "")]
    ct = (skill.get("content_type") or "").strip()
    if ct:
        parts.append(ct)
    pk = skill.get("platform") or ""
    if pk:
        parts.append(PF.name_of(pk))
    txt = parts[0] + ("　·　" + "　·　".join(parts[1:]) if len(parts) > 1 else "")
    if not SK.can_run(skill):
        txt += "　（不可用）"
    return txt


def _ability_tip(skill: Dict[str, Any]) -> str:
    """下拉项的悬浮说明：把原来卡片上那两行（描述 / 要填会得到）搬过来。"""
    lines: List[str] = []
    if SK.can_run(skill):
        if skill.get("desc"):
            lines.append(str(skill["desc"]))
    else:
        errs = [i["text"] for i in SK.check_skill(skill) if i["level"] == "err"]
        lines.append("不可用：" + (errs[0] if errs else "这个能力跑不起来"))
    ins = SK.inputs_of(skill)
    outs = SK.outputs_of(skill)
    lines.append("要填　" + ("、".join(i.label for i in ins) if ins else "无"))
    lines.append("会得到　" + ("、".join(outs) or "—"))
    return "\n".join(lines)


# ================================================================ 已选能力胶囊
class PickedChip(QFrame):
    """一个已选能力的小胶囊：平台色点 + 名称 + ×。

    点 × 就把它从「这次要跑的能力」里摘掉 —— 比回到下拉里再取消勾选直观。
    """

    removed = pyqtSignal(str)

    def __init__(self, skill: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.sid = str(skill.get("id") or "")
        self.setObjectName("PickedChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("off", not SK.can_run(skill))
        self.setToolTip(_ability_tip(skill))

        h = QHBoxLayout(self)
        h.setContentsMargins(10, 2, 4, 2)
        h.setSpacing(6)

        pk = skill.get("platform") or ""
        if pk:
            dot = QLabel()
            dot.setFixedSize(7, 7)
            dot.setStyleSheet(
                f"background:{PF.color_of(pk)};border-radius:3px;")
            dot.setToolTip(PF.name_of(pk))
            h.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        lb = QLabel(str(skill.get("name") or ""))
        lb.setObjectName("PickedChipName")
        h.addWidget(lb, 0, Qt.AlignmentFlag.AlignVCenter)

        btn = QPushButton()
        btn.setFixedSize(18, 18)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIcon(icons.icon("close", theme.PRIMARY, 10, 2.2))
        btn.setIconSize(QSize(10, 10))
        btn.setToolTip("从这次要跑的能力里移除")
        btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:9px;padding:0;}"
            f"QPushButton:hover{{background:{_rgba(theme.PRIMARY, 0.16)};}}")
        btn.clicked.connect(lambda: self.removed.emit(self.sid))
        h.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)


# ================================================================ 填写输入弹窗
def _inputs_subtitle(skills: List[Dict[str, Any]]) -> str:
    if len(skills) <= 1:
        return "填好点「保存」，回到工坊点「开始生成」"
    return f"这些输入会同时喂给 {len(skills)} 个能力，共用的只需填一次"


class InputsDialog(BaseDialog):
    """填写输入弹窗。

    为什么收进弹窗：流水线动辄七八项输入（链接 / 分镜数 / 音色 / 背景音乐…），
    直接铺在工坊页面上会把页面顶得很长，能力和输入离得远、看不清对应关系。
    收进弹窗后主页面只剩「要填什么、还差什么」，一次专心填完。
    """

    def __init__(self, parent, skills: List[Dict[str, Any]],
                 values: Optional[Dict[str, str]] = None, width: int = 620):
        super().__init__(parent, "填写输入", _inputs_subtitle(skills), width=width)
        self.skills = list(skills or [])
        self._inputs = merge_inputs([SK.inputs_of(s) for s in self.skills])
        self.editors: Dict[str, QWidget] = {}
        keep = dict(values or {})

        if not self._inputs:
            lb = QLabel("这个能力不需要额外输入，直接点「开始生成」就行。")
            lb.setObjectName("Muted")
            lb.setWordWrap(True)
            self.body.addWidget(lb)

        for inp in self._inputs:
            self.body.addWidget(self._field_panel(inp, keep))

        self.add_stretch()
        self.add_button("取消", "Soft", self.reject)
        self.add_button("保存", "Primary", self._save, default=True)

    # ---------------------------------------------------------- 控件
    _FIELD_ICON = {"textarea": "list", "text": "edit",
                   "choice": "target", "switch": "check"}

    def _field_panel(self, inp, values: Dict[str, str]) -> QFrame:
        panel = QFrame()
        panel.setObjectName("FieldPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setProperty("req", bool(inp.required))
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 13)
        pl.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        ic = QLabel()
        ic.setFixedSize(18, 18)
        ic.setPixmap(icons.icon(self._FIELD_ICON.get(inp.kind, "edit"),
                                theme.PRIMARY if inp.required else theme.TEXT_3,
                                16).pixmap(16, 16))
        head.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)

        lb = QLabel(inp.label)
        lb.setObjectName("FieldLabelStrong")
        head.addWidget(lb, 0, Qt.AlignmentFlag.AlignVCenter)
        if inp.required:
            req = QLabel("必填")
            req.setObjectName("ReqPill")
            head.addWidget(req, 0, Qt.AlignmentFlag.AlignVCenter)
        if inp.help:
            h = QLabel(inp.help)
            h.setObjectName("StepNote")
            h.setWordWrap(True)
            head.addWidget(h, 1)
        head.addStretch(0)
        pl.addLayout(head)

        ed = make_input_editor(inp, values=values)
        self.editors[inp.key] = ed
        pl.addWidget(ed)
        return panel

    # ---------------------------------------------------------- 取值
    def values(self) -> Dict[str, str]:
        return read_values(self._inputs, self.editors)

    def _save(self):
        lack = missing_required(self._inputs, self.values())
        if lack:
            toast(self.window(), f"请填写「{lack}」", "warn")
            return
        self.accept()


# ================================================================ 工坊
class StudioView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: Dict[str, ContentCard] = {}      # key = skill id
        self._picked: List[str] = []                  # 选中的 skill id（保序）
        self._picked_init = False                     # 是否已经自动选过默认能力
        self._input_values: Dict[str, str] = {}       # 输入值（弹窗保存后落在这里）
        self._editors: Dict[str, QWidget] = {}        # 输入控件，只在弹窗打开期间有值
        self._jobs: List[Dict[str, Any]] = []         # 待跑的能力
        self._task: Optional[llm.GenerateTask] = None
        self._pipe_task = None
        self._slots_used: Dict[str, Dict[str, str]] = {}
        self._picked_chips: Dict[str, PickedChip] = {}
        self._cur_skill: Dict[str, Any] = {}          # 正在跑的能力（进度展示用）
        self._run_t0 = 0.0                            # 本轮生成开始时刻
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        page = theme.PageScroll(max_width=1120, top=20, bottom=28, spacing=16)
        root.addWidget(page)
        lay = page.body

        # ---------------- 页头 hero
        lay.addWidget(self._build_hero())

        # ---------------- ① 选能力 + 填输入（一块卡装完，页面才短）
        card1, head1 = self._step_card("1", "选择能力与输入", "可多选，共用的输入只填一次")
        self.lb_ability_count = QLabel("")
        self.lb_ability_count.setObjectName("StepNote")
        head1.addWidget(self.lb_ability_count)
        self.btn_manage = QPushButton("管理 / 上传能力")
        self.btn_manage.setObjectName("Soft")
        self.btn_manage.setIcon(icons.icon("upload", theme.TEXT_2, 14))
        self.btn_manage.setToolTip(
            "到「设置 → 内容模板 Skill」上传文件夹 / 压缩包，或编辑已有能力")
        self.btn_manage.clicked.connect(lambda: BUS.goto_settings.emit("skills"))
        head1.addWidget(self.btn_manage)
        lay.addWidget(card1)

        self.picker_box = QWidget()
        pb = QVBoxLayout(self.picker_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(10)

        # 能力下拉（选一条加一条；选项里只有「名称 · 形态 · 平台」，说明在 tooltip）
        row = QHBoxLayout()
        row.setSpacing(9)
        lb = QLabel("能力")
        lb.setObjectName("SectionLabel")
        lb.setFixedWidth(34)
        row.addWidget(lb, 0, Qt.AlignmentFlag.AlignVCenter)

        self.combo = QComboBox()
        self.combo.setObjectName("AbilityCombo")
        self.combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo.setMinimumWidth(320)
        self.combo.setIconSize(QSize(13, 13))
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # currentIndex 复位到 -1 时显示这句 —— 否则选完一条下拉就是一片空白
        self.combo.setPlaceholderText("＋　从下拉里挑一个能力…")
        self.combo.activated.connect(self._on_combo_activated)
        row.addWidget(self.combo, 1)

        self.btn_add = QPushButton("添加")
        self.btn_add.setObjectName("Soft")
        self.btn_add.setMinimumHeight(34)
        self.btn_add.setIcon(icons.icon("plus", theme.TEXT_2, 14))
        self.btn_add.setToolTip("把下拉里选中的能力加进这次要跑的清单")
        self.btn_add.clicked.connect(
            lambda: self._on_combo_activated(self.combo.currentIndex()))
        row.addWidget(self.btn_add, 0)
        pb.addLayout(row)

        # 已选能力：一排小胶囊，点 × 摘掉
        self.picked_box = QWidget()
        self.picked_lay = theme.FlowLayout(self.picked_box, margin=0, h_gap=8, v_gap=8)
        pb.addWidget(self.picked_box)

        self.no_pick_hint = QLabel("还没选 —— 从上面的下拉里挑一个，可以多选")
        self.no_pick_hint.setObjectName("StepNote")
        pb.addWidget(self.no_pick_hint)

        card1.body.addWidget(self.picker_box)

        # 一条能力都没有时的引导面板。内置流水线一直在，正常走不到这里；
        # 只有把内置能力也全删 / 停用了才会出现 —— 但面板留着。
        self.no_skill_panel = self._build_no_skill()
        card1.body.addWidget(self.no_skill_panel)

        # 输入摘要 + 「填写输入」（表单在弹窗里）
        line = QFrame()
        line.setObjectName("Sunk")
        line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lh = QHBoxLayout(line)
        lh.setContentsMargins(12, 8, 10, 8)
        lh.setSpacing(10)

        self.lb_input_summary = QLabel("")
        self.lb_input_summary.setObjectName("InputSummary")
        self.lb_input_summary.setWordWrap(True)
        lh.addWidget(self.lb_input_summary, 1)

        self.btn_fill = QPushButton("填写输入 →")
        self.btn_fill.setObjectName("Primary")
        self.btn_fill.setMinimumHeight(32)
        self.btn_fill.setIcon(icons.icon("edit", "#FFFFFF", 14))
        self.btn_fill.setToolTip("打开弹窗，把所选能力需要的输入一次填完")
        self.btn_fill.clicked.connect(self._open_inputs)
        lh.addWidget(self.btn_fill, 0)
        card1.body.addWidget(line)

        # ---------------- ② 生成（动作条）
        lay.addWidget(self._build_action_bar())

        # ---------------- 结果
        lay.addLayout(self._build_result_head())

        self.cards_box = QWidget()
        self.cards_lay = QGridLayout(self.cards_box)
        self.cards_lay.setContentsMargins(0, 0, 0, 0)
        self.cards_lay.setHorizontalSpacing(12)
        self.cards_lay.setVerticalSpacing(12)
        lay.addWidget(self.cards_box)

        self.empty = EmptyState("还没有产出", "在上面选一个能力、填好输入，点「开始生成」", "sparkle")
        self.cards_lay.addWidget(self.empty, 0, 0, 1, 2)

        lay.addStretch(1)

        BUS.settings_changed.connect(self._rebuild_abilities)
        self._rebuild_abilities()

    # ============================================================ 视觉构件
    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("StudioHero")
        hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(hero)
        h.setContentsMargins(20, 14, 20, 14)
        h.setSpacing(14)

        mark = QLabel()
        mark.setObjectName("EmptyStudioIcon")
        mark.setFixedSize(40, 40)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(icons.icon("studio", theme.PRIMARY, 20).pixmap(20, 20))
        h.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)

        t = QLabel("内容工坊")
        t.setObjectName("StudioHeroTitle")
        h.addWidget(t, 0, Qt.AlignmentFlag.AlignVCenter)

        self.lb_hero_stat = QLabel("")
        self.lb_hero_stat.setObjectName("StudioHeroStat")
        self.lb_hero_stat.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.lb_hero_stat, 1, Qt.AlignmentFlag.AlignVCenter)
        return hero

    def _step_card(self, num: str, title: str, note: str = "") -> Tuple[Card, QHBoxLayout]:
        card = Card(padding=18, spacing=13)
        card.setObjectName("StepCard")
        head = _step_head(card, num, title, note)
        return card, head

    def _build_no_skill(self) -> QFrame:
        """一条可用能力都没有时的引导（都被停用 / 删掉了才会走到这）。"""
        panel = QFrame()
        panel.setObjectName("EmptyStudio")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        v = QVBoxLayout(panel)
        v.setContentsMargins(24, 26, 24, 26)
        v.setSpacing(10)

        ic = QLabel()
        ic.setObjectName("EmptyStudioIcon")
        ic.setFixedSize(46, 46)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(icons.icon("upload", theme.PRIMARY, 22).pixmap(22, 22))
        v.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)

        t = QLabel("还没有可用能力")
        t.setObjectName("EmptyStudioTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)

        self.lb_no_ability = QLabel(
            "工坊只列能真正干活的能力：你导入的 Skill 包，以及抓取 / 出图 / "
            "渲染视频这类流水线。现在一条都没有 —— 可能是被停用或删掉了，"
            "到「设置 → 内容模板 Skill」点「恢复内置」找回，或上传自己的 Skill 包。")
        self.lb_no_ability.setObjectName("Muted")
        self.lb_no_ability.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lb_no_ability.setWordWrap(True)
        v.addWidget(self.lb_no_ability)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        b_open = QPushButton("打开 Skill 目录")
        b_open.setObjectName("Soft")
        b_open.setIcon(icons.icon("folder", theme.TEXT_2, 14))
        b_open.clicked.connect(lambda: _open_path(config.SKILLS_DIR))
        row.addWidget(b_open)
        b_up = QPushButton("去上传 Skill 包")
        b_up.setObjectName("Primary")
        b_up.setIcon(icons.icon("upload", "#FFFFFF", 14))
        b_up.clicked.connect(lambda: BUS.goto_settings.emit("skills"))
        row.addWidget(b_up)
        row.addStretch(1)
        v.addLayout(row)
        return panel

    def _build_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("ActionBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 14, 16, 14)
        h.setSpacing(12)

        ic = QLabel()
        ic.setFixedSize(20, 20)
        ic.setPixmap(icons.icon("sparkle", theme.PRIMARY, 18).pixmap(18, 18))
        h.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)

        self.lb_progress = QLabel("准备好就开跑")
        self.lb_progress.setObjectName("Muted")
        self.lb_progress.setWordWrap(True)
        h.addWidget(self.lb_progress, 1)

        # 生成等待可视化：进度条（拿不到百分比时转不确定圈）+ 已用/约剩时间
        self.bar_progress = QProgressBar()
        self.bar_progress.setTextVisible(False)
        self.bar_progress.setFixedWidth(190)
        self.bar_progress.setFixedHeight(7)
        self.bar_progress.setRange(0, 0)
        self.bar_progress.hide()
        h.addWidget(self.bar_progress, 0, Qt.AlignmentFlag.AlignVCenter)

        self.lb_elapsed = QLabel("")
        self.lb_elapsed.setObjectName("Muted")
        self.lb_elapsed.hide()
        h.addWidget(self.lb_elapsed, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_gen = QPushButton("开始生成")
        self.btn_gen.setObjectName("Primary")
        self.btn_gen.setIcon(icons.icon("sparkle", "#FFFFFF", 15))
        self.btn_gen.setMinimumWidth(148)
        self.btn_gen.setMinimumHeight(36)
        self.btn_gen.clicked.connect(self._start)
        h.addWidget(self.btn_gen, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _build_result_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(8)
        lb = QLabel("生成结果")
        lb.setObjectName("PanelHead")
        head.addWidget(lb)
        self.lb_result_count = _chip("0 项")
        head.addWidget(self.lb_result_count)
        head.addStretch(1)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.clicked.connect(self._clear)
        head.addWidget(self.btn_clear)
        self.btn_check_all = QPushButton("全部体检")
        self.btn_check_all.setObjectName("Ghost")
        self.btn_check_all.setIcon(icons.icon("check", theme.PRIMARY, 14))
        self.btn_check_all.setToolTip("对全部产出跑一遍发布前体检（长度 / 必填 / 引流 / 排版 / 词库）")
        self.btn_check_all.clicked.connect(self._check_all)
        head.addWidget(self.btn_check_all)
        self.btn_to_workbench = QPushButton("去发布 →")
        self.btn_to_workbench.setObjectName("Primary")
        self.btn_to_workbench.setToolTip("把这里生成的内容同步到发布工作台，并跳过去")
        self.btn_to_workbench.clicked.connect(self._push_and_go)
        head.addWidget(self.btn_to_workbench)
        return head

    # ============================================================ ① 能力清单
    def _all_abilities(self) -> List[Dict[str, Any]]:
        """工坊能选的能力：Skill 包 + 流水线（见 skills.STUDIO_KINDS）。

        排序：能跑的在前、流水线优先（它们是真会抓取 / 出图 / 渲染的那批），
        跑不起来的垫底 —— 但**都列出来**，只是置灰 + 选不动。
        直接藏掉的话，用户会以为「我明明上传了，怎么找不到」。
        """
        items = list(SK.studio_skills())
        return sorted(items, key=lambda s: (
            0 if (SK.can_run(s) and SK.is_pipeline(s)) else
            1 if SK.can_run(s) else 2,
            s.get("name", "")))

    def _rebuild_abilities(self):
        """能力清单变了（上传 / 停用 / 设置改动）→ 全部重刷。"""
        usable = {s["id"] for s in self._all_abilities() if SK.can_run(s)}
        # 之前选的能力如果没了（被删 / 被停用 / 变得不可用），要摘掉
        self._picked = [i for i in self._picked if i in usable]
        if not self._picked and not self._picked_init:
            # 首次进来默认选上第一条能跑的能力（流水线优先）
            self._picked = [s["id"] for s in self._all_abilities() if SK.can_run(s)][:1]
        self._picked_init = True

        self._rebuild_combo()
        self._rebuild_chips()
        self._update_count()
        self._refresh_input_summary()

        total = len(self._all_abilities())
        self.picker_box.setVisible(total > 0)
        self.no_skill_panel.setVisible(total == 0)

    def _rebuild_combo(self):
        """下拉里放全部能力，一项一行。

        不可用的项在 model 里 `setEnabled(False)` —— 点不动、加不进来，
        而不是藏掉（藏掉用户会以为「没上传成功」）。
        """
        self.combo.blockSignals(True)
        self.combo.clear()
        for s in self._all_abilities():
            self.combo.addItem(_ability_label(s), s["id"])
            idx = self.combo.count() - 1
            item = self.combo.model().item(idx)
            if item is not None:
                item.setEnabled(SK.can_run(s))
            if s["id"] in self._picked:
                self.combo.setItemIcon(idx, icons.icon("check", theme.PRIMARY, 13, 2.2))
            self.combo.setItemData(idx, _ability_tip(s), Qt.ItemDataRole.ToolTipRole)
        # 复位到占位提示：加完一条就清空，方便连着加下一条
        self.combo.setCurrentIndex(-1)
        self.combo.blockSignals(False)
        try:
            self.combo.view().setMinimumWidth(430)
        except Exception:
            pass

    def _combo_ids(self) -> List[str]:
        """下拉里的能力 id，顺序同界面（分组标题没有 id，返回空串已滤掉）。"""
        return [str(self.combo.itemData(i) or "")
                for i in range(self.combo.count())
                if self.combo.itemData(i)]

    def _rebuild_chips(self):
        theme.clear_layout(self.picked_lay)
        self._picked_chips.clear()
        for sid in self._picked:
            s = SK.get_skill(sid)
            if not s:
                continue
            c = PickedChip(s)
            c.removed.connect(self._remove_ability)
            self._picked_chips[sid] = c
            self.picked_lay.addWidget(c)
        self.no_pick_hint.setVisible(not self._picked)

    def _on_combo_activated(self, idx: int):
        """下拉里选中一条 → 直接加进来（不用再点一次确认）。"""
        sid = self.combo.itemData(idx)
        if sid:
            self._add_ability(str(sid))
        self.combo.setCurrentIndex(-1)

    def _add_ability(self, sid: str) -> bool:
        skill = SK.get_skill(sid) or {}
        if not skill:
            return False
        if not SK.can_run(skill):
            # 不可用的能力不允许加 —— 加了也是白跑一趟
            toast(self.window(),
                  f"「{skill.get('name', '')}」跑不起来 —— 到「设置 → 内容模板 Skill」"
                  f"点「自检」看具体原因", "err", 5200)
            return False
        if sid in self._picked:
            toast(self.window(), f"「{skill.get('name', '')}」已经在清单里了", "info", 2000)
            return False
        self._picked.append(sid)
        self._rebuild_abilities()
        return True

    def _remove_ability(self, sid: str):
        if sid in self._picked:
            self._picked.remove(sid)
            self._rebuild_abilities()

    def _update_count(self):
        n = len(self._picked)
        total = len(self._all_abilities())
        self.lb_ability_count.setText(f"已选 {n} 个" if n else "还没选（至少选一个）")
        self.lb_hero_stat.setText(
            f"Skill 包 + 流水线　·　共 {total} 个能力" if total
            else "Skill 包 + 流水线　·　还没有能力")

    # ============================================================ ② 输入
    def _picked_skills(self) -> List[Dict[str, Any]]:
        out = []
        for sid in self._picked:
            s = SK.get_skill(sid)
            if s:
                out.append(s)
        return out

    def _merged_inputs(self) -> List[Any]:
        return merge_inputs([SK.inputs_of(s) for s in self._picked_skills()])

    def _values(self) -> Dict[str, str]:
        """当前能力需要的输入值。

        权威来源是 `self._input_values`（弹窗保存时落进来），不是控件 ——
        弹窗关掉后控件就销毁了，读控件必然读到空。

        ⚠ 缓存里**没有**的 key 要补 `Input.default`：开关 / 下拉这类输入
        一进来就有默认值（比如「读原文配图」默认开、「出图页数」默认 8），
        用户没打开过弹窗时缓存是空的 —— 不补默认值的话，摘要会一直误报
        「还差『读原文配图』」，明明它默认就是开着的。
        """
        out: Dict[str, str] = {}
        for inp in self._merged_inputs():
            if inp.key in self._input_values:
                out[inp.key] = self._input_values[inp.key]
            else:
                out[inp.key] = str(inp.default or "")
        return out

    def _refresh_input_summary(self):
        skills = self._picked_skills()
        if not skills:
            self.lb_input_summary.setText("先在上面选一个能力")
            self._set_summary_ok(False)
            self.btn_fill.setEnabled(False)
            return
        self.btn_fill.setEnabled(True)

        ins = self._merged_inputs()
        if not ins:
            self.lb_input_summary.setText("这个能力不需要额外输入，直接点「开始生成」")
            self._set_summary_ok(True)
            return

        names = "、".join(i.label for i in ins[:3])
        more = f" 等 {len(ins)} 项" if len(ins) > 3 else ""
        lack = missing_required(ins, self._values())
        if lack:
            self.lb_input_summary.setText(f"要填 {names}{more}　·　还差「{lack}」")
            self._set_summary_ok(False)
        else:
            # 只说「必填项已填好」，不说「已填好」—— 有些输入是可选的，
            # 说「已填好」会让用户以为所有框都有值了。
            self.lb_input_summary.setText(f"要填 {names}{more}　·　必填项已填好")
            self._set_summary_ok(True)

    def _set_summary_ok(self, ok: bool):
        self.lb_input_summary.setProperty("ok", bool(ok))
        self.lb_input_summary.style().unpolish(self.lb_input_summary)
        self.lb_input_summary.style().polish(self.lb_input_summary)

    def _open_inputs(self) -> bool:
        """打开填写输入弹窗。保存了返回 True。"""
        skills = self._picked_skills()
        if not skills:
            toast(self.window(), "先在上面选一个能力", "warn")
            return False
        dlg = InputsDialog(self.window(), skills, self._input_values)
        self._editors = dlg.editors          # 弹窗活着的时候给测试 / 排查用
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._input_values.update(dlg.values())
            self._editors = {}
            self._refresh_input_summary()
            return True
        self._editors = {}
        return False

    # ============================================================ 生成
    def _start(self):
        skills = self._picked_skills()
        if not skills:
            toast(self.window(), "先在上面选一个能力", "warn")
            return
        bad = [s.get("name", "") for s in skills if not SK.can_run(s)]
        if bad:
            toast(self.window(),
                  f"「{'、'.join(bad[:2])}」跑不起来 —— "
                  f"到「设置 → 内容模板 Skill」点「自检」看原因", "err", 5200)
            return
        ins = self._merged_inputs()
        lack = missing_required(ins, self._values())
        if lack:
            toast(self.window(), f"还差「{lack}」，先把输入填完", "warn")
            self._open_inputs()
            return
        # 需要模型的（单次生成型 + 标了 needs_llm 的流水线）才查 Key
        need_llm = any(not SK.is_pipeline(s) or SK.pipe_of(s) and SK.pipe_of(s).needs_llm
                       for s in skills)
        if need_llm and not (store.load_settings().get("api_key") or "").strip():
            toast(self.window(), "还没有配置 API Key，请先到「设置」里填写", "warn")
            return

        vals = self._values()
        self._jobs = [{"skill": s, "values": dict(vals)} for s in skills]
        self._build_cards([s["id"] for s in skills])
        self._set_busy(True)
        self._run_next()

    def _set_busy(self, busy: bool):
        self.btn_gen.setEnabled(not busy)
        self.btn_gen.setText("生成中…" if busy else "开始生成")
        if busy:
            self._run_t0 = time.time()
            self.bar_progress.setRange(0, 0)      # 不确定态，收到百分比再切刻度
            self.bar_progress.setValue(0)
            self.bar_progress.show()
            self.lb_elapsed.show()
            self._tick_elapsed()
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()
            self.bar_progress.hide()
            self.lb_elapsed.hide()

    def _tick_elapsed(self):
        """每秒刷一次「已用 / 约剩」。约剩按已走百分比线性外推，仅供参考。"""
        secs = max(0, int(time.time() - self._run_t0))
        mm, ss = divmod(secs, 60)
        base = f"已用 {mm:02d}:{ss:02d}"
        v = self.bar_progress.value()
        if self.bar_progress.maximum() == 100 and v >= 8:
            eta = int(secs / v * (100 - v))
            em, es = divmod(eta, 60)
            self.lb_elapsed.setText(f"{base} · 约剩 {em:02d}:{es:02d}")
        else:
            self.lb_elapsed.setText(base)

    def _on_pipe_prog(self, p: float, m: str):
        """流水线进度：进度条只进不退（子步骤标定区间可能相互重叠），文字照常刷。"""
        name = (self._cur_skill or {}).get("name", "")
        self.lb_progress.setText(f"{name}：{m or ''}" if name else (m or ""))
        card = self._cards.get((self._cur_skill or {}).get("id", ""))
        try:
            pct = int(round(max(0.0, min(1.0, float(p or 0))) * 100))
        except (TypeError, ValueError):
            pct = 0
        if pct > 0:
            if self.bar_progress.maximum() == 0:
                self.bar_progress.setRange(0, 100)
            cur = self.bar_progress.value()
            if pct > cur:
                self.bar_progress.setValue(pct)
            if card:
                card.set_busy(True, f"生成中 {max(pct, cur)}%")

    def _run_next(self):
        if not self._jobs:
            self._set_busy(False)
            self.lb_progress.setText("准备好就开跑")
            toast(self.window(), "全部完成", "ok")
            return
        job = self._jobs.pop(0)
        skill = job["skill"]
        sid = skill["id"]
        self._cur_skill = skill
        self.bar_progress.setRange(0, 0)          # 每个能力都从不确定态重新开始
        self.bar_progress.setValue(0)
        card = self._cards.get(sid)
        if card:
            card.set_busy(True, "运行中")
        self.lb_progress.setText(f"正在跑：{skill.get('name', '')}")

        if SK.is_pipeline(skill):
            self._run_pipe(job)
        else:
            self._run_prompt(job)

    def _run_pipe(self, job: Dict[str, Any]):
        """流水线形态的运行分支（抓网页 / 出图 / 渲染视频）。

        3 条内置流水线就在工坊里，且排序时流水线优先、默认选的也是它们 ——
        所以这是工坊最常走的一条路径，不是备胎。
        """
        from views.pipeline_dialog import PipelineTask
        skill = job["skill"]
        pipe = SK.pipe_of(skill)
        card = self._cards.get(skill["id"])
        if pipe is None:
            if card:
                card.set_busy(False)
                card.set_status("失败", "err", "缺少运行器")
            QTimer.singleShot(60, self._run_next)
            return

        # 只把这个能力真正需要的输入交给它（共用的输入可能带别的能力的字段）
        keys = {i.key for i in pipe.inputs()}
        vals = {k: v for k, v in job["values"].items() if k in keys}

        self._pipe_task = PipelineTask(pipe, vals, self)
        self._pipe_task.log.connect(lambda m: self.lb_progress.setText(
            f"{skill.get('name', '')}：{m}"))
        self._pipe_task.prog.connect(self._on_pipe_prog)
        self._pipe_task.done.connect(lambda res, j=job: self._on_pipe_done(j, res))
        self._pipe_task.failed.connect(lambda e, j=job: self._on_fail(j, e))
        self._pipe_task.start()

    def _on_pipe_done(self, job: Dict[str, Any], res: Dict[str, Any]):
        skill = job["skill"]
        card = self._cards.get(skill["id"])
        fields = skill.get("fields") or []
        content: Dict[str, Any] = {f: str(res.get(f) or "") for f in fields}
        for k, v in (res or {}).items():
            if not str(k).startswith("_") and k not in content:
                content[k] = str(v)
        if card:
            card.set_content(skill, content, job["values"].get("topic", ""), {})
            card.set_artifacts(res.get("_artifacts"))
            card.set_status("已生成", "ok")
            card.set_busy(False)
            card.run_precheck(show_dialog=False)
        self._store_item(job, content, res.get("_artifacts"))
        QTimer.singleShot(60, self._run_next)

    def _run_prompt(self, job: Dict[str, Any]):
        skill = job["skill"]
        vals = job["values"]
        topic = vals.get("topic", "")
        slots = SK.pick_slots(avoid=self._slots_used.get(skill["id"]))
        self._slots_used[skill["id"]] = slots
        system, user = SK.build_prompt(skill, topic, vals.get("persona", ""),
                                       vals.get("extra", ""), slots)
        job["slots"] = slots
        job["topic"] = topic
        self._task = llm.GenerateTask(store.load_settings(), system, user, self)
        self._task.done.connect(lambda text, j=job: self._on_prompt_done(j, text))
        self._task.failed.connect(lambda err, j=job: self._on_fail(j, err))
        self._task.start()

    def _on_prompt_done(self, job: Dict[str, Any], text: str):
        skill = job["skill"]
        raw = llm.extract_json(text)
        if raw is None:
            fields = skill.get("fields") or ["body"]
            raw = {f: "" for f in fields}
            raw["body"] = text.strip()
            raw[fields[0]] = raw.get(fields[0]) or text.strip().split("\n")[0][:30]
        content = SK.normalize_result(raw, skill)
        card = self._cards.get(skill["id"])
        if card:
            card.set_content(skill, content, job.get("topic", ""), job.get("slots"))
            card.set_status("已生成", "ok")
            card.set_busy(False)
        self._store_item(job, content)
        QTimer.singleShot(60, self._run_next)

    def _on_fail(self, job: Dict[str, Any], err: str):
        skill = job["skill"]
        card = self._cards.get(skill["id"])
        if card:
            card.set_busy(False)
            card.set_status("失败", "err", err)
        store.log(f"生成失败 {skill.get('id')}：{err}")
        QTimer.singleShot(60, self._run_next)

    # ============================================================ 结果卡片
    def _build_cards(self, skill_ids: List[str]):
        self.empty.setVisible(False)
        for k in list(self._cards.keys()):
            if k not in skill_ids:
                c = self._cards.pop(k)
                c.setParent(None)
                c.deleteLater()
        for sid in skill_ids:
            if sid in self._cards:
                continue
            skill = SK.get_skill(sid) or {}
            c = ContentCard(skill.get("platform", "xhs"), self)
            c.changed.connect(self._on_card_changed)
            c.request_regen.connect(self._regen_one)
            c.request_rewrite.connect(self._rewrite_one)
            c.request_save.connect(self._save_one)
            self._cards[sid] = c
        self._relayout_cards()
        self._sync_batch()

    def _cols(self) -> int:
        try:
            w = self.cards_box.width()
        except Exception:
            return 1
        return 2 if w >= 860 else 1

    def _relayout_cards(self):
        while self.cards_lay.count():
            it = self.cards_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)

        keys = list(self._cards.keys())
        self.lb_result_count.setText(f"{len(keys)} 项")
        if not keys:
            self.empty.setParent(self.cards_box)
            self.empty.setVisible(True)
            self.cards_lay.addWidget(self.empty, 0, 0, 1, 2)
            self._last_cols = 2
            return

        self.empty.setVisible(False)
        cols = self._cols()
        self._last_cols = cols
        for i, k in enumerate(keys):
            c = self._cards[k]
            c.setParent(self.cards_box)
            c.setVisible(True)
            self.cards_lay.addWidget(c, i // cols, i % cols)
        for col in range(2):
            self.cards_lay.setColumnStretch(col, 1 if col < cols else 0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not hasattr(self, "cards_box"):
            return
        if getattr(self, "_last_cols", 0) != self._cols():
            self._relayout_cards()

    def _sync_batch(self):
        b = BUSMOD.batch()
        if b is None:
            return
        by_skill = {it.skill_id: it for it in b.items}
        for sid, card in self._cards.items():
            it = by_skill.get(sid)
            if it is not None and card.populated():
                it.content = card.content()

    def _on_card_changed(self, _platform_key: str):
        self._sync_batch()

    def _clear(self):
        for k, c in list(self._cards.items()):
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()
        BUSMOD.set_batch(None)
        self._relayout_cards()

    # ============================================================ 单项动作
    def _regen_one(self, sid: str):
        skill = SK.get_skill(sid)
        if not skill:
            return
        vals = self._values()
        if not SK.is_pipeline(skill) and not vals.get("topic"):
            toast(self.window(), "先填写选题", "warn")
            self._open_inputs()
            return
        card = self._cards.get(sid)
        if card:
            card.set_busy(True, "生成中")
        self._jobs = [{"skill": skill, "values": vals}]
        self._set_busy(True)
        self._run_next()

    def _rewrite_one(self, sid: str, action: str):
        card = self._cards.get(sid)
        if not card:
            return
        skill = card.skill or {}
        content = card.content()
        cur = "\n\n".join(f"【{SK.field_label(k)}】\n{v}" for k, v in content.items() if v)
        acts = {
            "expand": "请把下面的内容扩写得更充实：补充具体方法、步骤、数字和场景，保持原有结构和风格。",
            "shrink": "请把下面的内容精简得更利落：删掉重复和空话，保留核心信息点，保持原有风格。",
            "angle": "请换一个全新的切入角度重写下面的内容：换个开头方式、换论证路径，但主题和信息价值不变。",
            "persona": "请换一个完全不同的人设口吻重写下面的内容：语气、用词习惯、称呼方式都要变。",
        }
        system = skill.get("system", "")
        user = (f"{acts.get(action, '请重写下面的内容。')}\n\n"
                f"仍然按原来的 JSON 格式输出，字段不变：\n"
                f"{', '.join(skill.get('fields') or [])}\n\n"
                f"原内容：\n{cur}")
        card.set_busy(True, "改写中")
        job = {"skill": skill, "topic": card.topic, "slots": {},
               "values": {"topic": card.topic}}
        self._task = llm.GenerateTask(store.load_settings(), system, user, self)
        self._task.done.connect(lambda text, j=job: self._on_prompt_done(j, text))
        self._task.failed.connect(lambda err, j=job: self._on_fail(j, err))
        self._task.start()

    def _check_all(self):
        total = 0
        errs = 0
        for c in self._cards.values():
            total += c.run_precheck(show_dialog=False)
            errs += sum(1 for i in c.precheck_issues() if i.level == "err")
        if total == 0:
            toast(self.window(), "全部产出体检通过", "ok")
        elif errs:
            toast(self.window(),
                  f"有 {errs} 项必改问题（共 {total} 项），点卡片上的「发布前体检」看逐条说明",
                  "err", 5000)
        else:
            toast(self.window(), f"共 {total} 项建议优化，没有必改项", "warn", 4200)

    # ============================================================ 素材库
    def _store_item(self, job: Dict[str, Any], content: Dict[str, Any],
                    artifacts: Optional[List[str]] = None):
        skill = job["skill"]
        topic = job.get("values", {}).get("topic", "") or job.get("topic", "")
        db = store.load_library()
        title = str(content.get("title") or content.get("body") or "")[:40]
        store.add_library_item(
            db, title=title or skill.get("name", ""), topic=topic,
            platform=skill.get("platform", ""), skill_id=skill["id"],
            content=content, artifacts=artifacts, tags=[topic] if topic else [],
        )
        BUS.library_changed.emit()

    def _save_one(self, sid: str):
        card = self._cards.get(sid)
        if not card:
            return
        content = card.content()
        skill = card.skill or {}
        topic = card.topic or ""
        db = store.load_library()
        title = str(content.get("title") or content.get("body") or "")[:40]
        store.add_library_item(db, title=title or skill.get("name", ""), topic=topic,
                               platform=skill.get("platform", ""),
                               skill_id=skill.get("id", ""),
                               content=content, artifacts=card.artifacts,
                               tags=[topic] if topic else [])
        BUS.library_changed.emit()
        n = len(card.artifacts or [])
        toast(self.window(), "已存入素材库" + (f"（含 {n} 个产出文件）" if n else ""), "ok")

    # ============================================================ 对外
    def _push_and_go(self):
        n = self.push_to_batch()
        BUS.goto_workbench.emit()
        if n:
            toast(self.window(), f"已同步 {n} 项产出到发布工作台", "ok")
        else:
            toast(self.window(), "还没有可发布的内容，先在上面生成", "warn")

    def push_to_batch(self):
        """把当前界面上的产出同步成全局草稿批次，供发布工作台使用。"""
        items = []
        for sid, card in self._cards.items():
            content = card.content()
            if not any(content.values()):
                continue
            skill = card.skill or {}
            it = DraftItem(skill.get("platform", "xhs"), skill.get("id", ""),
                           skill.get("name", ""), content, card.topic or "")
            it.artifacts = list(card.artifacts or [])
            items.append(it)
        b = Batch(items[0].topic if items else "")
        b.items = items
        BUSMOD.set_batch(b)
        return len(items)
