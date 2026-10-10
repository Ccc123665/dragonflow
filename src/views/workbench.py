"""发布工作台：勾选账号 → 一键填充 → 人工确认 → 一键发布。

界面逻辑（改版要点）
  · 左「账号矩阵」由主窗口提供，只在工作台出现，可折叠（手柄在分界线底部）
  · 「待发布内容」不再是固定左栏，改为工具栏按钮 + 弹窗，浏览器区占满宽度
  · 「目标账号」同样是工具栏弹窗（选参与本次发布的账号）
  · 「从内容工坊同步」「合规检测」收进待发布内容弹窗里
  · 浏览器标签页带关闭 ×；底部执行结果条：每条内容填到了哪个账号、成没成，一眼可见
"""
from typing import Any, Dict, List, Optional
import os

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import bus as BUSMOD
import browser as BR
import config
import icons
import platforms as PF
import publisher as PUB
import store
import theme
from bus import BUS, DraftItem
from widgets.common import (
    Badge, BrowserTab, EmptyState, IconButton, Pill, StepBar, ToolButton, toast,
)
from widgets.content_card import ContentCard
from widgets.dialogs import BaseDialog

STEPS = ["打开发布页", "一键填充", "核对内容", "一键发布"]


def _diagnose_text(d: Dict[str, Any]) -> tuple:
    """把诊断结果翻成人话。返回 (一句话结论, 逐项明细)。"""
    yes, no = "有", "没有"
    login = bool(d.get("login"))
    editor = bool(d.get("editor"))
    title = bool(d.get("title"))
    url = str(d.get("url", ""))
    target_img = "target=image" in url

    lines = [
        f"页面地址：{url or '（读不到）'}",
        f"是否登录：{'未登录（页面出现了登录框）' if login else '已登录'}",
        f"标题输入框：{yes if title else no}",
        f"正文编辑器：{yes if editor else no}",
        f"配图上传控件：{yes if d.get('fileInput') else no}",
        f"「上传图文」入口：{yes if d.get('imageTab') else no}",
        f"发布按钮（xhs-publish-btn）：{d.get('publishHost', 0)} 个",
        f"页面上 contenteditable：{d.get('contentEditables', 0)} 个 / "
        f"input：{d.get('inputs', 0)} 个",
    ]

    if login:
        head = "这个账号没登录，先在浏览器里扫码登录，再回来填充。"
    elif editor:
        head = "页面正常，标题框和正文编辑器都在 —— 填充应该能成功。"
    elif not target_img and url:
        head = ("地址栏里没有 target=image，说明停在了视频页或别的页面。"
                "点「打开发布页」重新打开一次（现在会直接进图文页）。")
    elif d.get("imageTab"):
        head = "正文编辑器还没渲染出来。点一下页面上的「上传图文」，等表单出现再填充。"
    else:
        head = ("找不到标题框和正文编辑器 —— 页面结构可能变了，"
                "或者这不是发布页。")
    return head, "\n".join(lines)

STATUS_KIND = {
    "待填充": (theme.TEXT_2, theme.BG_INPUT),
    "填充中": (theme.WARNING, theme.WARNING_TINT),
    "已填充": (theme.PRIMARY, theme.PRIMARY_TINT),
    "发布中": (theme.WARNING, theme.WARNING_TINT),
    "已发布": (theme.SUCCESS, theme.SUCCESS_TINT),
    "需人工": (theme.WARNING, theme.WARNING_TINT),
    "失败": (theme.DANGER, theme.DANGER_TINT),
}


# ================================================================ 待发布内容弹窗
class DraftsDialog(BaseDialog):
    """待发布内容弹窗：把原来固定的左栏搬进来，浏览器区因此能占满宽度。

    卡片控件本身是复用的（不重建），只是临时挂到这个弹窗的滚动区里，
    关闭时再搬回工作台 —— 这样在弹窗里编辑的内容不会丢。
    """

    def __init__(self, parent, wb: "WorkbenchView"):
        super().__init__(parent, "待发布内容",
                         "这些内容会被填充到各平台的发布页。可以直接在这里编辑，"
                         "改完关闭即可，工作台会同步。",
                         width=800, height=700)
        self.wb = wb

        head = QHBoxLayout()
        head.setSpacing(8)
        self.lb_count = QLabel("")
        self.lb_count.setObjectName("Muted")
        head.addWidget(self.lb_count)
        head.addStretch(1)

        self.btn_sync = QPushButton("从内容工坊同步")
        self.btn_sync.setObjectName("Soft")
        self.btn_sync.setIcon(icons.icon("sync", theme.TEXT_2, 14))
        self.btn_sync.setToolTip("把内容工坊里最新生成的内容拉过来")
        self.btn_sync.clicked.connect(self._sync)
        head.addWidget(self.btn_sync)

        self.btn_check = QPushButton("发布前体检")
        self.btn_check.setObjectName("Soft")
        self.btn_check.setIcon(icons.icon("check", theme.TEXT_2, 14))
        self.btn_check.setToolTip("长度 / 必填 / 站外引流 / 排版 / 词库，一次全查")
        self.btn_check.clicked.connect(self._check)
        head.addWidget(self.btn_check)
        self.body.addLayout(head)

        self.sc = QScrollArea()
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QFrame.Shape.NoFrame)
        self.sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.addWidget(self.sc, 1)

        # 把工作台里的卡片容器搬进来（takeWidget 不会销毁它）
        wb.cards_box.setParent(None)
        self.sc.setWidget(wb.cards_box)
        wb.cards_box.show()

        self.add_stretch()
        self.add_button("关闭", "Primary", self.accept, default=True)
        self._refresh_count()

    def _refresh_count(self):
        n = len(self.wb._cards)
        self.lb_count.setText(f"共 {n} 个平台的内容" if n else "还没有内容")

    def _sync(self):
        self.wb._pull_from_studio()
        self._refresh_count()

    def _check(self):
        self.wb._check_all_content()

    def done(self, r):
        # 把卡片容器搬回工作台，别跟着弹窗一起被销毁
        try:
            self.sc.takeWidget()
            self.wb.cards_box.setParent(self.wb)
            self.wb.cards_box.hide()
        except Exception:
            pass
        super().done(r)


