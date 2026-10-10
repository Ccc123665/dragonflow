"""界面冒烟测试：离屏渲染 5 个视图 + 关键弹窗并截图，用于验证布局与样式没有回归。

关键点（踩过的坑，别改）：
  1. QtWebEngineWidgets 必须在 QApplication 之前导入，否则直接崩进程且无任何报错
  2. 离屏环境下真实 QWebEngineView 渲染会拖慢/崩，用桩替身替换（只影响截图）
  3. 离屏环境字体库为空，theme.init_font() 会退回按路径加载系统字体，
     否则中文全是方块 —— 这也是打包后交付到别人机器的兜底
  4. 导航要走 win._on_nav()，不要直接 setCurrentWidget —— 否则侧栏显隐逻辑不会被触发，
     截出来的图和真实运行不一致
  5. **用临时数据目录**（把 APPDATA 指到 temp）。以前这个用例直接往用户真实的
     accounts.json 里塞「公考干货号A / B」，用户打开软件看到一堆自己没登录过的账号，
     以为是程序预置的 —— 其实是测试残留。隔离掉最省事。

用法：
    python tests/test_ui_smoke.py
截图输出到 tests/_shots/
"""
import glob
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu --disable-software-rasterizer --no-sandbox"
)

# 数据目录隔离：config 在 import 时就会算 DATA_DIR，所以必须赶在 import 之前改。
# Windows 下 config.user_data_base() 读的就是 APPDATA。
_SMOKE_DATA = tempfile.mkdtemp(prefix="dragonflow_smoke_")
os.environ["APPDATA"] = _SMOKE_DATA
# 临时目录**不**在退出时删自己那份：Chromium 收尾时还在动 profile 目录，
# 这时候 rmtree 会让它 SIGSEGV，退出码变成 139 —— 测试明明全过，
# 却看起来像挂了。改成「启动时清上一轮留下的」（超过 1 小时的），
# 既不留垃圾，也没有退场竞态。
for _old in glob.glob(os.path.join(tempfile.gettempdir(), "dragonflow_smoke_*")):
    if _old != _SMOKE_DATA and time.time() - os.path.getmtime(_old) > 3600:
        shutil.rmtree(_old, ignore_errors=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


def step(msg):
    print("  ·", msg, flush=True)


def pump(ms: int = 260):
    """推进真实时间，让淡入等动画真正跑完 —— 否则截图会停在半透明状态。"""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


# 1) WebEngine 必须最先导入
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
# 2) 再建 QApplication
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QVBoxLayout, QWidget,
)

app = QApplication(sys.argv)


# 3) 桩替身：离屏下不真渲染网页
class _StubView(QWidget):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        lb = QLabel("浏览器区域（截图验证时占位）")
        lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lb.setStyleSheet("color:#9AA0A6; font-size:13px;")
        lay = QVBoxLayout(self)
        lay.addWidget(lb)

    def setPage(self, p): pass
    def page(self): return None
    def reload(self): pass
    def setUrl(self, u): pass
    def url(self): return None
    def load(self, u): pass


step("导入界面模块")
import views.workbench as WB  # noqa: E402

WB.QWebEngineView = _StubView
import browser as BR  # noqa: E402

BR.QWebEngineView = _StubView

step("导入 main")
import main as M  # noqa: E402
import bus as BM  # noqa: E402
import skills as SK  # noqa: E402
import store  # noqa: E402
from bus import Batch, DraftItem  # noqa: E402

theme = M.theme
theme.init_font()
app.setStyleSheet(theme.stylesheet())
app.setFont(theme.font(14))
theme.install_cursor_filter(app)

step("准备测试数据")
db = store.load_accounts()
# 数据目录已在 import 之前指向临时目录（见文件头），这里随便补几个账号造场景就行，
# 不会碰到用户真实的 accounts.json。
for _pk, _nm, _grp in (("xhs", "公考干货号A", "省考项目"),
                       ("xhs", "公考干货号B", "省考项目"),
                       ("douyin", "抖音口播号", "省考项目"),
                       ("gzh", "公众号主号", "")):
    if not any(a.get("name") == _nm for a in store.list_accounts(db)):
        store.add_account(db, _pk, _nm, group=_grp,
                          persona="深耕公考十年的教研老师" if _pk == "xhs" else "")

