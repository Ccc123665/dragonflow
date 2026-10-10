"""左侧账号矩阵面板。

设计要点
  · 可折叠：收起后主界面留出全部宽度（发布工作台要放大的浏览器区很吃宽度）
  · 平台行可点：点平台名展开/收起，点「打开」直接进该平台发布页（没账号则引导添加）
  · 账号行可点：点一行直接打开该账号的发布页；右键出管理菜单
  · 全部用自绘行，不再用 QTreeWidget —— 为了拿到完整的悬停态与行内按钮
"""
from typing import Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QScrollArea, QVBoxLayout, QWidget,
)

import icons
import platforms as PF
import store
import theme
from widgets.common import Badge, IconButton, Pill, TagDot


def _dot_pixmap(color: str, size: int = 9) -> QPixmap:
    pm = QPixmap(size * 3, size * 3)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(0, 0, size * 3, size * 3)
    p.end()
    pm.setDevicePixelRatio(3)
    return pm


class AccountRow(QFrame):
    """单个账号行：状态点 + 名称 + 状态。点一行即打开该账号的发布页。

    行尾有两个按钮（悬停才出现）：打开发布页、编辑（改名）。
    改名以前只能右键 → 编辑账号，藏得太深，用户根本找不到 ——
    现在给一个明确的铅笔按钮。
    """

    open_requested = pyqtSignal(str)      # aid
    edit_requested = pyqtSignal(str)      # aid
    menu_requested = pyqtSignal(str, object)   # aid, global pos

    def __init__(self, acc: dict, parent=None):
        super().__init__(parent)
        self.acc = acc
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(32)
        status = acc.get("status", "正常")
        logged = bool(acc.get("logged_in"))
        # 没登录过的账号不能看起来和正常账号一样 —— 否则用户会以为它是可用的，
        # 一路填到发布才发现要扫码。状态点用灰色，并挂一个「未登录」小标。
        if status == "正常" and not logged:
            color = theme.TEXT_4
        else:
            color = theme.STATUS_COLORS.get(status, theme.TEXT_4)
        self.setStyleSheet(
            "QFrame{background:transparent;border-radius:7px;}"
            f"QFrame:hover{{background:{theme.BG_HOVER};}}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 0, 6, 0)
        lay.setSpacing(8)

        dot = QLabel()
        dot.setFixedSize(9, 9)
        dot.setPixmap(_dot_pixmap(color))
        lay.addWidget(dot)

        name = QLabel(acc.get("name", ""))
        name.setStyleSheet(
            f"background:transparent;{theme.css_font(13, 500)}"
            f"color:{theme.TEXT_1 if acc.get('logged_in') else theme.TEXT_2};")
        name.setToolTip(self._tip())
        lay.addWidget(name, 1)

        if status != "正常":
            lay.addWidget(Pill(status, color, theme.BG_INPUT))
        elif not logged:
            lay.addWidget(Pill("未登录", theme.TEXT_3, theme.BG_INPUT))

        self.btn_edit = IconButton("edit", "编辑账号（可改名字、人设、分组）", 22, 12)
        self.btn_edit.clicked.connect(lambda: self.edit_requested.emit(self.acc["id"]))
        self.btn_edit.setVisible(False)
        lay.addWidget(self.btn_edit)

        self.btn_open = IconButton("external", "打开发布页", 22, 12)
        self.btn_open.clicked.connect(lambda: self.open_requested.emit(self.acc["id"]))
        self.btn_open.setVisible(False)
        lay.addWidget(self.btn_open)

    def _tip(self) -> str:
        parts = [f"{PF.name_of(self.acc.get('platform',''))} · {self.acc.get('status','正常')}"]
        if not self.acc.get("logged_in"):
            parts.append("未登录 —— 点这一行打开发布页扫码，登录后会自动标记")
        if self.acc.get("nickname"):
            parts.append(f"昵称：{self.acc['nickname']}")
        if self.acc.get("group"):
            parts.append(f"分组：{self.acc['group']}")
        if self.acc.get("persona"):
            parts.append(f"人设：{self.acc['persona']}")
        if self.acc.get("note"):
            parts.append(f"备注：{self.acc['note']}")
        parts.append("（鼠标移到这一行 → 点铅笔可改名；右键也有「编辑账号」）")
        return "\n".join(parts)

    def enterEvent(self, ev):
        self.btn_open.setVisible(True)
        self.btn_edit.setVisible(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.btn_open.setVisible(False)
        self.btn_edit.setVisible(False)
        super().leaveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.acc["id"])
        elif ev.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.acc["id"],
                                     self.mapToGlobal(ev.position().toPoint()))
        super().mouseReleaseEvent(ev)


