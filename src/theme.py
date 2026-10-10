"""DragonFlow 设计系统 —— 专业 · 克制 · 层级清晰

设计原则
  1. 靠留白与分隔线建立层级，不靠阴影和渐变（低视觉噪音）
  2. 单一强调色，其余全部中性灰阶；语义色只用于状态提示
  3. 圆角统一：卡片 12 / 控件 8 / 大容器 16
  4. 字号阶梯克制：22(大标题) 17(标题) 14(正文) 12.5(辅助) 11.5(标注)
     重要标题一律 600 字重，与正文拉开层级
  5. 动效短促（160-220ms），只做透明度与位移，不做缩放弹跳
  6. 所有可点元素必须是手型光标 —— 由 install_cursor_filter() 全局兜底
"""
import os

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QObject, QPropertyAnimation, QRect, QRectF, Qt,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QAbstractButton, QCheckBox, QComboBox, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

# ============================================================ 色板
# 中性色（iOS System Gray 体系，稍作降饱和以贴合教育行业的稳重感）
BG_PAGE = "#F5F6F8"        # 页面底色
BG_CARD = "#FFFFFF"        # 卡片
BG_SUBTLE = "#FAFBFC"      # 次级容器
BG_HOVER = "#F1F3F6"       # 悬停
BG_SELECTED = "#EBF1FE"    # 选中态
BG_INPUT = "#F8F9FB"       # 输入框填充（需与 BG_PAGE 区分，否则在浅底上隐形）
BG_INPUT_LINE = "#DFE3E9"  # 输入框描边（常显，不依赖底色对比）
BG_SUNK = "#F2F4F7"        # 下沉容器（工具条、状态条）

LINE = "#E7E9EE"           # 主分隔线
LINE_SOFT = "#F0F2F5"      # 次级分隔线
LINE_STRONG = "#D6DAE1"    # 强分隔线（表头等）

TEXT_1 = "#14171C"         # 主文字
TEXT_2 = "#565B64"         # 次文字
TEXT_3 = "#868C96"         # 辅助文字
TEXT_4 = "#B2B8C2"         # 占位 / 禁用

# 强调色（单一主色，深蓝偏冷，专业克制）
PRIMARY = "#2C6BE8"
PRIMARY_HOVER = "#2459CE"
PRIMARY_PRESS = "#1D4BB0"
PRIMARY_TINT = "#EEF4FE"
PRIMARY_SOFT = "#CFE0FC"

# 语义色（低饱和，仅用于状态）
SUCCESS = "#2F9E68"
SUCCESS_TINT = "#EAF6F0"
WARNING = "#C97F1B"
WARNING_TINT = "#FBF3E6"
DANGER = "#D34B47"
DANGER_TINT = "#FBECEB"
DANGER_HOVER = "#BE3F3B"

# 平台品牌色（用于账号标识点，克制使用）
PLATFORM_COLORS = {
    "xhs": "#E0443A",
    "douyin": "#1C1C1E",
    "sph": "#2F9E68",
    "gzh": "#3E9E4E",
    "toutiao": "#D9534F",
}

# ============================================================ 圆角 / 间距
R_CARD = 12
R_CTRL = 8
R_LARGE = 16
R_PILL = 999

SP_1, SP_2, SP_3, SP_4, SP_5, SP_6 = 4, 8, 12, 16, 20, 24

# ============================================================ 字体
_FONT_STACK = [
    "PingFang SC",            # macOS
    "HarmonyOS Sans SC",
    "Microsoft YaHei UI",     # Windows
    "Microsoft YaHei",
    "Source Han Sans SC",
    "Noto Sans CJK SC",
]