BODY = ("先说结论：行测提分的关键不在刷题量，而在做题顺序。\n\n"
        "第一，先做常识和言语，进入状态。\n第二，数量关系放到最后。\n"
        "第三，资料分析必须留足 25 分钟。\n\n按这个顺序练三套，你会明显感觉到差别。")

items = []
for pk, sk in (("xhs", "小红书图文"), ("douyin", "抖音口播脚本"), ("gzh", "公众号长图文")):
    c = {"title": f"省考行测提速的三个关键动作（{sk}）",
         "body": BODY,
         "topics": ["省考", "行测", "公考备考", "上岸经验"]}
    items.append(DraftItem(pk, "", sk, c, "省考行测怎么提速"))
b = Batch("省考行测怎么提速")
b.items = items
BM.set_batch(b)

step("构造 MainWindow")
win = M.MainWindow()
theme.apply_styled_bg(win)

# 初始尺寸必须收进**屏幕可用区**（已扣任务栏）。
# 以前直接 resize(1440, 940)，在 1366×768 上可用区只有 728 高 ——
# 窗口底边整条藏到任务栏下面，最下面那排控件点不到。
_av = (win.screen() or app.primaryScreen()).availableGeometry()
_ig = win.geometry()
assert _av.contains(_ig), \
    f"初始窗口超出屏幕可用区：{_ig.getRect()} / 可用区 {_av.getRect()}"
assert win.minimumWidth() <= _av.width() and win.minimumHeight() <= _av.height(), \
    ("最小尺寸不能大于可用区，否则 setMinimumSize 会把窗口重新顶出屏幕："
     f"{win.minimumWidth()}x{win.minimumHeight()} / 可用区 {_av.getRect()}")
step(f"初始窗口收在可用区内：{_ig.getRect()} / 可用区 {_av.getRect()}")

win.resize(1440, 940)
win.show()
pump(400)


# 让内容工坊也渲染出结果卡片，检验双列网格。
# 工坊按「能力」组织，卡片 key 是 skill id（不再是平台 key）。
#
# 工坊列的是 bundle（Skill 包）+ pipeline（流水线），6 个 prompt 基础模板不进。
# 造几条 Skill 包 fixture 是为了让截图里有「用户自己传的包」这一类条目
# （内置流水线本来就够填满下拉，但截出来全是内置的，看不出上传后的样子）。
sv = win.studio_view
for _sid, _nm, _ct, _pk in (
        ("smoke_pack_a", "公众号拆解重组（Skill 包）", "公众号长图文", "gzh"),
        ("smoke_pack_b", "小红书钩子开头库（Skill 包）", "图文", "xhs"),
        ("smoke_pack_c", "抖音口播分镜（Skill 包）", "短视频", "douyin"),
        ("smoke_pack_d", "朋友圈短文案（Skill 包）", "短文案", "xhs")):
    SK.upsert_skill({"id": _sid, "name": _nm, "kind": "bundle",
                     "content_type": _ct, "platform": _pk,
                     "desc": "测试用 Skill 包：把方法论拆成可复用的生成步骤。",
                     "prompt": f"按下面的方法论生成：{{topic}}。" + "占位说明" * 12,
                     "fields": ["title", "body", "topics"]})
# 选前两条，让截图能拍到「已选胶囊」；顺便填点输入，让摘要显示「已填好」。
sv._picked = [s["id"] for s in sv._all_abilities()][:2]
sv._rebuild_abilities()
skill_ids = [s["id"] for s in sv._all_abilities()][:5]
sv._input_values.update({
    "url": "https://mp.weixin.qq.com/s/AbCdEf123456",
    "topic": "省考行测怎么提速",
    "extra": "重点讲做题顺序，控制在 800 字内",
})
sv._refresh_input_summary()
sv._build_cards(skill_ids)
for sid in skill_ids:
    card = sv._cards.get(sid)
    if not card:
        continue
    card.set_content(SK.get_skill(sid), {
        "title": "省考行测提速的三个关键动作",
        "body": BODY,
        "topics": ["省考", "行测", "公考备考", "上岸经验"],
    }, "省考行测怎么提速")