# ================================================================ 目标账号弹窗
class AccountsPopup(BaseDialog):
    """选择本次参与发布的账号。按平台分组，支持全选/全不选。"""

    def __init__(self, parent, checked: set, platform_keys: List[str],
                 content_keys: Optional[set] = None):
        super().__init__(parent, "目标账号", "勾选本次要发布的账号，只有勾上的账号会被填充和发布")
        self._boxes: Dict[str, QCheckBox] = {}
        self._checked = set(checked)
        # 「有待发布内容的平台」之外再列出来的组（比如账号已勾选但还没生成
        # 内容）——组头会标注「暂无待发布内容」，勾了也不会参与填充。
        content_keys = content_keys if content_keys is not None else set(platform_keys)
        db = store.load_accounts()

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setMinimumHeight(300)
        sc.setMaximumHeight(420)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 6, 0)
        bl.setSpacing(10)

        self._total = 0
        for pk in platform_keys:
            accs = store.accounts_of(db, pk)
            if not accs:
                continue
            head = QHBoxLayout()
            head.setSpacing(6)
            if pk in content_keys:
                t = QLabel(f"{PF.name_of(pk)}")
            else:
                t = QLabel(f"{PF.name_of(pk)} · 暂无待发布内容")
            t.setObjectName("FieldLabel")
            if pk not in content_keys:
                t.setToolTip("这个平台本次没有专属内容 —— 勾选后点「一键填充」"
                             "会问你是否把本次内容也发过去")
            head.addWidget(t)
            head.addWidget(Badge(str(len(accs))))
            head.addStretch(1)
            b_all = QPushButton("全选")
            b_all.setObjectName("Ghost")
            b_all.clicked.connect(lambda _=False, k=pk: self._set_platform(k, True))
            b_none = QPushButton("全不选")
            b_none.setObjectName("Ghost")
            b_none.clicked.connect(lambda _=False, k=pk: self._set_platform(k, False))
            head.addWidget(b_all)
            head.addWidget(b_none)
            bl.addLayout(head)

            for a in accs:
                self._total += 1
                logged = bool(a.get("logged_in"))
                cb = QCheckBox(f"{a['name']}    ·  "
                               f"{'已登录' if logged else '未登录'}")
                cb.setChecked(a["id"] in self._checked)
                cb.setProperty("_pk", pk)
                cb.setProperty("_aid", a["id"])
                if not logged:
                    cb.setToolTip("这个账号还没登录 —— 打开发布页扫码后才能填充")
                elif a.get("status") in ("停用", "封禁预警"):
                    cb.setToolTip("该账号状态异常，默认不建议参与发布")
                self._boxes[a["id"]] = cb
                bl.addWidget(cb)
        bl.addStretch(1)
        sc.setWidget(box)
        self.body.addWidget(sc, 1)

        if self._total == 0:
            self.lb_sub.setText("还没有账号。先到左侧「账号矩阵」添加账号。")

        self.add_stretch()
        # 差异化分配（内容 × 账号 的网格）收进这里 —— 它和「选账号」本来就是
        # 同一件事的两个粒度，放在工具栏上是重复入口。
        self.add_button("差异化分配…", "Soft", lambda: self.done(2))
        self.add_button("取消", "Soft", self.reject)
        self.add_button("确定", "Primary", self.accept, default=True)

    def _set_platform(self, pk: str, on: bool):
        for aid, cb in self._boxes.items():
            if cb.property("_pk") == pk:
                cb.setChecked(on)

    def checked(self) -> set:
        return {aid for aid, cb in self._boxes.items() if cb.isChecked()}