# 字体文件兜底：系统字体库取不到中文字体时（精简版系统 / 打包运行环境 / 离屏渲染），
# 直接按路径加载字体文件，避免中文渲染成方块
_FONT_FILES = [
    "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",     # 黑体
    "C:/Windows/Fonts/simsun.ttc",     # 宋体
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _load_font_files() -> list:
    """按路径加载字体文件，返回加载到的族名列表。"""
    got: list = []
    for path in _FONT_FILES:
        if not os.path.exists(path):
            continue
        try:
            fid = QFontDatabase.addApplicationFont(path)
            if fid >= 0:
                got.extend(QFontDatabase.applicationFontFamilies(fid))
        except Exception:
            continue
    return got


def pick_font_family() -> str:
    available = set(QFontDatabase.families())
    for name in _FONT_STACK:
        if name in available:
            return name
    # 系统字体库里没有中文字体，退回按路径加载
    for name in _load_font_files():
        if name:
            return name
    return "sans-serif"


FONT_FAMILY = "sans-serif"   # 启动时由 init_font() 填充


def init_font() -> str:
    global FONT_FAMILY
    # QFontDatabase 在没有 QApplication 时调用会直接崩掉进程（无报错、退出码 127），
    # 这里提前拦一下，把静默崩溃变成一条看得懂的异常。
    from PyQt6.QtWidgets import QApplication
    if QApplication.instance() is None:
        raise RuntimeError(
            "theme.init_font() 必须在 QApplication 创建之后调用"
            "（QFontDatabase 依赖 QApplication）"
        )
    FONT_FAMILY = pick_font_family()
    return FONT_FAMILY


def font(size: int = 14, weight: int = 400) -> QFont:
    f = QFont(FONT_FAMILY, size)
    f.setWeight(QFont.Weight(weight) if weight >= 100 else QFont.Weight.Normal)
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return f


def css_font(size: float = 14, weight: int = 400) -> str:
    return f"font-family:'{FONT_FAMILY}';font-size:{size}px;font-weight:{weight};"


# ============================================================ 全局手型光标
class _CursorFilter(QObject):
    """给所有可点控件自动挂手型光标。

    Qt 的 QSS 不支持 cursor 属性，逐个 setCursor 又容易漏。
    这里装一个应用级事件过滤器：控件一旦进入鼠标，就按它是否可点决定光标。
    顺带修掉「按钮能点但鼠标是箭头」这类体感问题。
    """

    _CLICKABLE = (QAbstractButton, QComboBox)

    def eventFilter(self, obj, ev):
        et = ev.type()
        if et == QEvent.Type.Enter:
            try:
                if isinstance(obj, self._CLICKABLE):
                    if obj.isEnabled():
                        obj.setCursor(Qt.CursorShape.PointingHandCursor)
                    else:
                        obj.unsetCursor()
                elif isinstance(obj, QWidget) and obj.property("clickable"):
                    obj.setCursor(Qt.CursorShape.PointingHandCursor)
            except Exception:
                pass
        return False


_CURSOR_FILTER = None


def install_cursor_filter(app) -> None:
    """在 QApplication 上装全局手型光标过滤器（幂等）。"""
    global _CURSOR_FILTER
    if app is None:
        return
    if _CURSOR_FILTER is None:
        _CURSOR_FILTER = _CursorFilter(app)
        app.installEventFilter(_CURSOR_FILTER)


# ============================================================ 勾选对勾
_TICK_CACHE: dict = {}


def check_tick_path() -> str:
    """把白色对勾渲染成 PNG，供 QSS 的 `image:` 使用。

    QSS 里 `QCheckBox::indicator:checked` 只写 background 会得到**一块纯色方块**，
    没有对勾 —— 用户看到的就是「蓝色色块」。QSS 的 image 只认文件 / 资源，
    不认 QPainter，所以这里现画一张存到数据目录，再拼进样式表。

    必须在 QApplication 之后调用（QPixmap 依赖 QGuiApplication）。
    """
    cached = _TICK_CACHE.get("path")
    if cached and os.path.exists(cached):
        return cached
    try:
        import config
        from PyQt6.QtGui import QPixmap

        size = 16
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        pa = QPainter(pm)
        pa.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#FFFFFF"))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pa.setPen(pen)
        path = QPainterPath()
        path.moveTo(3.4, 8.2)
        path.lineTo(6.6, 11.6)
        path.lineTo(12.8, 4.6)
        pa.drawPath(path)
        pa.end()

        out = os.path.join(config.DATA_DIR, "check_tick.png")
        pm.save(out, "PNG")
        _TICK_CACHE["path"] = out
        return out
    except Exception:
        return ""


# ============================================================ 图标转 PNG
_ICON_PNG_CACHE: dict = {}


def icon_png(name: str, color: str = None, size: int = 14, width: float = 2.0) -> str:
    """把 icons 里的矢量图标渲染成 PNG 文件，返回路径。

    为什么需要它：**QSS 的 `image:` 只认文件 / 资源路径，不认 QIcon**。
    所以想给控件（比如 QComboBox 的 down-arrow）换图标，必须先把图标落到磁盘。

    和 check_tick_path() 一样，必须在 QApplication 之后调用（QPixmap 依赖它）。
    取不到就返回空串，调用方拼样式表时跳过即可（退化成无图标，不影响功能）。
    """
    key = f"{name}|{color or ''}|{size}|{width}"
    cached = _ICON_PNG_CACHE.get(key)
    if cached and os.path.exists(cached):
        return cached
    try:
        import config
        import icons

        pm = icons.pixmap(name, color or TEXT_3, size, width)
        if pm.isNull():
            return ""
        safe = "".join(ch if ch.isalnum() else "_" for ch in key)
        out = os.path.join(config.DATA_DIR, f"qss_icon_{safe}.png")
        pm.save(out, "PNG")
        _ICON_PNG_CACHE[key] = out
        return out
    except Exception:
        return ""


# ============================================================ 全局样式表
def stylesheet() -> str:
    # 对勾图片：QSS 只认文件，所以先渲染到数据目录再拼进来。
    # 渲染失败（比如离屏环境下没字体）就退化成纯色底，不影响功能。
    tick = check_tick_path().replace("\\", "/")
    tick_img = f'image: url("{tick}");' if tick else ""
    # 下拉箭头同理 —— 不给 QComboBox 画箭头的话，它长得和输入框一模一样，
    # 用户根本看不出「这里可以点开选」（设置页的服务商 / 模型两个框就是这样）。
    arrow = icon_png("chevron_down", TEXT_3, 14, 2.0).replace("\\", "/")
    arrow_img = f'image: url("{arrow}");' if arrow else ""
    # 展开态换成主色箭头。渲染不出来就整条规则不写 —— 写个空的 url("")
    # 会把上面那条也一起盖掉，箭头反而彻底没了。
    arrow_on = icon_png("chevron_down", PRIMARY, 14, 2.0).replace("\\", "/")
    arrow_on_rule = (f'QComboBox::down-arrow:on {{ image: url("{arrow_on}"); }}'
                     if arrow_on else "")
    return f"""
* {{ outline: none; }}

QWidget {{
    {css_font(14, 400)}
    color: {TEXT_1};
    background: transparent;
}}

#RootFrame {{
    background: {BG_PAGE};
    border: 1px solid {LINE_STRONG};
}}

/* ---------- 标题栏 ---------- */
#TitleBar {{ background: {BG_CARD}; }}
#TitleText {{ {css_font(12.5, 400)} color: {TEXT_3}; }}
#TitleMark {{ {css_font(13.5, 600)} color: {TEXT_1}; }}

/* ---------- 导航 ---------- */
#NavBar {{ background: {BG_CARD}; border-bottom: 1px solid {LINE}; }}
#NavBarSunk {{ background: {BG_CARD}; border-bottom: 1px solid {LINE}; }}
#SegItem {{
    {css_font(13.5, 400)}
    color: {TEXT_2};
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 7px 16px;
}}
#SegItem:hover {{ background: {BG_HOVER}; color: {TEXT_1}; }}
#SegItem:checked {{ background: {BG_CARD}; color: {TEXT_1}; font-weight: 600; }}
#SegTrack {{ background: {BG_INPUT}; border-radius: 9px; border: 1px solid {LINE}; }}

/* ---------- 侧栏 ---------- */
#Sidebar {{ background: {BG_SUBTLE}; border-right: 1px solid {LINE}; }}
#SideRail {{ background: {BG_SUBTLE}; border-right: 1px solid {LINE}; }}
#SideTitle {{ {css_font(13, 600)} color: {TEXT_1}; }}
#SideGroup {{ {css_font(11.5, 500)} color: {TEXT_3}; }}

/* ---------- 卡片 ---------- */
#Card {{
    background: {BG_CARD};
    border: 1px solid {LINE};
    border-radius: {R_CARD}px;
}}
#CardHover {{
    background: {BG_CARD};
    border: 1px solid {LINE};
    border-radius: {R_CARD}px;
}}
#CardHover:hover {{ border: 1px solid {PRIMARY_SOFT}; background: #FCFDFF; }}
/* ================================================================
   内容工坊（v1.4）—— 下拉选能力 + 弹窗填输入，页面尽量短
   ----------------------------------------------------------------
   v1.3 把每条能力铺成一张实体卡片（名称 + 描述 + 要填/会得到 + 两个胶囊），
   十几条能力就是一屏多的列表，用户的原话是「不用把所有能力都详细列出来」。
   v1.4 收成：**一个下拉选能力 + 已选能力的小胶囊**，详细说明移到下拉项的
   tooltip 里；输入从页内表单改成弹窗，主页面只剩「选了什么 / 还差什么」。
   ================================================================ */
#StudioHero {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0.7,
                stop:0 {PRIMARY_TINT}, stop:0.5 #F6FAFF, stop:1 {BG_CARD});
    border: 1px solid {PRIMARY_SOFT};
    border-radius: {R_LARGE}px;
}}
#StudioHeroTitle {{ {css_font(21, 700)} color: {TEXT_1}; }}
#StudioHeroSub {{ {css_font(12.5, 400)} color: {TEXT_2}; }}
#StudioHeroStat {{ {css_font(12, 600)} color: {PRIMARY}; }}

#StepBadge {{
    background: {PRIMARY};
    color: #FFFFFF;
    border-radius: 11px;
    {css_font(12.5, 700)}
}}
#StepCard {{
    background: {BG_CARD};
    border: 1px solid {LINE};
    border-radius: {R_LARGE}px;
}}
#StepTitle {{ {css_font(14.5, 600)} color: {TEXT_1}; }}
#StepNote {{ {css_font(11.5, 400)} color: {TEXT_3}; }}

/* 能力下拉：页面上的主角，比普通输入框大一号 */
#AbilityCombo {{
    {css_font(13.5, 500)}
    background: {BG_CARD};
    border: 1px solid {PRIMARY_SOFT};
    border-radius: {R_CTRL}px;
    padding: 8px 10px;
    min-height: 22px;
}}
#AbilityCombo:hover {{ border: 1px solid {PRIMARY}; }}
#AbilityCombo:focus {{ border: 1px solid {PRIMARY}; }}
#AbilityCombo::drop-down {{ border: none; width: 26px; }}
#AbilityCombo QAbstractItemView {{
    background: {BG_CARD};
    border: 1px solid {LINE};
    border-radius: {R_CTRL}px;
    padding: 5px;
    selection-background-color: {PRIMARY_TINT};
    selection-color: {TEXT_1};
    outline: none;
}}
/* 跑不起来的项：置灰 + 下沉底，点也点不动（model 里已 setEnabled(False)） */
#AbilityCombo QAbstractItemView::item:disabled {{ color: {TEXT_4}; }}

/* 已选能力的小胶囊：名称 + 一个 × */
#PickedChip {{
    background: {PRIMARY_TINT};
    border: 1px solid {PRIMARY_SOFT};
    border-radius: {R_PILL}px;
}}
#PickedChipName {{ {css_font(12.5, 500)} color: {PRIMARY}; }}
#PickedChip[off="true"] {{
    background: {DANGER_TINT};
    border: 1px solid #F3D2D1;
}}
#PickedChip[off="true"] #PickedChipName {{ color: {DANGER}; }}

#MetaChip {{
    background: {BG_SUNK};
    color: {TEXT_3};
    border-radius: 6px;
    padding: 2px 7px;
    {css_font(11, 500)}
}}
#MetaChip[on="true"] {{ background: {PRIMARY_TINT}; color: {PRIMARY}; }}

#FieldPanel {{
    background: {BG_SUBTLE};
    border: 1px solid {LINE};
    border-radius: 11px;
}}
#FieldPanel[req="true"] {{ background: #FBFDFF; border: 1px solid {PRIMARY_SOFT}; }}
#InputSummary {{ {css_font(12.5, 400)} color: {TEXT_3}; }}
#InputSummary[ok="true"] {{ color: {SUCCESS}; }}
#FieldLabelStrong {{ {css_font(12.5, 600)} color: {TEXT_1}; }}
#ReqPill {{
    background: {DANGER_TINT};
    color: {DANGER};
    border-radius: 6px;
    padding: 1px 6px;
    {css_font(10.5, 600)}
}}

#ActionBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {PRIMARY_TINT}, stop:0.6 #FBFDFF, stop:1 {BG_CARD});
    border: 1px solid {PRIMARY_SOFT};
    border-radius: {R_LARGE}px;
}}
#EmptyStudio {{
    background: {BG_SUBTLE};
    border: 1px dashed {LINE_STRONG};
    border-radius: {R_LARGE}px;
}}
#EmptyStudioIcon {{
    background: {PRIMARY_TINT};
    border: 1px solid {PRIMARY_SOFT};
    border-radius: 23px;
}}
#EmptyStudioTitle {{ {css_font(15, 600)} color: {TEXT_1}; }}
#CardTitle {{ {css_font(15, 600)} color: {TEXT_1}; }}
#CardSub {{ {css_font(12.5, 400)} color: {TEXT_3}; }}
#SectionLabel {{ {css_font(12, 600)} color: {TEXT_3}; }}
#PanelHead {{ {css_font(13, 600)} color: {TEXT_1}; }}
#Sunk {{ background: {BG_SUNK}; border: 1px solid {LINE}; border-radius: {R_CTRL}px; }}

/* ---------- 文本 ---------- */
#H1 {{ {css_font(22, 600)} color: {TEXT_1}; }}
#H2 {{ {css_font(16.5, 600)} color: {TEXT_1}; }}
#H3 {{ {css_font(14.5, 600)} color: {TEXT_1}; }}
#Body {{ {css_font(14, 400)} color: {TEXT_1}; }}
#Muted {{ {css_font(12.5, 400)} color: {TEXT_3}; }}
#Hint {{ {css_font(11.5, 400)} color: {TEXT_4}; }}
#FieldLabel {{ {css_font(12, 600)} color: {TEXT_3}; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    {css_font(13.5, 500)}
    color: {TEXT_1};
    background: {BG_CARD};
    border: 1px solid {BG_INPUT_LINE};
    border-radius: {R_CTRL}px;
    padding: 7px 14px;
    min-height: 20px;
}}
QPushButton:hover {{ background: {BG_HOVER}; border: 1px solid {LINE_STRONG}; }}
QPushButton:pressed {{ background: {BG_SUNK}; }}
QPushButton:disabled {{ color: {TEXT_4}; background: {BG_SUBTLE};
                        border: 1px solid {LINE_SOFT}; }}

QPushButton#Primary {{
    color: #FFFFFF; background: {PRIMARY}; border: 1px solid {PRIMARY};
    font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
QPushButton#Primary:pressed {{ background: {PRIMARY_PRESS}; border-color: {PRIMARY_PRESS}; }}
QPushButton#Primary:disabled {{ background: {BG_INPUT}; border: 1px solid {LINE};
                                color: {TEXT_4}; }}

QPushButton#Danger {{
    color: #FFFFFF; background: {DANGER}; border: 1px solid {DANGER}; font-weight: 600;
}}
QPushButton#Danger:hover {{ background: {DANGER_HOVER}; border-color: {DANGER_HOVER}; }}

QPushButton#Ghost {{
    background: transparent; border: 1px solid transparent; color: {PRIMARY};
    padding: 6px 9px; font-weight: 500;
}}
QPushButton#Ghost:hover {{ background: {PRIMARY_TINT}; }}
QPushButton#Ghost:pressed {{ background: {PRIMARY_SOFT}; }}
QPushButton#Ghost:disabled {{ color: {TEXT_4}; background: transparent; }}

QPushButton#Soft {{
    background: {BG_INPUT}; border: 1px solid {LINE}; color: {TEXT_1};
}}
QPushButton#Soft:hover {{ background: {BG_HOVER}; border: 1px solid {LINE_STRONG}; }}
QPushButton#Soft:disabled {{ color: {TEXT_4}; background: {BG_SUBTLE}; }}

QPushButton#Outline {{
    background: {BG_CARD}; border: 1px solid {LINE_STRONG}; color: {TEXT_2};
}}
QPushButton#Outline:hover {{ border: 1px solid {PRIMARY}; color: {PRIMARY};
                             background: {PRIMARY_TINT}; }}

QPushButton#WinBtn {{
    background: transparent; border: none; border-radius: 6px;
    padding: 0px; color: {TEXT_2};
}}
QPushButton#WinBtn:hover {{ background: {BG_HOVER}; }}
QPushButton#WinClose:hover {{ background: {DANGER}; color: #FFFFFF; }}

/* 工具栏上的分段小按钮（工作台用） */
QPushButton#TabBtn {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 5px 10px; {css_font(12.5, 400)} color: {TEXT_2};
}}
QPushButton#TabBtn:hover {{ background: {BG_HOVER}; }}
QPushButton#TabBtn:checked {{ background: {PRIMARY_TINT}; color: {PRIMARY}; font-weight: 600; }}

/* ---------- 侧栏收起手柄（蓝色渐变） ---------- */
#SideHandle {{
    border: none;
    padding: 0px;
    border-radius: 9px;
    background: qlineargradient(x1:0, y1:0, x2:0.25, y2:1,
                stop:0 #7FB2FF, stop:0.45 {PRIMARY}, stop:1 {PRIMARY_PRESS});
}}
#SideHandle:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0.25, y2:1,
                stop:0 #9CC6FF, stop:0.45 {PRIMARY_HOVER}, stop:1 {PRIMARY});
}}
#SideHandle:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0.25, y2:1,
                stop:0 {PRIMARY}, stop:1 {PRIMARY_PRESS});
}}

/* ---------- 浏览器标签页 ---------- */
#BrowserTab {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}}
#BrowserTab:hover {{ background: {BG_HOVER}; }}
#BrowserTab[active="true"] {{
    background: {PRIMARY_TINT};
    border: 1px solid {PRIMARY_SOFT};
}}
#TabClose {{
    background: transparent; border: none; border-radius: 4px; padding: 0;
}}
#TabClose:hover {{ background: rgba(20, 23, 28, 0.10); }}

/* ---------- 输入 ---------- */
QLineEdit, QTextEdit, QPlainTextEdit {{
    {css_font(13.5, 400)}
    background: {BG_INPUT};
    border: 1px solid {BG_INPUT_LINE};
    border-radius: {R_CTRL}px;
    padding: 8px 10px;
    selection-background-color: {PRIMARY_SOFT};
    selection-color: {TEXT_1};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border: 1px solid #C9CFD8;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    background: {BG_CARD};
    border: 1px solid {PRIMARY};
}}
QLineEdit::placeholder {{ color: {TEXT_4}; }}

QComboBox {{
    {css_font(13.5, 400)}
    background: {BG_INPUT};
    border: 1px solid {BG_INPUT_LINE};
    border-radius: {R_CTRL}px;
    padding: 7px 10px;
    min-height: 18px;
}}
QComboBox:hover {{ border: 1px solid #C9CFD8; }}
QComboBox:focus {{ background: {BG_CARD}; border: 1px solid {PRIMARY}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ {arrow_img} width: 14px; height: 14px; }}
{arrow_on_rule}
QComboBox QAbstractItemView {{
    background: {BG_CARD};
    border: 1px solid {LINE};
    border-radius: {R_CTRL}px;
    padding: 4px;
    selection-background-color: {PRIMARY_TINT};
    selection-color: {TEXT_1};
    outline: none;
}}

QSpinBox, QDoubleSpinBox {{
    {css_font(13.5, 400)}
    background: {BG_INPUT}; border: 1px solid {BG_INPUT_LINE};
    border-radius: {R_CTRL}px; padding: 7px 10px;
}}
QSpinBox:hover, QDoubleSpinBox:hover {{ border: 1px solid #C9CFD8; }}
QSpinBox:focus, QDoubleSpinBox:focus {{ background: {BG_CARD}; border: 1px solid {PRIMARY}; }}

/* ---------- 列表 / 树 ---------- */
QTreeWidget, QListWidget, QTableWidget {{
    background: transparent;
    border: none;
    {css_font(13.5, 400)}
}}
QTreeWidget::item, QListWidget::item {{
    height: 32px; border-radius: 7px; padding-left: 4px;
}}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {BG_HOVER}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {BG_SELECTED}; color: {PRIMARY};
}}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; border: none;
    border-bottom: 1px solid {LINE};
    padding: 9px 6px;
    {css_font(12, 600)} color: {TEXT_3};
}}
QTableWidget {{ gridline-color: transparent; }}
QTableWidget::item {{ padding: 7px 6px; border-bottom: 1px solid {LINE_SOFT}; }}
QTableWidget::item:selected {{ background: {BG_SELECTED}; color: {TEXT_1}; }}

/* ---------- 滚动条（细、无箭头） ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D5D8DE; border-radius: 4px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #BFC4CC; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #D5D8DE; border-radius: 4px; min-width: 32px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- 其他 ---------- */
/* 所有「选择」一律用打勾：勾选框选中 = 主色底 + 白色对勾。
   光设 background 只会得到一块纯色方块，对勾来自 check_tick_path() 生成的 PNG。 */
QCheckBox {{ {css_font(13.5, 400)} spacing: 8px; color: {TEXT_1}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #C4CAD3; background: {BG_CARD};
}}
QCheckBox::indicator:hover {{ border: 1px solid {PRIMARY}; }}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border: 1px solid {PRIMARY};
    {tick_img}
}}
QCheckBox::indicator:checked:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
QCheckBox::indicator:disabled {{ background: {BG_SUBTLE}; border: 1px solid {LINE}; }}
QCheckBox::indicator:checked:disabled {{ background: {TEXT_4}; border-color: {TEXT_4}; }}
QCheckBox:disabled {{ color: {TEXT_4}; }}

/* 筛选行上的紧凑勾选框（形态 / 平台） */
#FilterCheck {{ {css_font(12.5, 400)} color: {TEXT_2}; spacing: 6px; }}
#FilterCheck::indicator {{
    width: 14px; height: 14px; border-radius: 4px;
    border: 1px solid #C4CAD3; background: {BG_CARD};
}}
#FilterCheck::indicator:checked {{
    background: {PRIMARY}; border: 1px solid {PRIMARY};
    {tick_img}
}}
#FilterCheck::indicator:hover {{ border: 1px solid {PRIMARY}; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {PRIMARY_SOFT}; }}

QToolTip {{
    background: #2C2F36; color: #FFFFFF; border: none;
    border-radius: 6px; padding: 6px 9px; {css_font(12, 400)}
}}

QMenu {{
    background: {BG_CARD}; border: 1px solid {LINE};
    border-radius: {R_CTRL}px; padding: 5px;
}}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; {css_font(13.5, 400)} }}
QMenu::item:selected {{ background: {PRIMARY_TINT}; color: {PRIMARY}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}

QProgressBar {{
    background: {BG_INPUT}; border: none; border-radius: 3px;
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 3px; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; border: none; padding: 8px 14px;
    {css_font(13.5, 500)} color: {TEXT_2};
}}
QTabBar::tab:hover {{ color: {TEXT_1}; }}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 2px solid {PRIMARY}; font-weight: 600; }}

/* ---------- 弹窗（自绘标题栏） ---------- */
#DlgCard {{
    background: {BG_CARD};
    border: 1px solid {LINE_STRONG};
    border-radius: {R_LARGE}px;
}}
#DlgTitle {{ {css_font(16, 600)} color: {TEXT_1}; }}
#DlgSub {{ {css_font(12.5, 400)} color: {TEXT_3}; }}
#DlgFoot {{ background: {BG_SUBTLE}; border-top: 1px solid {LINE};
            border-bottom-left-radius: {R_LARGE}px;
            border-bottom-right-radius: {R_LARGE}px; }}
#DlgHead {{ background: {BG_CARD}; border-top-left-radius: {R_LARGE}px;
            border-top-right-radius: {R_LARGE}px; }}
"""


# ============================================================ 组件
class Switch(QCheckBox):
    """iOS 风格开关。"""

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 26)
        self._offset = 1.0 if checked else 0.0
        self.setChecked(checked)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, v: float):
        self._offset = max(0.0, min(1.0, v))
        self.update()

    offset = pyqtProperty(float, fget=get_offset, fset=set_offset)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(44, 26)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2

        off = QColor("#D3D6DC")
        on = QColor(PRIMARY)
        c = QColor(
            int(off.red() + (on.red() - off.red()) * self._offset),
            int(off.green() + (on.green() - off.green()) * self._offset),
            int(off.blue() + (on.blue() - off.blue()) * self._offset),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        pad = 3.0
        kr = r - pad
        cx = pad + kr + (w - 2 * (pad + kr)) * self._offset
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(cx - kr, h / 2 - kr, kr * 2, kr * 2))
        p.end()