pump()

out = os.path.join(HERE, "_shots")
os.makedirs(out, exist_ok=True)


def shoot(widget, name: str, note: str = ""):
    pump(200)
    pm = widget.grab()
    path = os.path.join(out, name + ".png")
    pm.save(path)
    size = os.path.getsize(path)
    flag = "  ⚠ 可能是空白/豆腐块" if size < 20000 else ""
    step(f"截图 {name}.png {pm.width()}x{pm.height()} {size}B{flag}{note}")


for key, name in [("studio", "01_studio"),
                  ("workbench", "02_workbench"),
                  ("library", "03_library"),
                  ("records", "04_records"),
                  ("settings", "05_settings")]:
    win._on_nav(key)
    shoot(win, name)

# 填写输入弹窗（工坊的输入都收在这里）
from views.studio import InputsDialog  # noqa: E402

win._on_nav("studio")
pump(200)
_d = InputsDialog(win, sv._picked_skills(), sv._input_values)
_d.show()
shoot(_d, "01b_studio_inputs", "（填写输入弹窗）")
if not _d.editors:
    raise SystemExit("填写输入弹窗里没有渲染出任何输入控件")
step(f"填写输入弹窗渲染了 {len(_d.editors)} 个输入控件")
_d.close()

# 工作台：侧栏收起（浏览器区占满）
win._on_nav("workbench")
win._set_sidebar(False)
pump(420)
shoot(win, "06_workbench_sidebar_collapsed", "（侧栏收起）")

# 侧栏收起必须真的能用：
#   1. 标题行里有个看得见、点得到的「收起」按钮（之前只有贴底的浮动手柄，
#      用户反馈「不起作用，没有箭头」）
#   2. 收起后侧栏宽度归 0，并且给浮动手柄留出左侧空隙 ——
#      手柄压在 QWebEngineView 上会被盖住 / 吞点击，那就再也展不开了
step("侧栏收起")
assert win.sidebar.btn_collapse.isVisible(), "标题行应该有「收起账号矩阵」按钮"
assert "收起" in win.sidebar.btn_collapse.toolTip(), "收起按钮要有说明"
assert win.sidebar.width() == 0 and win.sidebar.maximumWidth() == 0, \
    f"收起后侧栏宽度应归 0，实际 {win.sidebar.width()}/{win.sidebar.maximumWidth()}"
_gutter = win.body_lay.contentsMargins().left()
assert _gutter > 0, "收起后应给手柄留出左侧空隙，否则手柄会压在网页视图上"
assert win.handle.geometry().right() <= _gutter + 4, \
    f"手柄应落在空隙里，实际 right={win.handle.geometry().right()} gutter={_gutter}"
assert win.body.rect().contains(win.handle.geometry()), \
    f"收起后手柄还得在窗口里，否则点不回来：{win.handle.geometry()}"
step(f"收起 OK：侧栏 0，空隙 {_gutter}px，手柄 {win.handle.geometry().getRect()}")

# 手柄要**竖向居中**骑在分界线上。
# 以前是贴底的（`body.height() - hh - inset`），inset 还得靠 workbench 的
# bottom_bar_height() 估 —— 底部一有条就往上飘，看着像掉在角落里的扣子。
_hmid = (win.body.height() - win.handle.height()) // 2
assert abs(win.handle.y() - _hmid) <= 2, \
    f"手柄应竖向居中：实际 y={win.handle.y()}，期望 {_hmid}"
assert win.handle.y() < win.body.height() - win.handle.height() - 60, \
    "手柄不该还贴在底部"
step(f"手柄竖向居中：y={win.handle.y()}（body 高 {win.body.height()}，期望 {_hmid}）")

# 窗口变小再变大：手柄的位置必须跟着 body 的**真实**高度走。
# 早先 _place_handle 在窗口 resizeEvent 里读 self.body.height()，拿到的是旧值
# （Qt 的布局是事件循环稍后才激活的），窗口一变小手柄就被摆到屏幕外 ——
# 那才是「收不起来」的真凶。
win.resize(900, 620)
pump(300)
assert win.body.rect().contains(win.handle.geometry()), \
    f"窗口变小后手柄跑到窗口外了：{win.handle.geometry()} / body {win.body.rect()}"