class PlatformGroup(QWidget):
    """一个平台分组：可展开/收起的标题行 + 账号行。"""

    open_platform = pyqtSignal(str)        # platform key → 打开登录页
    add_account = pyqtSignal(str)          # platform key
    open_account = pyqtSignal(str)         # aid
    edit_account = pyqtSignal(str)         # aid
    account_menu = pyqtSignal(str, object)

    def __init__(self, platform: dict, accounts: List[dict], expanded: bool = True,
                 parent=None):
        super().__init__(parent)
        self.platform = platform
        self._expanded = expanded

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(1)

        # ---------------- 平台标题行
        self.head = QFrame()
        self.head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.setFixedHeight(32)
        self.head.setStyleSheet(
            "QFrame{background:transparent;border-radius:7px;}"
            f"QFrame:hover{{background:{theme.BG_HOVER};}}"
        )
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(6, 0, 6, 0)
        hl.setSpacing(7)

        self.chev = IconButton("chevron_down", "展开 / 收起", 20, 12)
        self.chev.clicked.connect(self.toggle)
        hl.addWidget(self.chev)

        hl.addWidget(TagDot(PF.short_of(platform["key"]),
                            PF.color_of(platform["key"]), size=18))

        nm = QLabel(platform["name"])
        nm.setStyleSheet(f"background:transparent;{theme.css_font(13, 600)}color:{theme.TEXT_1};")
        hl.addWidget(nm)

        self.badge = Badge(str(len(accounts)))
        if accounts:
            self.badge.set_color(theme.PRIMARY, theme.PRIMARY_TINT)
        hl.addWidget(self.badge)
        hl.addStretch(1)

        self.btn_open = IconButton("external", f"打开{PF.name_of(platform['key'])}发布页", 22, 12)
        self.btn_open.clicked.connect(lambda: self.open_platform.emit(platform["key"]))
        hl.addWidget(self.btn_open)

        self.btn_add = IconButton("plus", f"新增{PF.name_of(platform['key'])}账号", 22, 13)
        self.btn_add.clicked.connect(lambda: self.add_account.emit(platform["key"]))
        hl.addWidget(self.btn_add)

        root.addWidget(self.head)

        # ---------------- 账号行
        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(16, 1, 0, 1)
        bl.setSpacing(1)
        if accounts:
            for a in accounts:
                row = AccountRow(a)
                row.open_requested.connect(self.open_account.emit)
                row.edit_requested.connect(self.edit_account.emit)
                row.menu_requested.connect(self.account_menu.emit)
                bl.addWidget(row)
        else:
            hint = QLabel("还没有账号，点右侧 + 添加")
            hint.setStyleSheet(
                f"background:transparent;{theme.css_font(11.5)}color:{theme.TEXT_4};"
                f"padding:6px 2px;")
            bl.addWidget(hint)
        root.addWidget(self.body)

        self.head.mouseReleaseEvent = self._head_click
        self.head.setToolTip(f"点这一行直接打开{PF.name_of(platform['key'])}发布页；"
                             f"点左侧箭头展开 / 收起账号列表")
        self.body.setVisible(expanded)

    def _head_click(self, ev):
        # 点平台名 = 打开发布页（用户的直觉动作）；展开/收起交给左侧箭头
        if ev.button() == Qt.MouseButton.LeftButton:
            self.open_platform.emit(self.platform["key"])

    def toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.chev.set_icon_name("chevron_down" if self._expanded else "chevron_right")

    @property
    def expanded(self) -> bool:
        return self._expanded