class SegmentedControl(QWidget):
    """iOS 分段控件。"""

    def __init__(self, items, parent=None, on_change=None):
        super().__init__(parent)
        self.setObjectName("SegTrack")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._items = list(items)
        self._buttons = []
        self._on_change = on_change
        self._current = 0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        for i, (key, text) in enumerate(self._items):
            b = QPushButton(text)
            b.setObjectName("SegItem")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setAutoExclusive(False)
            b.clicked.connect(lambda _=False, idx=i: self.set_index(idx))
            lay.addWidget(b)
            self._buttons.append(b)
        self.set_index(0, notify=False)

    def set_index(self, idx: int, notify: bool = True):
        if not self._buttons:
            return
        idx = max(0, min(len(self._buttons) - 1, idx))
        self._current = idx
        for i, b in enumerate(self._buttons):
            b.setChecked(i == idx)
        if notify and self._on_change:
            self._on_change(self._items[idx][0])

    def current_key(self) -> str:
        return self._items[self._current][0]


class Card(QWidget):
    """白底圆角卡片容器。

    注意：QWidget 子类默认不绘制 QSS 里的 background，
    必须显式打开 WA_StyledBackground，否则 #Card 的白底不会出现。
    """

    def __init__(self, parent=None, padding: int = 16, spacing: int = 12):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        from PyQt6.QtWidgets import QVBoxLayout
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)