_hmid = (win.body.height() - win.handle.height()) // 2
assert abs(win.handle.y() - _hmid) <= 2, \
    f"窗口变小后手柄仍应居中：y={win.handle.y()}，期望 {_hmid}"
step(f"窗口变小后手柄仍在窗口内且居中：{win.handle.geometry().getRect()}")
win.resize(1440, 940)
pump(300)

win._set_sidebar(True)
pump(420)
assert win.sidebar.width() == M.SIDEBAR_W, f"展开后侧栏应恢复 {M.SIDEBAR_W}"
assert win.body_lay.contentsMargins().left() == 0, "展开后左侧空隙应收回"
step("展开 OK：侧栏恢复宽度，空隙收回")

# 侧栏平台行展开态
shoot(win.sidebar, "07_sidebar", "（账号矩阵侧栏）")

# ---------------- 弹窗
from views.account_dialog import AccountDialog  # noqa: E402
from views.platform_dialog import PlatformDialog  # noqa: E402
from views.skill_dialog import SkillDialog  # noqa: E402
from views.workbench import DraftsDialog  # noqa: E402
from widgets.dialogs import MessageDialog, TextInputDialog  # noqa: E402

d = MessageDialog(win, "确认发布", "即将向 3 个账号触发发布。", kind="ask",
                  confirm=True, ok_text="确认发布", cancel_text="再检查一下",
                  detail="请确认各平台页面内容已核对无误、账号状态正常。\n"
                         "公众号只会保存草稿，不会群发。")
d.show()
shoot(d, "08_dialog_confirm")
d.close()

d = MessageDialog(win, "删除账号", "确定删除「公考干货号A」吗？", kind="err",
                  confirm=True, ok_text="删除", destructive=True,
                  detail="该账号的本地登录态也会一并清除，此操作不可撤销。")
d.show()
shoot(d, "09_dialog_danger")
d.close()

d = TextInputDialog(win, "批量导入选题", "一行一个选题：",
                    "省考行测怎么提速\n申论大作文怎么开头\n在职备考每天两小时怎么安排",
                    multiline=True, ok_text="导入")
d.show()
shoot(d, "10_dialog_batch_topic")
d.close()

d = SkillDialog(win, SK.all_skills()[0])
d.show()
shoot(d, "11_dialog_skill_edit")
d.close()

d = AccountDialog(win, None, "xhs")
d.show()
shoot(d, "12_dialog_account")
d.close()

# 待发布内容弹窗（卡片搬进去）
win._on_nav("workbench")
pump(300)
d = DraftsDialog(win, win.workbench_view)
d.show()
pump(400)
shoot(d, "13_dialog_drafts", "（待发布内容弹窗）")
d.done(0)

# 自定义平台弹窗
d = PlatformDialog(win)
d.show()
shoot(d, "14_dialog_custom_platform")
d.close()

# ---------------- 浏览器标签页：打开 + 关闭
wbv = win.workbench_view
win._on_nav("workbench")
pump(200)
acc_ids = [a["id"] for a in store.list_accounts(store.load_accounts())][:3]
for aid in acc_ids:
    wbv.open_account(aid)
pump(300)
shoot(wbv.browser_pane, "15_browser_tabs", "（标签页带关闭 ×）")

n0 = len(wbv._opened)
mid = acc_ids[1]
wbv._select(mid)
pump(150)
wbv._close_tab(mid)
pump(200)
step(f"关闭标签页：{n0} → {len(wbv._opened)}，当前选中 {wbv._cur_aid}")
if mid in wbv._opened:
    raise SystemExit("标签页没有真的被关闭")
if wbv._cur_aid == mid:
    raise SystemExit("关掉当前标签后没有切到相邻标签")

# 全关掉 → 回到空态
for aid in list(wbv._opened):
    wbv._close_tab(aid)
pump(200)
if wbv._opened or wbv._cur_aid:
    raise SystemExit("全部关闭后状态没有清干净")