class Sidebar(QWidget):
    open_account = pyqtSignal(str, str)      # (aid, url)
    account_changed = pyqtSignal()           # 账号数据有变动
    collapse_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 宽度交给 MainWindow 用 min/max 动画控制。
        # ⚠ 这里**不要**设 minimumWidth —— 它会把收起动画顶住，
        #   maximumWidth 归 0 了但控件实际宽度纹丝不动。
        self._db = store.load_accounts()
        self._filter = ""
        self._expanded_state: Dict[str, bool] = {}

        root = QVBoxLayout(self)
        # 右边距 12px 是给分界线上的收起手柄留的：手柄 20px 宽、骑在分界线上，
        # 只有 10px 探进侧栏里，正好落在这条边距上、压不到账号行右侧的「+」。
        # （以前手柄贴底，底部才要额外留 62px 让它别压住最后一栏；现在手柄竖向居中，
        #   那条底边距已经没有理由了。）
        root.setContentsMargins(12, 14, 12, 14)
        root.setSpacing(10)

        # ---------------- 标题行
        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel("账号矩阵")
        title.setObjectName("SideTitle")
        head.addWidget(title)
        self.lb_total = Badge("0")
        head.addWidget(self.lb_total)
        head.addStretch(1)
        # 收起侧栏：放在标题行里，**看得见、点得到**。
        # 之前只有浮在分界线贴底的那个渐变手柄，位置太低太淡，
        # 用户的原话是「不起作用，没有箭头」—— 所以这里补一个明确的按钮。
        self.btn_collapse = IconButton("chevron_left", "收起账号矩阵", 26, 15)
        self.btn_collapse.clicked.connect(self.collapse_requested.emit)
        head.addWidget(self.btn_collapse)
        self.btn_add = IconButton("plus", "添加账号", 26, 15)
        self.btn_add.clicked.connect(self._on_add)
        head.addWidget(self.btn_add)
        root.addLayout(head)

        # ---------------- 搜索
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索账号")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._on_search)
        root.addWidget(self.search)

        # ---------------- 账号分组
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        self.box = QWidget()
        self.box_lay = QVBoxLayout(self.box)
        self.box_lay.setContentsMargins(0, 0, 0, 0)
        self.box_lay.setSpacing(6)
        self.scroll.setWidget(self.box)

        self.reload()

    # ---------------------------------------------------------- 数据
    def reload(self):
        self._db = store.load_accounts()
        self._build()

    def _build(self):
        theme.clear_layout(self.box_lay)
        kw = self._filter.strip().lower()
        total = 0
        for pf in PF.enabled_platforms():
            accs = store.accounts_of(self._db, pf["key"])
            if kw:
                accs = [a for a in accs
                        if kw in a["name"].lower()
                        or kw in (a.get("nickname") or "").lower()]
            total += len(accs)
            if kw and not accs:
                continue
            group = PlatformGroup(pf, accs,
                                  expanded=self._expanded_state.get(pf["key"], True))
            group.open_platform.connect(self._open_platform)
            group.add_account.connect(self._add_for)
            group.open_account.connect(self._open_by_id)
            group.edit_account.connect(self._edit)
            group.account_menu.connect(self._on_account_menu)
            self.box_lay.addWidget(group)
        self.lb_total.setText(str(total))

        if total == 0 and not kw:
            hint = QLabel("还没有账号\n点右上角 + 添加第一个")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_4};"
                f"padding:26px 6px;")
            self.box_lay.addWidget(hint)
        self.box_lay.addStretch(1)

    def _remember(self):
        """记住当前各分组的展开状态，重建后不丢。"""
        for g in self.box.findChildren(PlatformGroup):
            self._expanded_state[g.platform["key"]] = g.expanded

    def _on_search(self, text: str):
        self._remember()
        self._filter = text
        self._build()

    # ---------------------------------------------------------- 打开
    def _open_platform(self, platform_key: str):
        """打开某平台的发布页：取该平台第一个账号；没有账号就引导添加。"""
        accs = store.accounts_of(self._db, platform_key)
        name = PF.name_of(platform_key)
        if not accs:
            from widgets.common import toast
            toast(self.window(),
                  f"还没有{name}账号，先添加一个，之后点这里就能直接打开发布页",
                  "warn", 3600)
            self._add_for(platform_key)
            return
        pf = PF.get(platform_key) or {}
        self.open_account.emit(accs[0]["id"], pf.get("publish_url", ""))

    def _open_by_id(self, aid: str):
        acc = store.get_account(self._db, aid)
        if not acc:
            return
        pf = PF.get(acc["platform"]) or {}
        self.open_account.emit(aid, pf.get("publish_url", ""))

    # ---------------------------------------------------------- 账号操作
    def _on_add(self):
        from views.account_dialog import AccountDialog
        dlg = AccountDialog(self.window(), None)
        if dlg.exec():
            self.reload()
            self.account_changed.emit()

    def _add_for(self, platform_key: str):
        from views.account_dialog import AccountDialog
        dlg = AccountDialog(self.window(), None, platform_key)
        if dlg.exec():
            self.reload()
            self.account_changed.emit()

    def _on_account_menu(self, aid: str, pos):
        acc = store.get_account(self._db, aid)
        if not acc:
            return
        pf = PF.get(acc["platform"]) or {}
        menu = QMenu(self)

        a1 = QAction("打开发布页", self)
        a1.triggered.connect(lambda: self.open_account.emit(aid, pf.get("publish_url", "")))
        a2 = QAction("打开后台首页", self)
        a2.triggered.connect(lambda: self.open_account.emit(aid, pf.get("home_url", "")))
        a3 = QAction("编辑账号", self)
        a3.triggered.connect(lambda: self._edit(aid))
        menu.addAction(a1)
        menu.addAction(a2)
        menu.addSeparator()
        menu.addAction(a3)

        sub = menu.addMenu("标记状态")
        for s in store.ACCOUNT_STATUS:
            act = QAction(s, self)
            act.triggered.connect(lambda _=False, s=s: self._set_status(aid, s))
            sub.addAction(act)

        menu.addSeparator()
        a5 = QAction("清除登录态（退出登录）", self)
        a5.triggered.connect(lambda: self._clear_login(aid))
        a6 = QAction("删除账号", self)
        a6.triggered.connect(lambda: self._delete(aid))
        menu.addAction(a5)
        menu.addAction(a6)
        menu.exec(pos)

    def _edit(self, aid: str):
        from views.account_dialog import AccountDialog
        dlg = AccountDialog(self.window(), aid)
        if dlg.exec():
            self.reload()
            self.account_changed.emit()

    def _set_status(self, aid: str, status: str):
        store.update_account(self._db, aid, {"status": status})
        self.reload()

    def _clear_login(self, aid: str):
        from browser import BROWSER
        BROWSER.clear_profile(aid)
        store.update_account(self._db, aid, {"logged_in": False})
        store.log(f"清除登录态：{aid}")
        self.reload()
        from widgets.common import toast
        toast(self.window(), "已清除该账号的登录态与缓存", "ok")

    def _delete(self, aid: str):
        from widgets.dialogs import MessageDialog
        acc = store.get_account(self._db, aid)
        if not acc:
            return
        ok = MessageDialog.confirm(
            self.window(), "删除账号",
            f"确定删除「{acc['name']}」吗？",
            kind="err",
            detail="该账号的本地登录态也会一并清除，此操作不可撤销。",
            ok_text="删除", cancel_text="取消", destructive=True)
        if not ok:
            return
        from browser import BROWSER
        BROWSER.clear_profile(aid)
        store.delete_account(self._db, aid)
        store.log(f"删除账号：{acc['name']}")
        self.reload()
        self.account_changed.emit()
