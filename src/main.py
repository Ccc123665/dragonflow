"""DragonFlow 一条龙 · 入口与主窗口。

启动顺序很重要：必须在导入任何 PyQt6 模块之前决定 Chromium 启动参数，
否则硬件加速开关不会生效。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config  # noqa: E402


# ---------------------------------------------------------------- 早期环境
def _early_flags() -> None:
    """在导入 PyQt 之前读设置，决定 Chromium 启动参数。"""
    accel = False
    try:
        import json
        if os.path.exists(config.SETTINGS_FILE):
            with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
                accel = bool(json.load(f).get("hardware_accel", False))
    except Exception:
        accel = False

    flags = ["--disable-dev-shm-usage", "--disable-features=Translate"]
    if os.name != "nt" and sys.platform != "darwin":
        flags.append("--no-sandbox")
    if not accel:
        flags.append("--disable-gpu")
        flags.append("--disable-software-rasterizer")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


_early_flags()

from PyQt6.QtCore import (  # noqa: E402
    QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QRect, Qt, QTimer,
)
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

import browser as BR  # noqa: E402
import icons  # noqa: E402
import store  # noqa: E402
import theme  # noqa: E402
from bus import BUS  # noqa: E402
from widgets.common import (  # noqa: E402
    GradientHandle, SegmentedControl, SideEdge, TitleBar, toast,
)
from widgets.sidebar import Sidebar  # noqa: E402
from widgets.window_kit import WindowResizer  # noqa: E402
from views.dashboard import DashboardView  # noqa: E402
from views.library import LibraryView  # noqa: E402
from views.records import RecordsView  # noqa: E402
from views.settings_view import SettingsView  # noqa: E402
from views.studio import StudioView  # noqa: E402
from views.workbench import WorkbenchView  # noqa: E402

NAV = [
    ("studio", "内容工坊", "studio"),
    ("workbench", "发布工作台", "send"),
    ("library", "素材库", "folder"),
    ("records", "发布记录", "clock"),
    ("dashboard", "数据看板", "target"),
]

# 视图在 QStackedWidget 里的顺序，必须和 NAV 一致，settings 放最后
VIEW_ORDER = ["studio", "workbench", "library", "records", "dashboard", "settings"]

SIDEBAR_W = 244
# 只有发布工作台需要账号矩阵；其余页面把宽度让给内容本身
VIEWS_WITH_SIDEBAR = {1}
# 侧栏收起后给浮动手柄留的左侧空隙（见 _apply_gutter）
COLLAPSED_GUTTER = 30

# 窗口的期望初始尺寸 / 最小尺寸。期望值只是「想开多大」，
# 屏幕放不下时会被 _fit_to_screen 压到可用区以内（见那里的注释）。
WANT_W, WANT_H = 1440, 940
MIN_W, MIN_H = 1040, 680
# 初始窗口与屏幕可用区之间留的边距，别贴着任务栏 / 屏幕边
SCREEN_MARGIN = 24


class RootFrame(QFrame):
    """承载全部内容的外框。"""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.setObjectName("RootFrame")
        self.win = win
        self.resizer = None

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.resizer is not None:
            self.resizer.relayout()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        # 初始尺寸 / 位置必须按**屏幕可用区**算（扣掉任务栏），不能直接 resize(1440,940)。
        # 1366×768 的笔记本上可用区只有 1366×728，直接按 1440×940 开会话窗口
        # 底边整条藏到任务栏下面，最下面那排控件点不到。
        self._fit_to_screen()
        # 应用图标：不设的话任务栏上是一个默认的空白方块（用户原话「太原始」）
        self._apply_icon()

        self.root = RootFrame(self)
        self.setCentralWidget(self.root)

        lay = QVBoxLayout(self.root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---------------- 顶部：标题栏 + 主导航 + 设置（合并成一条）
        self.title_bar = TitleBar(self)
        self.title_bar.minimize.connect(self.showMinimized)
        self.title_bar.maximize.connect(self._toggle_max)
        self.title_bar.close.connect(self.close)

        self.seg = SegmentedControl([(k, t) for k, t, _ in NAV],
                                    on_change=self._on_nav)
        self.title_bar.center_lay.addWidget(self.seg)

        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("Soft")
        self.btn_settings.setMinimumHeight(32)
        self.btn_settings.setIcon(icons.icon("gear", theme.TEXT_2, 15))
        self.btn_settings.clicked.connect(lambda: self._on_nav("settings"))
        self.title_bar.add_action(self.btn_settings)
        lay.addWidget(self.title_bar)

        # ---------------- 主体
        self.body = QWidget()
        bl = QHBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.body_lay = bl
        lay.addWidget(self.body, 1)

        self.sidebar = Sidebar(self)
        self.sidebar.open_account.connect(self._open_account)
        # 账号 / 平台有变动统一走全局总线，让所有视图（含内容工坊的平台芯片）
        # 都能收到通知；这里不再直连 _on_accounts_changed，否则会跑两遍。
        self.sidebar.account_changed.connect(BUS.accounts_changed.emit)
        self.sidebar.collapse_requested.connect(lambda: self._set_sidebar(False))
        self.sidebar.setMinimumWidth(SIDEBAR_W)
        self.sidebar.setMaximumWidth(SIDEBAR_W)
        bl.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        bl.addWidget(self.stack, 1)

        # 侧栏收起手柄：骑在侧栏与内容区的分界线上（贴底），细长渐变胶囊。
        # 放在 body 里而不是侧栏里 —— 收起后侧栏宽度为 0，手柄必须还能点到。
        self.handle = GradientHandle(self.body)
        self.handle.clicked.connect(self._toggle_sidebar)
        self.handle.hide()

        # 侧栏右缘的渐变指示线：比一个孤零零的按钮含蓄，暗示「这条边可以收」
        self.side_edge = SideEdge(self.body)
        self.side_edge.hide()

        self.studio_view = StudioView(self)
        self.workbench_view = WorkbenchView(self)
        self.library_view = LibraryView(self)
        self.records_view = RecordsView(self)
        self.dashboard_view = DashboardView(self)
        self.settings_view = SettingsView(self)
        for v in (self.studio_view, self.workbench_view, self.library_view,
                  self.records_view, self.dashboard_view, self.settings_view):
            self.stack.addWidget(v)

        BUS.goto_workbench.connect(self._goto_workbench)
        # 内容工坊的「管理 / 上传能力」→ 跳到设置页（tab 参数暂时忽略：
        # 设置页是单页滚动，没有分 tab）
        BUS.goto_settings.connect(lambda _tab="": self._on_nav("settings"))
        BUS.accounts_changed.connect(self._on_accounts_changed)

        # 侧栏宽度动画：minimumWidth 和 maximumWidth 必须一起动。
        # 只动 maximumWidth 会被控件自身的最小宽度顶住，看起来「点了没反应」。
        self._side_anims = []
        self._side_anim = QParallelAnimationGroup(self)
        for _prop in (b"minimumWidth", b"maximumWidth"):
            _a = QPropertyAnimation(self.sidebar, _prop)
            _a.setDuration(200)
            _a.setEasingCurve(QEasingCurve.Type.OutCubic)
            # 动画过程中也让手柄 / 边线跟着走，否则它们只在动画结束时「跳」一下。
            # （QParallelAnimationGroup 本身没有 valueChanged，得挂在子动画上）
            _a.valueChanged.connect(lambda _v: self._place_handle())
            self._side_anim.addAnimation(_a)
            self._side_anims.append(_a)
        self._side_anim.finished.connect(self._on_side_anim_done)
        self._side_open = True

        # 手柄不在布局里，是浮在分界线上的。**必须在 body 真正改过尺寸之后再摆**——
        # 窗口 resizeEvent 里读 self.body.height() 拿到的是旧值（Qt 的布局是
        # 事件循环稍后才激活的），窗口一变小手柄就会被摆到屏幕外，
        # 用户看到的就是「收不起来、也没有箭头」。挂在 body 的 Resize 上最可靠。
        self.body.installEventFilter(self)

        self.stack.setCurrentIndex(0)
        self._sync_sidebar_visibility()
        QTimer.singleShot(300, self._welcome)

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "body", None) and ev.type() == ev.Type.Resize:
            self._place_handle()
        return super().eventFilter(obj, ev)

    def _fit_to_screen(self):
        """把初始尺寸与位置收进屏幕的**可用区**（已扣掉任务栏），并居中。

        为什么不能直接 `resize(1440, 940)`：
        可用区是 `availableGeometry()`，任务栏占掉的那 40px 不算在里面。
        在 1366×768 的机器上可用区只有 1366×728 —— 窗口比它高一截，
        Windows 会把窗口往下压住标题栏，于是**底边整条藏到任务栏下面**，
        最下面那排控件（导航 / 按钮 / 结果条）全都点不到。

        做法：拿可用区取交集，宽高都不超过「可用区 − 2×边距」，
        最小尺寸也跟着一起压（否则 `setMinimumSize` 会把窗口重新顶出屏幕）。
        """
        scr = self.screen() or QApplication.primaryScreen()
        avail = (scr.availableGeometry() if scr is not None
                 else QRect(0, 0, WANT_W, WANT_H))
        w = min(WANT_W, max(360, avail.width() - 2 * SCREEN_MARGIN))
        h = min(WANT_H, max(300, avail.height() - 2 * SCREEN_MARGIN))
        # ⚠ 顺序：先压最小尺寸，再 resize。反过来的话 resize 会被旧的最小值顶回去。
        self.setMinimumSize(min(MIN_W, w), min(MIN_H, h))
        x = avail.x() + max(0, (avail.width() - w) // 2)
        y = avail.y() + max(0, (avail.height() - h) // 2)
        # 无边框窗口没有系统标题栏，setGeometry 就是最终结果，不需要补偿 frame
        self.setGeometry(x, y, w, h)

    def _apply_icon(self):
        """窗口 / 任务栏图标。

        只调 setWindowIcon 在 Windows 上**不够** —— 任务栏会按 python.exe 归组，
        显示的仍是 Python 的图标。必须同时声明 AppUserModelID，
        Windows 才会把它当成独立应用，用我们自己的图标。
        """
        try:
            from PyQt6.QtGui import QIcon
            if os.path.exists(config.APP_ICON):
                self.setWindowIcon(QIcon(config.APP_ICON))
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "DragonFlow.OneLine")
            except Exception:
                pass

    # ---------------------------------------------------------- 侧栏
    def _set_sidebar(self, open_: bool):
        self._side_open = open_
        end = SIDEBAR_W if open_ else 0
        cur = self.sidebar.width() or self.sidebar.maximumWidth()
        self._side_anim.stop()
        for a in self._side_anims:
            a.setStartValue(cur)
            a.setEndValue(end)
        self._side_anim.start()
        self.handle.set_open(open_)

    def _toggle_sidebar(self):
        self._set_sidebar(not self._side_open)

    def _on_side_anim_done(self):
        """收起 / 展开动画结束：补上左侧空隙，再摆一次手柄。"""
        self._apply_gutter()
        self._place_handle()

    def _apply_gutter(self):
        """收起侧栏后，在内容区左侧留一条窄空隙给手柄。

        手柄是浮层。收起后侧栏宽度归 0，手柄就只能压在内容区上 ——
        而内容区里是 QWebEngineView，浮层压在上面既可能被盖住、点击也可能被吞掉，
        用户就再也展不开侧栏了。留一条 gutter 让手柄完全落在空隙里，从根上避开。
        """
        need = self.stack.currentIndex() in VIEWS_WITH_SIDEBAR
        g = COLLAPSED_GUTTER if (need and not self._side_open) else 0
        self.body_lay.setContentsMargins(g, 0, 0, 0)

    def _sync_sidebar_visibility(self):
        """账号矩阵只在发布工作台出现。"""
        need = self.stack.currentIndex() in VIEWS_WITH_SIDEBAR
        w = (SIDEBAR_W if self._side_open else 0) if need else 0
        self.sidebar.setVisible(need)
        self.sidebar.setMinimumWidth(w)
        self.sidebar.setMaximumWidth(w)
        self.handle.setVisible(need)
        self.handle.set_open(self._side_open)
        self.side_edge.setVisible(need and self._side_open)
        self._apply_gutter()
        self._place_handle()

    def _place_handle(self):
        """把手柄摆在侧栏与内容区分界线的**竖向中点**上；渐变边线贴着侧栏右缘。

        以前是贴底的（`body.height() - hh - inset`）。贴底有两个毛病：
          · 视觉上像「掉到角落里的一颗扣子」，跟侧栏这个整体没关系；
          · 底部只要有东西（工作台的「执行结果」条、状态栏）就得往上让，
            让多少得靠 `bottom_bar_height()` 估 —— 一改布局就会压住它。
        改成居中之后两个问题一起消失：中点永远空着，也不用再管底部有什么。
        """
        if not hasattr(self, "handle"):
            return
        if hasattr(self, "side_edge"):
            self.side_edge.setGeometry(
                max(0, self.sidebar.width() - SideEdge.W), 0,
                SideEdge.W, self.body.height())
            self.side_edge.raise_()
        hw = self.handle.width()
        hh = self.handle.height()
        # 侧栏还够宽就骑在分界线上；已经收窄了（或本来就是收起的）就落进
        # _apply_gutter 留出的空隙里，绝不压在网页视图上
        if self.sidebar.width() > hw:
            x = self.sidebar.width() - hw // 2
        else:
            x = max(2, (COLLAPSED_GUTTER - hw) // 2)
        x = max(2, min(x, self.body.width() - hw - 4))
        # 竖向居中。用 body 的高度（不是窗口高度）—— 顶部那条标题栏 / 导航不在 body 里，
        # 按窗口高度算会整体偏下。
        y = max(8, (self.body.height() - hh) // 2)
        self.handle.move(x, y)
        self.handle.raise_()

    # ---------------------------------------------------------- 导航
    def _on_nav(self, key: str):
        idx = VIEW_ORDER.index(key) if key in VIEW_ORDER else 0
        if key != "settings":
            self.seg.set_index([k for k, _, _ in NAV].index(key), notify=False)
        self.stack.setCurrentIndex(idx)
        self._sync_sidebar_visibility()
        if key == "workbench":
            self.workbench_view.reload_drafts()
        elif key == "library":
            self.library_view.reload()
        elif key == "records":
            self.records_view.reload()
        elif key == "dashboard":
            self.dashboard_view.reload()
        theme.fade_in(self.stack.currentWidget(), 160)

    def _goto_workbench(self):
        """只负责导航。

        要不要把内容同步过去，由**发起方**决定：
          · 内容工坊点「去发布 →」→ 自己先 push_to_batch 再发这个信号
          · 素材库点「复用到发布工作台」→ 自己 set_batch 再发这个信号

        以前这里无条件调 `studio.push_to_batch()`，而工坊的 push 是「用卡片
        重建整个批次」—— 从素材库复用时工坊里没有卡片，于是刚设好的草稿被
        一个空批次覆盖，工作台和「待发布内容」里什么都看不到。
        """
        self._on_nav("workbench")

    # ---------------------------------------------------------- 账号
    def _open_account(self, aid: str, url: str):
        BR.BROWSER.open(aid, url)
        self._on_nav("workbench")
        self.workbench_view.open_account(aid)

    def _on_accounts_changed(self):
        self.sidebar.reload()
        self.workbench_view.reload_drafts()

    # ---------------------------------------------------------- 窗口
    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(60, lambda: self.root.resizer and self.root.resizer.relayout())

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange:
            QTimer.singleShot(0, lambda: self.root.resizer and self.root.resizer.relayout())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 侧栏手柄跟着窗口尺寸走（它不在布局里，是浮在分界线上的）
        self._place_handle()

    def closeEvent(self, ev):
        store.log("应用退出")
        super().closeEvent(ev)

    def _welcome(self):
        s = store.load_settings()
        if not (s.get("api_key") or "").strip():
            toast(self, "先到「设置」里填一下 API Key，才能开始生成内容", "warn", 4200)


def main():
    # Windows 任务栏图标：必须在 QApplication 建之前声明 AppUserModelID，
    # 否则任务栏按 python.exe 归组，显示的是 Python 的图标而不是我们的。
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "DragonFlow.OneLine")
        except Exception:
            pass

    # 顺序很重要：QApplication 必须先建。
    # theme.init_font() 内部要访问 QFontDatabase，而 QFontDatabase 在没有
    # QApplication 时调用会直接崩掉进程（退出码 127，无任何报错信息）。
    app = QApplication(sys.argv)
    theme.init_font()
    app.setApplicationName(config.APP_NAME)
    app.setStyleSheet(theme.stylesheet())
    app.setFont(theme.font(14))
    if os.path.exists(config.APP_ICON):
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(config.APP_ICON))
    # 全局手型光标：可点控件不再出现「按钮能点但鼠标是箭头」
    theme.install_cursor_filter(app)

    store.log(f"启动 {config.APP_NAME} v{config.APP_VERSION}")

    win = MainWindow()
    theme.apply_styled_bg(win)
    win.root.resizer = WindowResizer(win, win.root)
    win.root.resizer.relayout()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