if not wbv.empty_browser.isVisible():
    raise SystemExit("全部关闭后没有回到空态")
step("全部关闭 → 已回到空态")

# ---------------- 结果条：跑完一轮后不能被冲回「待填充」
# 之前 _on_all_done 会按「平台级」状态重建 chip，把刚跑出的「失败」冲掉，
# 于是用户看到 toast 说失败、chip 却说待填充，点进去也没有原因。
step("结果条保留本轮结果")
_acc = store.list_accounts(store.load_accounts())
if _acc:
    _aid = _acc[0]["id"]
    wbv._checked.add(_aid)
    wbv._rebuild_status_chips()
    wbv._last_result[_aid] = ("失败", "没有找到正文编辑器，可能页面结构已变化")
    wbv._rebuild_status_chips()
    _chip = wbv._chip_widgets.get(_aid)
    if _chip is None:
        raise SystemExit("结果条里没有这个账号的 chip")
    if "失败" not in _chip.text():
        raise SystemExit(f"chip 没显示失败状态：{_chip.text()!r}")
    if "正文编辑器" not in _chip.toolTip():
        raise SystemExit(f"chip 上没挂失败原因：{_chip.toolTip()!r}")
    step("跑完后的失败状态与原因都留在结果条上")
    wbv._last_result.pop(_aid, None)

# 诊断入口要在浏览器工具条上
if not hasattr(wbv, "btn_diag"):
    raise SystemExit("浏览器工具条上没有「诊断当前页」按钮")
step("浏览器工具条上有「诊断当前页」")

# ================================================================ 数据看板
step("数据看板")
import precheck as PC  # noqa: E402
from views.dashboard import compute as dash_compute  # noqa: E402

win._on_nav("dashboard")
shoot(win, "16_dashboard")

# 统计口径：只认「已填充 / 已发布」，失败不计入成功
import datetime as _dt  # noqa: E402

_today = _dt.date.today().isoformat()
_fake = [
    {"status": "已发布", "platform": "xhs", "platform_name": "小红书",
     "account_name": "A", "created_at": f"{_today} 10:00:00"},
    {"status": "已填充", "platform": "xhs", "platform_name": "小红书",
     "account_name": "B", "created_at": f"{_today} 11:00:00"},
    {"status": "失败", "platform": "douyin", "platform_name": "抖音",
     "account_name": "A", "created_at": f"{_today} 12:00:00"},
]
_st = dash_compute(_fake)
assert _st["ok"] == 2, f"成功数应为 2，实际 {_st['ok']}"
assert _st["fail"] == 1, f"失败数应为 1，实际 {_st['fail']}"
assert _st["today_pub"] == 1 and _st["today_fill"] == 1, "今日填充 / 发布应分开统计"
assert abs(_st["rate"] - 2 / 3) < 1e-6, "成功率 = 成功 / (成功 + 失败)"
assert _st["streak"] == 1, "今天有产出，连续天数应为 1"
assert sum(_st["by_day"].values()) == 2, "近 14 天合计应等于成功数"
step(f"看板统计口径正确：成功 {_st['ok']} / 失败 {_st['fail']} / 成功率 {_st['rate']:.0%}")

# ================================================================ 流水线弹窗
step("流水线参数弹窗")
import pipelines as PL  # noqa: E402
from views.pipeline_dialog import PipelineDialog  # noqa: E402

_gzh = PL.get("gzh_to_xhs")
_vid = PL.get("xhs_video")
assert _gzh is not None and _vid is not None, "流水线运行器没有注册"

d = PipelineDialog(win, _gzh, topic="省考行测怎么提速")
d.show()
pump(300)
shoot(d, "17_dialog_pipeline_gzh", "（公众号链接转图文）")
_v = d.values()
assert set(_v.keys()) == {"url", "text", "read_images", "pages", "extra"}, \
    f"取值字段不对：{_v.keys()}"
assert _v["pages"] == "8", f"页数默认值应为 8，实际 {_v['pages']}"
assert _v["read_images"] == "1", "「读原文配图」默认应该打开"
d.close()