def styled(w: QWidget) -> QWidget:
    """给纯 QWidget 打开 QSS 背景绘制。

    Qt 的坑：自定义/裸 QWidget 默认不画 stylesheet 里的 background，
    必须显式打开 WA_StyledBackground，否则设了背景也看不见。
    """
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return w


def apply_styled_bg(root: QWidget) -> None:
    """递归给所有「裸 QWidget」补上背景绘制开关（内联 setStyleSheet 的容器全靠它）。"""
    if root is None:
        return
    if type(root) is QWidget:
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    for child in root.findChildren(QWidget):
        if type(child) is QWidget:
            child.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


def clear_layout(lay) -> None:
    """清空布局并真正移除子控件。

    Qt 的坑：只 takeAt 不摘父子关系的话，deleteLater() 是延迟执行，
    旧控件会留在原位继续显示 —— 典型症状是「两个空状态叠在一起」。
    """
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


def detach_layout(lay) -> None:
    """把子控件从布局里摘出来，但**不销毁**它们。

    和 clear_layout 的区别：clear_layout 会 deleteLater（用于真正要丢掉的旧控件），
    detach_layout 只是「先搬走」，控件还能再塞进别的布局 ——
    典型场景是弹窗打开时把卡片搬进去、关闭时搬回来。
    """
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
        elif it.layout() is not None:
            detach_layout(it.layout())