# ================================================================ 工作台
class WorkbenchView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: Dict[str, ContentCard] = {}
        self._checked: set = set()
        self._opened: List[str] = []
        self._cur_aid = ""
        # 上一次执行的逐账号结果 {account_id: (status, message)}。
        # 必须单独存：底部结果条是按账号渲染的，而内容批次里存的是
        # 「平台级」状态，跑完一重建就把刚出的「失败」冲回「待填充」了。
        self._last_result: Dict[str, tuple] = {}
        self._queue: Optional[PUB.PublishQueue] = None
        self._mode = "fill"
        self._tabs: Dict[str, BrowserTab] = {}
        self._chip_widgets: Dict[str, QWidget] = {}
        # 正在等待「图传完自动续跑」的账号（防 hook 与队列失败双路径重复排队）
        self._refill_pending: set = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_stepbar())

        # ---------------- 进度条
        self.prog_box = QWidget()
        self.prog_box.setVisible(False)
        pl = QHBoxLayout(self.prog_box)
        pl.setContentsMargins(20, 8, 20, 8)
        pl.setSpacing(10)
        self.lb_prog = QLabel("")
        self.lb_prog.setObjectName("Muted")
        pl.addWidget(self.lb_prog)
        self.prog = QProgressBar()
        self.prog.setFixedHeight(6)
        self.prog.setTextVisible(False)
        self.prog.setMinimumWidth(200)
        pl.addWidget(self.prog, 1)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("Ghost")
        self.btn_stop.clicked.connect(self._stop)
        pl.addWidget(self.btn_stop)
        root.addWidget(self.prog_box)

        # ---------------- 主体：浏览器区占满（内容区已改成弹窗）
        self.browser_pane = self._build_browser_pane()
        root.addWidget(self.browser_pane, 1)

        self._build_cards_host()
        root.addWidget(self._build_status_strip())

        BUS.draft_changed.connect(self.reload_drafts)
        BUS.accounts_changed.connect(self.reload_drafts)
        self.reload_drafts()

        # 填充中途用户在选图器里交回文件 → 回写内容并自动补一次填充。
        # 不注册这个的话，用户选完图还得再手动点一次「一键填充」（真实反馈）。
        BR.set_files_picked_hook(self._on_files_picked)
        # 发布页里扫码登录会跳转页面 → 浏览器层防抖喊一声，这里重探登录态。
        # 不注册的话，登录发生在「打开发布页后探测两轮」之后就没人更新，
        # 账号明明登录着却永远挂灰「未登录」（真机反馈：抖音登录了不亮）。
        BR.set_login_hook(self._on_login_hint)

    # ============================================ 工具栏
    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("NavBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedHeight(58)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 0, 14, 0)
        bl.setSpacing(8)

        t = QLabel("发布工作台")
        t.setObjectName("H2")
        bl.addWidget(t)

        self.lb_summary = QLabel("")
        self.lb_summary.setObjectName("Muted")
        bl.addWidget(self.lb_summary)
        bl.addStretch(1)

        self.btn_drafts = ToolButton("待发布内容 · 0", "list", "Outline")
        self.btn_drafts.setToolTip("查看 / 编辑要发布的内容（也可以从内容工坊同步）")
        self.btn_drafts.clicked.connect(self._open_drafts)
        bl.addWidget(self.btn_drafts)

        # 「矩阵分配」不再单独占一个按钮 —— 它和「目标账号」是同一件事的
        # 两个粒度（一个选账号、一个选 内容×账号），入口收进「目标账号」弹窗。
        self.btn_accounts = ToolButton("目标账号 · 0", "target", "Outline")
        self.btn_accounts.setToolTip(
            "勾选本次要发布的账号。弹窗里还有「差异化分配…」—— "
            "按 内容 × 账号 网格勾选，并可为同平台多账号生成差异化版本，避免判重复")
        self.btn_accounts.clicked.connect(self._pick_accounts)
        bl.addWidget(self.btn_accounts)

        self.btn_precheck = ToolButton("发布前体检", "check", "Outline")
        self.btn_precheck.setToolTip("长度 / 必填 / 站外引流 / 排版 / 词库，一次全查")
        self.btn_precheck.clicked.connect(lambda: self._check_all_content(True))
        bl.addWidget(self.btn_precheck)

        self.sw_confirm = theme.Switch(
            checked=bool(store.load_settings().get("publish_confirm", True)))
        self.sw_confirm.toggled.connect(self._save_confirm)
        self.sw_confirm.setToolTip(
            "控制「一键发布」要不要先弹确认框。\n"
            "开：点发布 → 弹「即将向 N 个账号触发发布」→ 你点确认才真的发。\n"
            "关：点发布直接发出去，不再问。\n"
            "（不影响「一键填充」—— 填充永远不弹确认，因为填充只是把内容写进页面，\n"
            " 还要你自己核对后才发布）")
        bl.addWidget(self.sw_confirm)
        lb_confirm = QLabel("发布前二次确认")
        lb_confirm.setObjectName("Muted")
        lb_confirm.setToolTip(self.sw_confirm.toolTip())
        bl.addWidget(lb_confirm)

        self.btn_open = ToolButton("打开发布页", "globe", "Soft")
        self.btn_open.clicked.connect(self._open_pages)
        bl.addWidget(self.btn_open)

        self.btn_fill = ToolButton("一键填充", "sparkle", "Soft")
        self.btn_fill.clicked.connect(lambda: self._run("fill"))
        bl.addWidget(self.btn_fill)

        self.btn_publish = ToolButton("一键发布", "send", "Primary")
        self.btn_publish.clicked.connect(lambda: self._run("submit"))
        bl.addWidget(self.btn_publish)
        return bar

    def _build_stepbar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("NavBarSunk")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.setFixedHeight(40)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 0, 18, 0)
        self.steps = StepBar(STEPS)
        lay.addWidget(self.steps)
        return w

    # ============================================ 内容卡片宿主
    def _build_cards_host(self):
        """卡片容器：平时挂在工作台上（隐藏），打开弹窗时搬进弹窗。

        注意别用 clear_layout 之外的方式重建 —— 卡片控件要复用，
        否则弹窗里编辑的内容会丢。
        """
        self.cards_box = QWidget()
        self.cards_lay = QVBoxLayout(self.cards_box)
        self.cards_lay.setContentsMargins(0, 0, 4, 0)
        self.cards_lay.setSpacing(10)

        self.empty_cards = EmptyState(
            "还没有内容", "先去「内容工坊」生成，再回到这里点「从内容工坊同步」", "send")
        self.cards_lay.addWidget(self.empty_cards)
        self.cards_lay.addStretch(1)

        self.cards_box.setParent(self)
        self.cards_box.hide()

    def _open_drafts(self):
        d = DraftsDialog(self.window(), self)
        d.exec()
        # 弹窗里可能改过内容，回来后同步一次状态
        self._update_summary()
        self._refresh_card_status()

    # ============================================ 矩阵分配
    def _open_matrix(self):
        items = BUSMOD.batch().items if BUSMOD.batch() else []
        if not items:
            toast(self.window(), "还没有内容，先去内容工坊生成", "warn")
            return
        db = store.load_accounts()
        accounts = {it.platform_key: store.accounts_of(db, it.platform_key)
                    for it in items}
        if not any(accounts.values()):
            toast(self.window(), "还没有账号，先到左侧「账号矩阵」添加", "warn")
            return
        from views.matrix_dialog import MatrixDialog
        d = MatrixDialog(self.window(), self, items, accounts, set(self._checked))
        if d.exec():
            self._checked = d.checked()
            self._update_summary()
            self._rebuild_status_chips()
            n = sum(1 for it in items for a in accounts[it.platform_key]
                    if it.has_variant(a["id"]))
            toast(self.window(),
                  f"已分配 {len(self._checked)} 个账号"
                  + (f"，其中 {n} 个使用差异化版本" if n else ""),
                  "ok", 3600)

    # ============================================ 浏览器面板
    def _build_browser_pane(self) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(w, theme.BG_CARD)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        tb = QWidget()
        tb.setFixedHeight(42)
        tb.setStyleSheet(
            f"background:{theme.BG_CARD};border-bottom:1px solid {theme.LINE};")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(10, 0, 10, 0)
        tl.setSpacing(6)

        self.tabs_box = QWidget()
        self.tabs_lay = QHBoxLayout(self.tabs_box)
        self.tabs_lay.setContentsMargins(0, 0, 0, 0)
        self.tabs_lay.setSpacing(4)
        tl.addWidget(self.tabs_box, 1)

        self.lb_no_tab = QLabel("尚未打开发布页")
        self.lb_no_tab.setObjectName("Hint")
        tl.addWidget(self.lb_no_tab)

        self.btn_diag = IconButton("eye", "诊断当前页", 28, 15)
        self.btn_diag.setToolTip(
            "看看这个页面上到底有什么：是否登录、有没有标题框、"
            "有没有正文编辑器、是不是停在视频页。填不上时先点这里")
        self.btn_diag.clicked.connect(self._diagnose_current)
        self.btn_reload = IconButton("refresh", "刷新当前页", 28, 15)
        self.btn_reload.clicked.connect(BR.BROWSER.reload)
        self.btn_ext = IconButton("external", "在系统浏览器中打开", 28, 15)
        self.btn_ext.clicked.connect(self._open_external)
        for b in (self.btn_diag, self.btn_reload, self.btn_ext):
            tl.addWidget(b)
        lay.addWidget(tb)

        self.view = QWebEngineView()
        theme.paint_bg(self.view, "#FFFFFF")
        BR.BROWSER.attach_view(self.view)
        lay.addWidget(self.view, 1)

        self.empty_browser = EmptyState(
            "浏览器区", "点「打开发布页」后，各平台页面会在这里打开", "globe")
        self.empty_browser.setParent(self.view)
        theme.paint_bg(self.empty_browser, "#FFFFFF")
        self.empty_browser.show()
        return w

    # ============================================ 底部执行结果
    def _build_status_strip(self) -> QWidget:
        self.status_strip = QWidget()
        self.status_strip.setObjectName("Sunk")
        self.status_strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.status_strip.setFixedHeight(46)
        self.status_strip.setVisible(False)
        lay = QHBoxLayout(self.status_strip)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(8)

        lb = QLabel("执行结果")
        lb.setObjectName("FieldLabel")
        lay.addWidget(lb)

        self.chips_scroll = QScrollArea()
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_box = QWidget()
        self.chips_lay = QHBoxLayout(self.chips_box)
        self.chips_lay.setContentsMargins(0, 0, 0, 0)
        self.chips_lay.setSpacing(6)
        self.chips_scroll.setWidget(self.chips_box)
        lay.addWidget(self.chips_scroll, 1)
        return self.status_strip

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "empty_browser"):
            self.empty_browser.setGeometry(0, 0, self.view.width(), self.view.height())

    # ============================================ 目标账号
    def _pick_accounts(self):
        content_keys = self._platforms_with_content()
        keys = list(content_keys)
        # 已勾选账号的平台也要列出来 —— 否则勾着的账号在弹窗里「蒸发」，
        # 看不见也取消不了（真机反馈：登录完的抖音账号在弹窗里找不到）。
        db = store.load_accounts()
        for aid in sorted(self._checked):
            acc = store.get_account(db, aid)
            if acc and acc["platform"] not in keys:
                keys.append(acc["platform"])
        if not keys:
            toast(self.window(), "还没有内容，先去内容工坊生成", "warn")
            return
        dlg = AccountsPopup(self.window(), self._checked, keys,
                            content_keys=set(content_keys))
        code = dlg.exec()
        if code == 2:
            # 点了「差异化分配…」：先把勾选记下来，再打开矩阵网格
            self._checked = dlg.checked()
            self._update_summary()
            self._open_matrix()
            return
        if code:
            self._checked = dlg.checked()
            self._update_summary()

    def _platforms_with_content(self) -> List[str]:
        b = BUSMOD.batch()
        return [it.platform_key for it in b.items] if b and b.items else []

    # ============================================ 数据同步
    def reload_drafts(self):
        b = BUSMOD.batch()
        keys = [it.platform_key for it in b.items] if b and b.items else []

        # 账号勾选：新出现的账号默认勾上，已删除的清掉
        db = store.load_accounts()
        valid = {a["id"] for a in store.list_accounts(db)}
        self._checked &= valid
        # 账号删了就把它的历史结果也丢掉，别在结果条上留幽灵条目
        self._last_result = {k: v for k, v in self._last_result.items() if k in valid}
        for pk in keys:
            for a in store.accounts_of(db, pk):
                if a["id"] not in getattr(self, "_seen", set()):
                    # 没登录的账号不默认勾选 —— 它填不了，勾上只会让整批里
                    # 多一条注定失败的记录。用户要发的时候自己勾。
                    if a.get("logged_in"):
                        self._checked.add(a["id"])
        self._seen = valid

        self._rebuild_cards(keys)
        self._rebuild_status_chips()
        self._update_summary()
        self.btn_drafts.setText(f"待发布内容 · {len(keys)}")

    def _rebuild_cards(self, platform_keys: List[str]):
        for k in list(self._cards.keys()):
            if k not in platform_keys:
                c = self._cards.pop(k)
                c.setParent(None)
                c.deleteLater()
        for pk in platform_keys:
            card = self._cards.get(pk)
            if card is None:
                card = ContentCard(pk, self.cards_box, compact=True)
                card.changed.connect(self._on_card_changed)
                card.request_regen.connect(self._goto_studio)
                card.request_rewrite.connect(self._goto_studio)
                card.request_save.connect(self._save_one)
                self._cards[pk] = card
                # 插在末尾的 stretch 之前，否则卡片会被顶到下方
                self.cards_lay.insertWidget(self.cards_lay.count() - 1, card)
            it = BUSMOD.find_item(pk)
            if it:
                import skills as SK
                skill = SK.get_skill(it.skill_id) or {"name": it.skill_name,
                                                      "fields": list(it.content.keys())}
                card.set_content(skill, it.content, it.topic, it.slots)
                card.set_artifacts(it.artifacts)
                card.set_status(it.status, "info")
        self.empty_cards.setVisible(not platform_keys)

    def _on_card_changed(self, platform_key: str):
        card = self._cards.get(platform_key)
        it = BUSMOD.find_item(platform_key)
        if card and it and card.populated():
            it.content = card.content()

    def _save_one(self, platform_key: str):
        card = self._cards.get(platform_key)
        it = BUSMOD.find_item(platform_key)
        if not card:
            return
        content = card.content()
        db = store.load_library()
        title = str(content.get("title") or content.get("body") or "")[:40]
        store.add_library_item(db, title=title or (it.topic if it else ""),
                               topic=it.topic if it else "", platform=platform_key,
                               skill_id=it.skill_id if it else "",
                               content=content, tags=[it.topic] if it else [])
        BUS.library_changed.emit()
        toast(self.window(), "已存入素材库", "ok")

    def _goto_studio(self, platform_key: str = "", action: str = ""):
        toast(self.window(), "重新生成请到「内容工坊」操作", "info")

    def _pull_from_studio(self):
        w = self.window()
        studio = getattr(w, "studio_view", None)
        if studio is None:
            return
        n = studio.push_to_batch()
        if n:
            toast(self.window(), f"已从内容工坊同步 {n} 个平台的内容", "ok")
        else:
            toast(self.window(), "内容工坊里还没有内容", "warn")

    def _save_confirm(self, _state):
        s = store.load_settings()
        s["publish_confirm"] = self.sw_confirm.isChecked()
        store.save_settings(s)

    def _checked_accounts(self) -> List[Dict[str, Any]]:
        db = store.load_accounts()
        out: List[Dict[str, Any]] = []
        seen = set()
        for pk in self._platforms_with_content():
            for a in store.accounts_of(db, pk):
                if a["id"] in self._checked and a["id"] not in seen:
                    out.append(a)
                    seen.add(a["id"])
        # 勾选了、但该平台本次没有专属内容的账号也带上 —— 以前直接丢掉，
        # 一键填充时对它们一声不吭，用户以为「点了没反应」（真机反馈：
        # 勾了小红书 + 抖音，只有小红书被填充）。_run 会就这些账号问一句
        # 「要不要把本次内容也发过去」。
        for a in store.list_accounts(db):
            if a["id"] in self._checked and a["id"] not in seen:
                out.append(a)
                seen.add(a["id"])
        return out

    def _item_for(self, acc: Dict[str, Any], reuse_ids=frozenset()):
        """账号本次要用的内容条目。

        优先找该平台的专属条目；没有且用户同意复用（reuse_ids）时，
        退回批次第一条 —— 一份内容发多平台正是本产品的核心场景，
        各适配器按统一的 title / body / topics 字段取值，天然可跨平台。
        """
        it = BUSMOD.find_item(acc["platform"])
        if it is None and acc["id"] in reuse_ids:
            b = BUSMOD.batch()
            it = b.items[0] if b and b.items else None
        return it

    def _update_summary(self):
        n = len(self._checked_accounts())
        p = len(self._platforms_with_content())
        self.lb_summary.setText(f"已选 {n} 个账号 · {p} 个平台")
        has = n > 0 and p > 0
        self.btn_fill.setEnabled(has)
        self.btn_publish.setEnabled(has)
        self.btn_open.setEnabled(has)
        self.btn_accounts.setText(f"目标账号 · {n}")

    # ============================================ 步骤 / 结果条
    def _set_step(self, n: int):
        self.steps.set_step(max(0, min(len(STEPS) - 1, n)))

    def _rebuild_status_chips(self):
        theme.clear_layout(self.chips_lay)
        self._chip_widgets.clear()
        accs = self._checked_accounts()
        if not accs:
            self.status_strip.setVisible(False)
            return
        for a in accs:
            pk = a["platform"]
            saved = self._last_result.get(a["id"])
            if saved:
                status, message = saved
            else:
                it = BUSMOD.find_item(pk)
                status, message = (it.status if it else "待填充"), ""
            chip = self._make_chip(a, status, message)
            self.chips_lay.addWidget(chip)
        self.chips_lay.addStretch(1)
        self.status_strip.setVisible(True)

    def _make_chip(self, acc: Dict[str, Any], status: str, message: str = "") -> QWidget:
        color, bg = STATUS_KIND.get(status, STATUS_KIND["待填充"])
        chip = QPushButton(f"{PF.name_of(acc['platform'])}·{acc['name']}   {status}")
        chip.setObjectName("TabBtn")
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setStyleSheet(
            f"QPushButton{{background:{bg};color:{color};border:1px solid {bg};"
            f"border-radius:8px;padding:5px 11px;{theme.css_font(12, 600)}}}"
            f"QPushButton:hover{{border:1px solid {color};}}"
        )
        # 失败原因直接挂在 chip 上。之前只把原因写进记录里，
        # 用户看到「失败」却不知道为啥，还得去翻发布记录。
        tip = message or "点击可切到该账号的发布页"
        chip.setToolTip(tip + "\n（点击可切到该账号的发布页）" if message else tip)
        chip.clicked.connect(lambda _=False, aid=acc["id"]: self._select(aid))
        self._chip_widgets[acc["id"]] = chip
        return chip

    def _update_chip(self, aid: str, status: str, message: str = ""):
        db = store.load_accounts()
        acc = store.get_account(db, aid)
        chip = self._chip_widgets.get(aid)
        if acc is None or chip is None:
            return
        color, bg = STATUS_KIND.get(status, STATUS_KIND["待填充"])
        chip.setText(f"{PF.name_of(acc['platform'])}·{acc['name']}   {status}")
        chip.setStyleSheet(
            f"QPushButton{{background:{bg};color:{color};border:1px solid {bg};"
            f"border-radius:8px;padding:5px 11px;{theme.css_font(12, 600)}}}"
            f"QPushButton:hover{{border:1px solid {color};}}"
        )
        if message:
            chip.setToolTip(message)

    # ============================================ 打开发布页
    def _open_pages(self):
        accs = self._checked_accounts()
        if not accs:
            toast(self.window(), "先在「目标账号」里勾选账号", "warn")
            return
        for a in accs:
            pf = PF.get(a["platform"])
            if not pf:
                continue
            aid = a["id"]
            it = BUSMOD.find_item(a["platform"])
            # 图文 / 视频可能是两个不同的 URL（小红书就是），按内容挑
            url = PF.publish_url_for(a["platform"], it.content if it else {})
            BR.BROWSER.open(aid, url)
            self._sync_suggested_dir(aid)
            if aid not in self._opened:
                self._opened.append(aid)
            # ⚠ 这里**不**写 logged_in。
            # 以前「打开过发布页」就等于「已登录」，于是账号矩阵里全是深色的
            # 「已登录」账号，实际一个都没扫码 —— 用户原话：「不要预写账号进去」。
            # 现在改成打开后延迟探测真实登录状态（_probe_login，最多两轮）。
            QTimer.singleShot(4200, lambda i=aid, p=a["platform"]: self._probe_login(i, p))
        self._rebuild_tabs()
        self.empty_browser.hide()
        self._select(self._opened[-1] if self._opened else "")
        self._set_step(1)
        toast(self.window(), f"已打开 {len(accs)} 个发布页，请确认各平台登录状态", "info", 3200)

    def _on_login_hint(self, aid: str) -> None:
        """浏览器页面跳转完成（含扫码登录后的跳转）→ 重探登录态。

        browser 层已防抖；这里只做薄过滤：标签页开着、页面还活着、
        账号还在库里，才值得跑一次 diagnose。
        """
        if aid not in self._opened or not BR.BROWSER.has_page(aid):
            return
        acc = store.get_account(store.load_accounts(), aid)
        if not acc:
            return
        self._probe_login(aid, acc["platform"])

    def _probe_login(self, aid: str, platform_key: str, attempt: int = 1) -> None:
        """探测这个账号到底登录了没有，写回 logged_in。

        只认适配脚本明确给出的答案（diagnose 里的 login 字段）。
        拿不到答案就**不动** —— 宁可保持「未登录」，也不要替用户预设成已登录。

        但页面加载慢时第一轮探测（打开后 4.2s）常常什么都拿不到，
        账号明明登录着却一直挂着灰色的「未登录」。所以最多补一轮：
        第一轮没答案 → +4s 再探一次；两轮都没答案才认命（attempt 计数，
        不会无限重试）。
        """
        if aid not in self._opened:
            return   # 标签页已关，别再探
        pf = PF.get(platform_key) or {}
        page = BR.BROWSER.page(aid)
        if page is None:
            return

        def done(d):
            if isinstance(d, dict) and "login" in d:
                db = store.load_accounts()
                acc = store.get_account(db, aid)
                if not acc:
                    return
                logged = not bool(d.get("login"))
                if bool(acc.get("logged_in")) == logged:
                    return
                store.update_account(db, aid, {"logged_in": logged})
                BUS.accounts_changed.emit()
                return
            # 没拿到答案：页面多半还没就绪。补一轮探测后就放弃
            if attempt < 2 and aid in self._opened:
                QTimer.singleShot(
                    4000, lambda: self._probe_login(aid, platform_key, attempt + 1))

        PUB.diagnose(page, platform_key, pf.get("adapter", ""), done)

    def open_account(self, aid: str):
        """由主窗口调用：账号矩阵里点了某个账号。"""
        if aid not in self._opened:
            self._opened.append(aid)
        self._checked.add(aid)
        self.empty_browser.hide()
        self._rebuild_tabs()
        self._select(aid)
        self._update_summary()
        self._rebuild_status_chips()

    def _rebuild_tabs(self):
        theme.clear_layout(self.tabs_lay)
        self._tabs.clear()
        db = store.load_accounts()
        shown = 0
        for aid in self._opened:
            a = store.get_account(db, aid)
            if not a:
                continue
            shown += 1
            name = f"{PF.name_of(a['platform'])}·{a['name']}"
            tab = BrowserTab(aid, name, active=(aid == self._cur_aid))
            tab.selected.connect(self._select)
            tab.closed.connect(self._close_tab)
            self._tabs[aid] = tab
            self.tabs_lay.addWidget(tab)
        self.tabs_lay.addStretch(1)
        self.lb_no_tab.setVisible(shown == 0)

    def _close_tab(self, aid: str):
        """关掉一个标签页。关的是当前页就顺延到相邻的一个。"""
        if aid not in self._opened:
            return
        idx = self._opened.index(aid)
        self._opened.remove(aid)
        if self._cur_aid == aid:
            self._cur_aid = ""
            if self._opened:
                nxt = self._opened[min(idx, len(self._opened) - 1)]
                self._rebuild_tabs()
                self._select(nxt)
                return
            # 全关完了 → 回到空态
            self._rebuild_tabs()
            self.empty_browser.show()
            self.empty_browser.raise_()
            return
        self._rebuild_tabs()

    def _select(self, aid: str):
        if not aid:
            return
        self._cur_aid = aid
        BR.BROWSER.open(aid, "")
        self._sync_suggested_dir(aid)
        self.empty_browser.hide()
        self._rebuild_tabs()

    def _sync_suggested_dir(self, aid: str):
        """把这个账号对应内容的配图目录设为文件对话框的起始目录。

        没预置文件、必须弹系统对话框时（内容没图 / 预置失败），
        一打开就落在配图目录里 —— 而不是「最近」列表，
        对着隐藏的 %APPDATA% 深处发呆。
        顺带把内容主题交给浏览器：选图器靠它把同题批次排最前，
        别让上一个选题的批次串题（真实踩坑：本题 8 张、别题 26 张）。
        """
        db = store.load_accounts()
        a = store.get_account(db, aid)
        if not a:
            return
        it = BUSMOD.find_item(a["platform"])
        if it is None:
            return
        content = it.content if it else {}
        topic = it.topic if it else ""
        BR.set_suggested_topic(aid, topic)
        # 解析不出（artifacts 丢 + hint 被改坏）就兜底到最新产出的图片批次 ——
        # 用户刚跑完流水线的话，那个批次就是他要的图
        # （⚠ 不能用 latest_media_dir：视频批次更新时会把图片目录顶掉；
        #   topic 给了就先按题匹配，别的题的新批次不能顶掉本题的旧批次）
        BR.set_suggested_dir(aid, PF.media_dir_of(it.artifacts if it else [], content)
                             or PF.latest_image_dir(topic=topic)
                             or PF.latest_media_dir(topic=topic))

    def _open_external(self):
        if not self._cur_aid:
            return
        import webbrowser
        page = BR.BROWSER.page(self._cur_aid)
        webbrowser.open(page.url().toString())

    # ============================================ 诊断
    def _diagnose_current(self):
        """把当前页「到底有什么」报出来。

        填不上的原因太多（没登录 / 停在视频页 / 表单还没渲染 / 页面改版），
        与其猜，不如让适配脚本自己去看一眼，把结果摆给用户。
        """
        if not self._cur_aid:
            toast(self.window(), "先打开发布页再诊断", "warn")
            return
        db = store.load_accounts()
        acc = store.get_account(db, self._cur_aid)
        if not acc:
            return
        pf = PF.get(acc["platform"]) or {}
        adapter = pf.get("adapter", "")
        if not adapter:
            toast(self.window(), f"{PF.name_of(acc['platform'])} 没有适配脚本，"
                                  "发布时走「复制到剪贴板」兜底", "info", 4000)
            return
        page = BR.BROWSER.page(self._cur_aid)
        name = PF.name_of(acc["platform"])
        toast(self.window(), f"正在诊断 {name}·{acc['name']} 的页面…", "info", 1800)

        def on_result(d: Dict[str, Any]):
            if not isinstance(d, dict):
                d = {"message": str(d)}
            if d.get("message") and not d.get("url"):
                toast(self.window(), f"诊断失败：{d['message']}", "warn", 5000)
                return
            from widgets.dialogs import MessageDialog
            head, detail = _diagnose_text(d)
            MessageDialog.alert(self.window(), f"{name} 页面诊断",
                                head, kind="info", detail=detail)

        PUB.diagnose(page, acc["platform"], adapter, on_result)

    # ============================================ 执行
    def _run(self, mode: str):
        b = BUSMOD.batch()
        accs = self._checked_accounts()
        if not b or not accs:
            toast(self.window(), "先勾选目标账号并确保有内容", "warn")
            return

        # 勾选账号里有没有「该平台本次没有专属内容」的？以前对它们静默跳过
        # （真机反馈：勾了小红书 + 抖音，只有小红书被填充，抖音毫无动静）。
        # 现在问一句：把本次内容也发过去（多平台分发），还是跳过。
        no_item = [a for a in accs if BUSMOD.find_item(a["platform"]) is None]
        reuse_ids: set = set()
        if no_item and b.items:
            src = b.items[0]
            names = "、".join(f"{PF.name_of(a['platform'])}·{a['name']}"
                              for a in no_item[:3])
            if len(no_item) > 3:
                names += f" 等 {len(no_item)} 个账号"
            from widgets.dialogs import MessageDialog
            ok = MessageDialog.confirm(
                self.window(), "有账号没有本次内容的专属版本",
                f"{names} 没有生成过本次内容的对应版本。",
                kind="ask",
                detail="「发过去」会把本次内容直接填到这些平台"
                       "（多平台分发，标题 / 正文字数按各平台规则自动截断）；\n"
                       "「跳过」则本次只处理有专属内容的账号。",
                ok_text="把本次内容也发过去", cancel_text="跳过这些账号")
            if ok:
                reuse_ids = {a["id"] for a in no_item}
            else:
                skip_ids = {a["id"] for a in no_item}
                accs = [a for a in accs if a["id"] not in skip_ids]
                if not accs:
                    toast(self.window(), "没有可执行的内容", "warn")
                    return
        elif no_item:
            accs = [a for a in accs if a["platform"] in
                    {it.platform_key for it in b.items}]
            if not accs:
                toast(self.window(), "没有可执行的内容", "warn")
                return

        # 发布前体检：有必改项就拦一下，让用户自己决定要不要硬发
        errs, warns = self._precheck_all()
        if errs:
            from widgets.dialogs import MessageDialog
            ok = MessageDialog.confirm(
                self.window(), "体检发现必改项",
                f"有 {errs} 项必改问题（另有 {warns} 项建议改）。",
                kind="warn",
                detail="必改项通常是字段超长或必填为空，直接填充很可能失败。\n"
                       "建议先点工具栏「发布前体检」看逐条说明。",
                ok_text="仍然继续", cancel_text="先去看看")
            if not ok:
                self._check_all_content(True)
                return

        if mode == "submit" and self.sw_confirm.isChecked():
            from widgets.dialogs import MessageDialog
            ok = MessageDialog.confirm(
                self.window(), "确认发布",
                f"即将向 {len(accs)} 个账号触发发布。",
                kind="ask",
                detail="请确认各平台页面内容已核对无误、账号状态正常。\n"
                       "公众号只会保存草稿，不会群发。",
                ok_text="确认发布", cancel_text="再检查一下")
            if not ok:
                return

        # 要先传素材才有编辑表单的平台（小红书图文），这次没图可传就先问一句
        if mode == "fill":
            self._ask_missing_media(accs, reuse_ids)

        missing = [a for a in accs if a["id"] not in self._opened]
        if missing:
            self._open_pages()
            toast(self.window(), "正在打开发布页，稍后自动开始…", "info", 2000)
            QTimer.singleShot(2600, lambda: self._dispatch(mode, accs, reuse_ids))
        else:
            self._dispatch(mode, accs, reuse_ids)

    def _ask_missing_media(self, accs: List[Dict[str, Any]],
                           reuse_ids: "set[str]" = frozenset()) -> None:
        """给「要先传素材才有编辑表单」的平台补配图。

        小红书图文页不上传图片就不会渲染标题 / 正文编辑框。如果这次内容没有配图，
        填充必然填不上。这里按省事程度给用户三级选择（v1.6 方案 A+B）：
          1. 找到最近产出的批次 → 问一句「自动挂上 N 张」（一步搞定，推荐）
          2. 应用内选图器（批次列表 + 缩略图，不用会找文件夹）
          3. 都不要 → 传统系统对话框选文件夹
        """
        lack: List[Dict[str, Any]] = []
        for a in accs:
            if not PF.needs_upload(a["platform"]):
                continue
            it = self._item_for(a, reuse_ids)
            if it is None:
                continue
            card = self._cards.get(a["platform"])
            content = card.content() if card else it.content
            if not PF.upload_files(a["platform"], content, it.artifacts):
                lack.append(a)
        if not lack:
            return

        names = "、".join(f"{PF.name_of(a['platform'])}·{a['name']}" for a in lack[:3])
        if len(lack) > 3:
            names += f" 等 {len(lack)} 个账号"

        # 三级定位：内容已有配图目录 → 按题匹配的**图片**批次 → 产出根目录。
        # ⚠ 不能用 latest_media_dir：视频批次（目录里只有 mp4）比图片批次新时，
        #   会把整个「自动挂图」顶掉 —— 真实踩过（视频批次晚 3 分钟）。
        # ⚠ topic 必须带上：output 下躺着多个选题的批次，只按时间挑会把
        #   别的题的图挂过来（真实踩坑：本题 8 张，别题 26 张混在一起）
        first_it = self._item_for(lack[0], reuse_ids)
        topic = first_it.topic if first_it else ""
        start = PF.media_dir_of(first_it.artifacts if first_it else [],
                                first_it.content if first_it else {}) \
            or PF.latest_image_dir(topic=topic) or config.OUTPUT_DIR

        from widgets.dialogs import MessageDialog

        # -------- A：匹配到本题批次有图 → 直接问「自动挂上」
        imgs = self._images_in(start)
        if imgs:
            leaf = os.path.basename(start.rstrip(os.sep)) or start
            ok = MessageDialog.confirm(
                self.window(), "发现刚生成的配图",
                f"{names} 的发布页要先上传图片，才会出现标题 / 正文编辑框。\n\n"
                f"匹配到本题的产出批次，有 {len(imgs)} 张图（{leaf}）。",
                kind="ask",
                detail="「自动挂上」直接把这批图作为本次配图，填充时自动上传。\n"
                       "不是这批图就选「我自己选」，会打开应用内选图器"
                       "（同题批次排最前）。",
                ok_text=f"自动挂上 {len(imgs)} 张", cancel_text="我自己选")
            if ok:
                self._attach_images(imgs, lack)
                return

        # -------- B：应用内选图器（批次列表 + 缩略图，只列含图片的批次，
        #              同题批次排最前 —— 就算建议目录定位错了也能换回来）
        try:
            from widgets.media_picker import pick_media_files
            res = pick_media_files(self.window(), start, images_only=True,
                                   topic=topic)
        except Exception:
            res = None
        if res is not None:
            files, _d = res
            if files:
                self._attach_images(files, lack)
            return   # 取消了选图器就到此为止，不再连环弹窗

        # -------- C：兜底 —— 老式系统对话框选文件夹（选图器开不起来才会到这）
        ok = MessageDialog.confirm(
            self.window(), "有账号还没配图",
            f"{names} 的发布页要先上传图片，才会出现标题 / 正文编辑框。",
            kind="ask",
            detail="选一个文件夹，里面的图片会当作这次发布的配图自动上传（推荐）。\n"
                   "选「稍后手动」也行 —— 填充时会自动帮你点开上传，"
                   "你选好图、编辑框出现后，再点一次「一键填充」即可。",
            ok_text="现在选配图", cancel_text="稍后手动")
        if not ok:
            return
        d = QFileDialog.getExistingDirectory(self.window(), "选择配图所在文件夹", start)
        if not d:
            return
        imgs = self._images_in(d)
        if not imgs:
            toast(self.window(), "这个文件夹里没有图片（png / jpg / webp / gif）", "warn")
            return
        self._attach_images(imgs, lack)

    @staticmethod
    def _images_in(d: str) -> List[str]:
        """目录下按文件名排序的图片文件；目录无效返回空。"""
        if not d or not os.path.isdir(d):
            return []
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return []
        return [os.path.join(d, n) for n in names
                if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))]

    # ============================================ 填充中途选图后的自动续跑
    def _on_files_picked(self, aid: str, files: List[str]) -> None:
        """填充中途（适配脚本已点开上传控件、选图器弹出）用户交回了文件。

        文件已经被浏览器喂给页面开始上传，但这一轮填充已按「需人工」收场。
        这里把文件回写进内容（artifacts + 卡片状态条 + image_hint），
        等页面把图传完、编辑器渲染出来后，**自动补一次填充** ——
        用户不需要再点一次「一键填充」。
        """
        db = store.load_accounts()
        acc = store.get_account(db, aid)
        if not acc or not files:
            return
        it = BUSMOD.find_item(acc["platform"])
        if it is None:
            return
        # 复用挂图回写：artifacts + 卡片状态条 + image_hint 目录行
        self._attach_images(list(files), [acc],
                            toast_msg=f"已挂上 {len(files)} 张图，"
                                      f"等页面上传完自动继续填充…")

        # 页面上传 N 张图要几秒到几十秒，先等编辑器出现再补填充。
        # 若上一轮队列还在跑（多账号场景），等它收尾再补，别把队列搅了。
        self._wait_editor_and_refill(acc)

    def _wait_editor_and_refill(self, acc: Dict[str, Any], tries: int = 0) -> None:
        """轮询页面直到编辑器渲染出来，然后对该账号补一次填充。

        为什么不直接补：图还没传完编辑器就还没出现，适配脚本只能报
        「页面还在渲染」，重试窗口（8×1.5s）对几十张图可能不够。
        这里用 diagnose 探针每 2s 看一眼，最多等 90s。
        同一账号同时只排一个续跑（hook 路径与队列失败路径都会进来）。
        """
        aid = acc["id"]
        if tries == 0:
            if aid in self._refill_pending:
                return   # 已经在等了，别排两个
            self._refill_pending.add(aid)
        if aid not in self._opened:
            self._refill_pending.discard(aid)
            return   # 标签页被关了，别再补
        if self._queue is not None:
            # 上一轮还没跑完（多账号）：2s 后再看，不算进重试次数
            QTimer.singleShot(2000, lambda: self._wait_editor_and_refill(acc, tries))
            return
        page = BR.BROWSER.page(aid)
        adapter = (PF.get(acc["platform"]) or {}).get("adapter", "")

        def done(d):
            if not isinstance(d, dict):
                d = {}
            if d.get("editor") and d.get("title"):
                self._refill_pending.discard(aid)
                toast(self.window(),
                      f"{PF.name_of(acc['platform'])}·{acc['name']} 图片已就位，自动继续填充…",
                      "info", 2600)
                self._dispatch("fill", [acc])
                return
            if tries < 45:   # 2s × 45 = 90s
                QTimer.singleShot(
                    2000, lambda: self._wait_editor_and_refill(acc, tries + 1))
                return
            # 等不到（可能页面被关了 / 上传失败了）：交回人工，别无限等
            self._refill_pending.discard(aid)
            self._update_chip(aid, "需人工",
                              "图片上传后编辑器一直没出现，请手动再点一次「一键填充」")
            toast(self.window(), "图片等了很久还没上传完，请到页面确认后再点一次「一键填充」",
                  "warn", 5000)

        PUB.diagnose(page, acc["platform"], adapter, done)

    def _attach_images(self, imgs: List[str], lack: List[Dict[str, Any]],
                       toast_msg: str = "") -> None:
        """把这批图挂到所有缺图的平台上（回写 artifacts + 卡片状态条 + hint 文本）。"""
        d = os.path.dirname(imgs[0]) if imgs else ""
        for a in lack:
            it = BUSMOD.find_item(a["platform"])
            if it is None:
                continue
            it.artifacts = list(imgs)
            # 卡片同步更新（状态条 + image_hint 文本），
            # 之后 _dispatch 里 card.content() 带出去的就是新目录
            card = self._cards.get(a["platform"])
            if card is not None and hasattr(card, "attach_media"):
                card.attach_media("image_hint", imgs)
            else:
                old = it.content.get("image_hint") or ""
                style = [ln for ln in old.splitlines()
                         if ln.strip() and "目录：" not in ln and "目录:" not in ln
                         and not ln.strip().startswith("已出图")]
                it.content["image_hint"] = "\n".join(
                    style + [f"已出图 {len(imgs)} 张，目录：{d}"])
        toast(self.window(), toast_msg or
              f"已给 {len(lack)} 个平台挂上 {len(imgs)} 张配图，填充时会自动上传", "ok")

    def _dispatch(self, mode: str, accs: List[Dict[str, Any]],
                  reuse_ids: "set[str]" = frozenset()):
        s = store.load_settings()
        db = store.load_records()
        items = []
        skipped: List[str] = []
        for a in accs:
            it = self._item_for(a, reuse_ids)
            reused = False
            if it is not None and it.platform_key != a["platform"]:
                reused = True   # 复用了别的平台的条目（本次没有专属内容）
            if not it:
                skipped.append(f"{PF.name_of(a['platform'])}·{a['name']}")
                continue
            card = self._cards.get(a["platform"])
            content = card.content() if card else it.content
            # 矩阵差异化：这个账号有专属改写版本就用它，否则用原文
            if it.has_variant(a["id"]):
                content = {**content, **it.content_for(a["id"])}
            pf = PF.get(a["platform"]) or {}

            # 预置配图：适配脚本点到页面的上传控件时，Qt 会回调 chooseFiles，
            # 那里把这里的路径交回去，浏览器就当成用户自己选了文件。
            # 找不到真实存在的文件就清掉 —— 宁可不传，也不要弹系统对话框。
            uploads: List[str] = []
            if mode == "fill":
                uploads = PF.upload_files(a["platform"], content, it.artifacts)
                # upload_files 会按平台单篇上限截断（小红书 18 张）——
                # 被截了就提醒一句，用户才知道还有几张没传
                if uploads and it.artifacts:
                    n_src = len([f for f in it.artifacts if f and os.path.exists(f)])
                    if n_src > len(uploads):
                        toast(self.window(),
                              f"{PF.name_of(a['platform'])} 单篇最多 {len(uploads)} 张，"
                              f"已自动取前 {len(uploads)} 张（其余没传）", "warn", 4200)
                if uploads:
                    BR.set_pending_upload(a["id"], uploads)
                    # artifacts 只存在内存里（重启即丢）。能解析出来就回写，
                    # 卡片状态条 / 素材库 / 下一次发布拿到的都是同一份文件列表。
                    # ⚠ 复用别平台条目时不回写 —— 那是源平台的条目，
                    #   别把按本平台上限截过的文件列表污染回去。
                    if not reused:
                        it.artifacts = list(uploads)
                else:
                    BR.clear_pending_upload(a["id"])
            # 无论这次有没有预置文件，都把建议目录与主题设好：
            # 真弹选图器 / 系统对话框（用户手动选图）时，
            # 一打开就是对的文件夹，且同题批次排最前
            BR.set_suggested_topic(a["id"], it.topic)
            BR.set_suggested_dir(a["id"], PF.media_dir_of(uploads or it.artifacts, content)
                                 or PF.latest_media_dir(topic=it.topic or ""))

            rec = store.add_record(
                db, topic=it.topic, platform=a["platform"],
                platform_name=PF.name_of(a["platform"]),
                account_id=a["id"], account_name=a["name"],
                status="填充中" if mode == "fill" else "发布中",
            )
            items.append({
                "record_id": rec["id"],
                "platform_key": a["platform"],
                "platform_name": PF.name_of(a["platform"]),
                "account_id": a["id"],
                "adapter": pf.get("adapter", ""),
                "payload": PUB.payload_of(content, it.topic),
                "topic": it.topic,
                # 这个平台要不要「先传素材才有编辑表单」。
                # 与下面有几个文件要传是两回事：小红书图文页即使没配图，
                # 也得先把上传对话框点开（让用户选图），编辑框才会出现。
                "want_upload": PF.needs_upload(a["platform"]),
                # 有几个文件要传。发布队列只在**第一次尝试**时把它交给适配脚本，
                # 重试时置 0 —— 否则重试会把同一批图重复传一遍。
                "upload_count": len(uploads),
            })

        if not items:
            toast(self.window(), "没有可执行的内容", "warn")
            return
        if skipped:
            toast(self.window(),
                  "、".join(skipped[:3]) + " 没有可用的内容，本次已跳过", "warn", 4200)

        # 记下**实际参与执行**的账号顺序 —— _on_step 按索引把浏览器切到
        # 正在填充的账号，用勾选列表当索引会错位（勾选数 ≥ 任务数时）
        self._dispatched_items = items

        self._mode = mode
        self._db_records = db
        self.prog_box.setVisible(True)
        self.prog.setMaximum(len(items))
        self.prog.setValue(0)
        self.btn_fill.setEnabled(False)
        self.btn_publish.setEnabled(False)
        for it in items:
            self._update_chip(it["account_id"], "填充中" if mode == "fill" else "发布中")

        q = PUB.PublishQueue(lambda aid: BR.BROWSER.page(aid), self)
        q.step.connect(self._on_step)
        q.item_done.connect(self._on_item_done)
        q.all_done.connect(self._on_all_done)
        self._queue = q
        q.run(items, mode=mode,
              interval=int(s.get("publish_interval", 8)) if mode == "submit" else 1)

    def _on_step(self, idx: int, total: int, text: str):
        self.lb_prog.setText(text)
        self.prog.setValue(idx - 1)
        # 填充/发布到哪个账号，就把浏览器切到哪个标签 —— 让用户看得见内容进了哪里。
        # 用 _dispatch 实际构建的任务列表当索引：勾选账号可能有被跳过的，
        # 用勾选列表对索引会切错标签页。
        disp = getattr(self, "_dispatched_items", None) or []
        if 0 < idx <= len(disp):
            self._select(disp[idx - 1]["account_id"])

    def _on_item_done(self, record_id: str, ok: bool, message: str, meta=None):
        self.prog.setValue(self.prog.value() + 1)
        meta = meta or {}
        # 「需要人工介入」不是失败：页面要求手动选图之类，脚本已经把能做的做了。
        # 显示成「需人工」，用户才不会以为程序坏了。
        if ok:
            status = "已填充" if self._mode == "fill" else "已发布"
        elif meta.get("manual"):
            status = "需人工"
        else:
            status = "失败"
        store.update_record(self._db_records, record_id, {"status": status, "message": message})
        rec = next((r for r in self._db_records.get("records", [])
                    if r["id"] == record_id), None)
        if rec:
            aid = rec.get("account_id", "")
            # 存下来：跑完时 _rebuild_status_chips() 会重建所有 chip，
            # 不存就会被平台级的「待填充」冲掉（之前的 bug）。
            self._last_result[aid] = (status, message or "")
            self._update_chip(aid, status, message or "")
            # 填充项是「图还在传 / 页面还在渲染」超时的：图传完会自动续跑，
            # 用户不用再点一次（预置路径的自动续跑 —— 中途选图路径走 hook）。
            if (not ok and self._mode == "fill"
                    and meta.get("stage") in ("upload", "wait", "switch")):
                db2 = store.load_accounts()
                acc = store.get_account(db2, aid)
                if acc:
                    self._wait_editor_and_refill(acc)
        BUS.records_changed.emit()

    def _on_all_done(self, all_ok: bool):
        self.prog_box.setVisible(False)
        self._update_summary()
        self._queue = None
        for a in self._checked_accounts():
            BR.clear_pending_upload(a["id"])
        if all_ok:
            if self._mode == "fill":
                self._set_step(2)
                toast(self.window(),
                      "内容已填入各平台发布页 —— 请在右侧浏览器里逐条核对，确认无误后点「一键发布」",
                      "ok", 5000)
            else:
                self._set_step(3)
                toast(self.window(), "全部发布完成", "ok", 3000)
        else:
            toast(self.window(), "部分账号未完成，点底部结果条上的条目看具体说明", "warn", 4000)
        self._refresh_card_status()
        self._rebuild_status_chips()

    def _refresh_card_status(self):
        db = store.load_records()
        latest: Dict[str, str] = {}
        for r in db.get("records", []):
            pk = r.get("platform")
            if pk and pk not in latest:
                latest[pk] = r.get("status", "")
        for pk, card in self._cards.items():
            st = latest.get(pk)
            if st == "已填充":
                card.set_status("已填充", "ok")
            elif st == "已发布":
                card.set_status("已发布", "ok")
            elif st == "失败":
                card.set_status("失败", "err")

    def _stop(self):
        if self._queue:
            self._queue.stop()
        self.prog_box.setVisible(False)
        for a in self._checked_accounts():
            BR.clear_pending_upload(a["id"])
        self._update_summary()
        toast(self.window(), "已停止", "info")

    def _precheck_all(self) -> tuple:
        """对全部卡片跑体检，返回 (必改数, 建议改数)。"""
        errs = warns = 0
        for c in self._cards.values():
            c.run_precheck(show_dialog=False)
            for i in c.precheck_issues():
                if i.level == "err":
                    errs += 1
                elif i.level == "warn":
                    warns += 1
        return errs, warns

    def _check_all_content(self, show: bool = True):
        errs, warns = self._precheck_all()
        if not self._cards:
            toast(self.window(), "还没有内容", "warn")
            return
        if not errs and not warns:
            toast(self.window(), "全部内容体检通过", "ok")
            return
        if show:
            from views.precheck_dialog import PrecheckDialog
            issues = []
            for c in self._cards.values():
                issues.extend(c.precheck_issues())
            import compliance
            hits = {}
            for c in self._cards.values():
                h = compliance.check_content(c.content())
                for k, v in h.items():
                    hits.setdefault(k, []).extend(v)
            PrecheckDialog.show_for(self.window(), "", issues, hits)
        else:
            toast(self.window(),
                  f"体检：{errs} 项必改、{warns} 项建议改", "warn", 4000)