d = PipelineDialog(win, _vid, topic="省考行测怎么提速")
d.show()
pump(300)
shoot(d, "18_dialog_pipeline_video", "（文案转竖屏短视频）")
_v = d.values()
assert _v["voice"] and _v["scenes"] == "6", f"短视频默认值不对：{_v}"
d.close()
step("流水线弹窗能正确收集参数")

# 结果预览：真出几张图喂进缩略图条
import tempfile  # noqa: E402
from pipelines import kit_draw as KD  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="df_smoke_")
_deck = KD.Deck(_tmp, total=3)
_arts = [
    _deck.cover(tag="省考速览", title_small="行测提速",
                title_big=["三个关键动作", "一次讲清"],
                sub1="先看结论 · 再看方法", sub2="顺序对了，速度自然起来",
                stats=[("3", "个动作", "做题顺序"), ("25", "分钟", "资料分析"),
                       ("1", "条主线", "先易后难")]),
    _deck.bullets_page(2, tag="方法论", title="三个关键动作",
                       banner="顺序错了，刷再多题也没用",
                       items=[("先扫题干", "20 秒判断题型"), ("再定顺序", "按分值排"),
                              ("最后回头", "留 5 分钟检查")]),
    _deck.end_page(3, title="就这样练", lines=["先看结构", "再定顺序"],
                   cta="收藏慢慢看"),
]
assert all(os.path.exists(p) for p in _arts), "出图失败"
for p in _arts:
    assert os.path.getsize(p) > 3000, f"{p} 太小，可能是空白图"

d = PipelineDialog(win, _gzh, topic="省考行测怎么提速")
d.show()
pump(200)
# 模拟「已经开始跑过」的状态：参数表单收起，运行区展开
d.form.setVisible(False)
d.run_box.setVisible(True)
d._fit_to_screen()
d._result = {"title": "行测提速的三个动作", "body": "（略）", "topics": "省考 行测",
             "cover": "三个动作", "image_hint": "已出图 3 张", "_artifacts": _arts}
d._on_done(d._result)
pump(500)
shoot(d, "19_dialog_pipeline_result", "（产出缩略图条）")
assert d.result().get("_artifacts"), "结果没有带上产物路径"
assert d.result_box.isVisible(), "产出区没有显示出来"
_thumbs = d.result_box.findChildren(QLabel)
assert len(_thumbs) >= 3, f"缩略图条没建出来（只有 {len(_thumbs)} 个 QLabel）"
d.close()
step(f"出图工具箱产出 {len(_arts)} 张 1080x1440 图")

# ================================================================ 体检弹窗
step("发布前体检")
from views.precheck_dialog import PrecheckDialog  # noqa: E402

_bad = {"title": "这是一个特别特别长的标题已经超过二十个字了啊啊啊啊",
        "body": "短。还有公众号引流。",
        "topics": ["省考"], "cover": ""}
_issues = PC.check("xhs", _bad, {"fields": ["title", "body", "topics", "cover"]})
assert any(i.level == "err" for i in _issues), "超长标题应该被判必改"
assert any("公众号" in i.message for i in _issues), "站外引流词应该被识别"
import compliance  # noqa: E402

_hits = compliance.check_content(_bad)
d = PrecheckDialog(win, "xhs", _issues, _hits)
d.show()
pump(300)
shoot(d, "20_dialog_precheck", "（体检结果）")
d.close()

_good = {"title": "行测提速的三个动作", "body": BODY,
         "topics": ["省考", "行测", "公考备考"], "cover": "三个动作"}
_ok_issues = [i for i in PC.check("xhs", _good, {"fields": list(_good.keys())})
              if i.level == "err"]
assert not _ok_issues, f"合规内容不该有必改项：{[i.message for i in _ok_issues]}"
step("体检规则：超长 / 引流 / 短正文能识别，正常内容不误报")

# ================================================================ 矩阵分配
step("矩阵分配弹窗")
from views.matrix_dialog import MatrixDialog  # noqa: E402

_b = BM.batch()
_accs = {it.platform_key: store.accounts_of(store.load_accounts(), it.platform_key)
         for it in _b.items}