class FlowLayout(QLayout):
    """自动换行的横向布局。

    平台芯片数量不固定（用户能加自定义平台），用 QHBoxLayout 会挤成一条，
    用 QGridLayout 又要自己算列数。这里用标准的 FlowLayout：放不下就换行。
    """

    def __init__(self, parent=None, margin: int = 0, h_gap: int = 8, v_gap: int = 8):
        super().__init__(parent)
        self._items: list = []
        self._h_gap = h_gap
        self._v_gap = v_gap
        self.setContentsMargins(margin, margin, margin, margin)

    # --- Qt 要求的接口
    def addItem(self, item):            # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):                # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):                # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):      # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:        # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):        # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self):                 # noqa: N802
        return self.minimumSize()

    def minimumSize(self):              # noqa: N802
        from PyQt6.QtCore import QSize
        w = h = 0
        for it in self._items:
            s = it.sizeHint()
            w = max(w, s.width())
            h = max(h, s.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(),
                     h + m.top() + m.bottom())

    # --- 真正的排布
    def _layout(self, rect, apply: bool) -> int:
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        for it in self._items:
            s = it.sizeHint()
            if x + s.width() > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._v_gap
                line_h = 0
            if apply:
                it.setGeometry(QRect(x, y, s.width(), s.height()))
            x += s.width() + self._h_gap
            line_h = max(line_h, s.height())
        return y + line_h - rect.y() + m.bottom()


def paint_bg(w: QWidget, color: str) -> QWidget:
    """给容器刷底色，且**只作用于容器本身**。

    ⚠ 不要用 `w.setStyleSheet("background:xxx;")` 这种没有选择器的写法。
    Qt 会把这种「裸声明块」当成作用于该控件**及其全部后代**，把子控件自己的
    背景色一起冲掉 —— 典型症状是主按钮变成「白底 + 蓝边 + 白字」，完全看不见。
    这里用 objectName 把选择器限定住。
    """
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    name = w.objectName()
    if not name:
        name = f"_bg{id(w)}"
        w.setObjectName(name)
    cls = w.metaObject().className()
    w.setStyleSheet(f"{cls}#{name} {{ background: {color}; }}")
    return w


class PageScroll(QScrollArea):
    """居中限宽的可滚动页面容器。

    表单类页面（设置、内容工坊）横向拉满整个窗口会显得稀疏、不专业，
    这里把内容限制在 max_width 内并水平居中，窗口再宽也不会散开。

    用法：
        page = PageScroll(max_width=920)
        page.body.addWidget(card)
        page.body.addStretch(1)
    """

    def __init__(self, max_width: int = 920, top: int = 18, bottom: int = 28,
                 side: int = 24, spacing: int = 16, parent=None):
        super().__init__(parent)
        self._max_w = max_width
        self._top, self._bottom, self._side = top, bottom, side
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 不设样式：应用级 QSS 里 QWidget 本来就是透明的。
        # 一旦写 setStyleSheet("background:transparent;")，子孙控件（主按钮、
        # 输入框）自己的背景会被一起清掉，见 paint_bg 的说明。

        self._holder = QWidget()
        self.setWidget(self._holder)

        self.body = QVBoxLayout(self._holder)
        self.body.setSpacing(spacing)
        self._apply_margins()

    def _apply_margins(self):
        w = self.viewport().width()
        side = max(self._side, (w - self._max_w) // 2)
        self.body.setContentsMargins(side, self._top, side, self._bottom)
        self._guard_overflow(w)

    def _guard_overflow(self, w: int) -> None:
        """兜底：内容最小宽度超过视口时，把横向滚动条打开。

        触发场景很常见 —— 某个长 QLabel 忘了 setWordWrap(True)，它会把整个
        内容容器撑得比视口还宽。因为横向滚动条默认是关的，右侧控件会**静默消失**
        （不是被压扁，是根本看不到，也没法滚过去）。踩过一次：设置页一个提示
        标签把内容撑到 2170px，行尾新加的按钮直接跑到屏幕外。
        宁可让用户横向滚一下，也不要让控件无声无息地不见。
        """
        over = self._holder.minimumSizeHint().width() > w + 4
        want = (Qt.ScrollBarPolicy.ScrollBarAsNeeded if over
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if self.horizontalScrollBarPolicy() != want:
            self.setHorizontalScrollBarPolicy(want)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply_margins()


def hline(color: str = LINE) -> QWidget:
    w = QWidget()
    w.setFixedHeight(1)
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    paint_bg(w, color)
    return w


def vline(color: str = LINE) -> QWidget:
    w = QWidget()
    w.setFixedWidth(1)
    w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    paint_bg(w, color)
    return w


def label(text: str, obj: str = "Body", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def fade_in(widget: QWidget, duration: int = 200):
    """淡入动效（iOS 风：只做透明度，不做缩放）。

    注意：必须复用已有的 QGraphicsOpacityEffect。
    每次新建 effect 会让 setGraphicsEffect 删掉旧的，而旧 effect 上可能还有
    正在跑的动画 —— 连续快速切页时会把控件留在半透明状态。
    """
    if widget is None:
        return
    old = getattr(widget, "_fade_anim", None)
    if old is not None:
        try:
            old.stop()
        except Exception:
            pass

    eff = widget.graphicsEffect()
    if not isinstance(eff, QGraphicsOpacityEffect):
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)

    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: eff.setOpacity(1.0))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._fade_anim = anim


def dot(color: str, size: int = 8) -> QWidget:
    """小圆点状态标识。"""
    class _Dot(QWidget):
        def __init__(self):
            super().__init__()
            self.setFixedSize(size, size)

        def paintEvent(self, _ev):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(0, 0, size, size))
            p.end()

    return _Dot()


def rounded_pixmap(color: str, text: str, size: int = 22, radius: int = 6,
                   font_size: int = 11, weight: int = 600) -> "QPixmap":
    """生成一个「色块 + 单字」的小徽标位图（平台标识用）。"""
    from PyQt6.QtGui import QPixmap
    pm = QPixmap(size * 3, size * 3)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(0, 0, size * 3, size * 3), radius * 3, radius * 3)
    p.setPen(QColor("#FFFFFF"))
    p.setFont(font(font_size, weight))
    p.drawText(QRectF(0, 0, size * 3, size * 3), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    pm.setDevicePixelRatio(3)
    return pm


STATUS_COLORS = {
    "正常": SUCCESS,
    "限流": WARNING,
    "封禁预警": DANGER,
    "停用": TEXT_4,
    "未登录": TEXT_4,
}


# 兼容别名
style = stylesheet