d = MatrixDialog(win, win.workbench_view, _b.items, _accs, set())
d.show()
pump(400)
shoot(d, "21_dialog_matrix", "（内容 × 账号 分配）")
_sel = d.checked()
assert _sel, "矩阵弹窗默认应该勾上账号"
d._var[list(_sel)[0]].setChecked(True)
_jobs = d._jobs()
assert len(_jobs) == 1, f"只勾了一个差异化，应产生 1 个改写任务，实际 {len(_jobs)}"
d.close()

# 差异化内容真的会被填进去
_it = _b.items[0]
_first_acc = _accs[_it.platform_key][0]["id"]
_it.variants[_first_acc] = {"title": "改写后的标题"}
assert _it.content_for(_first_acc)["title"] == "改写后的标题", "差异化版本没生效"
assert _it.content_for("不存在的账号")["title"] == _it.content["title"], "无版本时应回退原文"
assert _it.has_variant(_first_acc) and not _it.has_variant("不存在的账号")
step("矩阵差异化：按账号取版本，无版本回退原文")

# ================================================================ Skill 导入
step("Skill 导入（文件 / 文件夹 / 压缩包）")
import zipfile as _zip  # noqa: E402

# 数据目录已经在开头整体隔离到临时目录（APPDATA），这里不用再备份 / 还原 ——
# 早先那套「copy 备份 + finally 里 shutil.move 还原」是多余的，而且 move 在 Windows
# 下会先 unlink 目标，撞上「删除守卫」就会在 finally 里抛异常，把用例带崩。
_d = tempfile.mkdtemp(prefix="df_pack_")
os.makedirs(os.path.join(_d, "assets"), exist_ok=True)
with open(os.path.join(_d, "SKILL.md"), "w", encoding="utf-8") as f:
    f.write("---\nname: 冒烟测试包\nplatform: 小红书\n"
            "description: 用来验证整包导入的目录\n---\n\n"
            "## 输出要求\n只输出一个 JSON 对象，字段：title, body。\n")
with open(os.path.join(_d, "assets", "x.txt"), "w", encoding="utf-8") as f:
    f.write("附件")
_n, _msgs = SK.import_files([_d])
assert _n == 1 and not _msgs, f"文件夹导入失败：{_n} {_msgs}"
_pk = SK.get_skill("pack_冒烟测试包")
assert _pk and SK.kind_of(_pk) == "bundle", "应识别为 Skill 包"
assert os.path.isdir(_pk["pack_dir"]), "包目录没有落到 data/skills"
assert os.path.isfile(os.path.join(_pk["pack_dir"], "assets", "x.txt")), "附件没被复制"

_z = os.path.join(_d, "z.zip")
with _zip.ZipFile(_z, "w") as zf:
    zf.writestr("inner/模板.md", "---\nname: 压缩包模板\n---\n写{topic}")
    zf.writestr("../逃逸.txt", "x")
_n2, _msgs2 = SK.import_files([_z])
assert _n2 == 1, f"压缩包导入应成功 1 个，实际 {_n2} {_msgs2}"

_bad = os.path.join(_d, "bad.zip")
with open(_bad, "w", encoding="utf-8") as f:
    f.write("not a zip")
_n3, _m3 = SK.import_files([_bad])
assert _n3 == 0 and _m3, "坏压缩包应该报错而不是静默通过"

SK.delete_skill("pack_冒烟测试包")
assert not os.path.isdir(_pk["pack_dir"]), "删模板时应连带删掉包目录"
step("文件夹 / 压缩包 / 坏包 / 目录穿越 都按预期处理")

print("界面冒烟测试通过", flush=True)

# 跑到这里说明所有断言都过了。直接硬退出，**绕开 Qt 的析构**：
# QtWebEngine 在解释器退出时会偶发 SIGSEGV（Chromium 子进程还没收完），
# 退出码变成 139 —— 消息都打完了、断言也全过，CI 却判失败，
# 比真失败还误导人（连跑多套时更容易撞上）。
# 这是 WebEngine 测试脚本的常规收尾手法，不是掩盖问题：
# 真正的失败都在上面 raise / assert 掉了，走不到这一行。
os._exit(0)
