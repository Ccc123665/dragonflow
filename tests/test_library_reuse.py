"""素材库 → 工作台 这条链路的回归测试。

盯的是三个真实报障：
  1. 「存入素材库没有图片，只有文案」 —— 产出文件（artifacts）根本没被存下来
  2. 「点复用到工作台，工作台和待发布内容里都看不到」 ——
     主窗口的导航回调会无条件用内容工坊的（空）批次覆盖掉素材库刚设好的
  3. 「配图传不上去」 —— image_hint 被当成空格分隔的标签列表拆成了单词，
     「目录：J:/…」被拆碎，发布时解析不出目录

用法：
    python tests/test_library_reuse.py
（用临时数据目录跑，不碰你本机的账号 / 素材库 / Skill 库）
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu --disable-software-rasterizer --no-sandbox"
)

# 数据目录隔离：config 在 import 时就算好 DATA_DIR，必须赶在 import 之前改 APPDATA
# （Windows 下 config.user_data_base() 读的就是它）。
#
# ⚠ 以前这里是「备份 → 跑完还原」，但那个方案有个致命的**棘轮效应**：
# 只要有一次跑到一半被杀（Ctrl-C / 超时 / 沙箱 SIGTERM），finally 不执行，
# 测试造的 Skill 包就留在真实库里了；下次再跑时备份的已经是**被污染的那一份**，
# 于是永远还原不干净 —— 而且表现成「内置模板自检突然多出几个不认识的包」，
# 极难反查到是测试留下的。直接隔离最省事，也是 test_ui_smoke /
# test_custom_platform 一直在用的做法。
_TEST_DATA = tempfile.mkdtemp(prefix="dragonflow_reuse_")
os.environ["APPDATA"] = _TEST_DATA
# 启动时清上一轮留下的（>1 小时的），不在退出时删自己那份 —— 退场时删会有竞态。
for _old in glob.glob(os.path.join(tempfile.gettempdir(), "dragonflow_reuse_*")):
    if _old != _TEST_DATA and time.time() - os.path.getmtime(_old) > 3600:
        shutil.rmtree(_old, ignore_errors=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

fails = []


def check(name, cond, detail=""):
    print(f"  {'[OK]  ' if cond else '[FAIL]'} {name}" + (f"  → {detail}" if detail else ""),
          flush=True)
    if not cond:
        fails.append(name)


def main():
    print("\n=== 素材库 → 工作台 链路 ===\n")

    # ⚠ WebEngine 必须在 QApplication 之前导入，否则直接崩进程、无任何报错
    from PyQt6.QtCore import Qt
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    app = QApplication(sys.argv)

    # 桩：离屏下不真渲染网页
    class _StubView(QWidget):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel("stub"))

        def setPage(self, p): pass
        def page(self): return None
        def reload(self): pass
        def setUrl(self, u): pass
        def url(self): return None
        def load(self, u): pass

    import browser as BR
    BR.QWebEngineView = _StubView
    import views.workbench as WB
    WB.QWebEngineView = _StubView

    import bus as BM
    import config
    import main as M
    import platforms as PF
    import skills as SK
    import store
    from bus import Batch, DraftItem
    from views.studio import InputsDialog
    from widgets.content_card import _from_text

    theme = M.theme
    theme.init_font()

    # 数据目录已经在文件头指向临时目录了，这里不用再备份 / 还原任何东西。
    assert config.DATA_DIR.startswith(_TEST_DATA), \
        f"数据目录没隔离成功：{config.DATA_DIR} 不在 {_TEST_DATA} 下"

    tmp = os.path.join(ROOT, ".workbuddy-ai", "tmp", "reuse_imgs")
    os.makedirs(tmp, exist_ok=True)
    imgs = []
    try:
        from PIL import Image
        for i, n in enumerate(("01.png", "02.png", "03.png")):
            p = os.path.join(tmp, n)
            Image.new("RGB", (120, 160), (40 + i * 60, 90, 200)).save(p)
            imgs.append(p)
    except Exception:
        # 没有 Pillow 就写一个 1x1 的合法 PNG
        import base64
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        for n in ("01.png", "02.png", "03.png"):
            p = os.path.join(tmp, n)
            with open(p, "wb") as f:
                f.write(png)
            imgs.append(p)
    vid = os.path.join(tmp, "clip.mp4")
    with open(vid, "wb") as f:
        f.write(b"\x00" * 32)

    try:
        # ---------------- 1. 字段解析：image_hint 不该被拆碎
        print("--- 字段解析 ---")
        hint = f"写实风格，横版 3:4\n已出图 3 张，目录：{tmp}"
        check("topics 仍按空格 / 逗号拆成列表",
              _from_text("topics", "省考 行测，公考") == ["省考", "行测", "公考"],
              str(_from_text("topics", "省考 行测，公考")))
        got = _from_text("image_hint", hint)
        check("image_hint 保持整段文本（不再拆成单词）",
              isinstance(got, str) and "目录：" in got, repr(got)[:70])
        check("shot_hint 同理", isinstance(_from_text("shot_hint", hint), str))

        # ---------------- 2. 要传哪些文件
        print("\n--- 上传文件挑选 ---")
        content = {"image_hint": hint}
        check("优先用产出文件（artifacts）",
              PF.upload_files("xhs", content, imgs) == imgs,
              str(len(PF.upload_files("xhs", content, imgs))))
        check("产出文件里混进视频也认",
              PF.upload_files("xhs", content, imgs + [vid]) == imgs + [vid])
        check("没有产出文件时退回解析 image_hint 目录",
              PF.upload_files("xhs", content, None) == sorted(
                  os.path.join(tmp, n) for n in ("01.png", "02.png", "03.png")))
        check("平台没声明 upload_dir_field 就一律不传",
              PF.upload_files("douyin", content, imgs) == [])
        check("产出文件不存在时被过滤掉",
              PF.upload_files("xhs", content, [os.path.join(tmp, "nope.png")])
              == sorted(os.path.join(tmp, n) for n in ("01.png", "02.png", "03.png")))

        # ---------------- 3. 素材库要存下产出文件
        print("\n--- 素材库存产出文件 ---")
        db = store.load_library()
        it = store.add_library_item(
            db, title="省考行测提速", topic="省考", platform="xhs",
            skill_id="xhs_from_gzh", content=content, artifacts=imgs)
        check("素材库条目带上了 artifacts", it.get("artifacts") == imgs,
              str(it.get("artifacts")))
        reloaded = [x for x in store.load_library()["items"] if x["id"] == it["id"]]
        check("落盘后还在（不是只在内存里）",
              bool(reloaded) and reloaded[0].get("artifacts") == imgs)

        # ---------------- 4. 模板自检
        print("\n--- 模板可用性自检 ---")
        bad_pipe = {"id": "t1", "name": "缺运行器", "kind": "pipeline",
                    "pipeline": "not_exist_pipe", "platform": "xhs", "fields": ["body"]}
        iss = SK.check_skill(bad_pipe)
        check("pipeline 缺运行器 → 判为不可用",
              any(i["level"] == "err" and "运行器" in i["text"] for i in iss),
              str(iss))
        good_pipe = dict(bad_pipe, pipeline="gzh_to_xhs")
        check("pipeline 有运行器 → 不报错",
              not any(i["level"] == "err" for i in SK.check_skill(good_pipe)))

        empty = {"id": "t2", "name": "空指令", "kind": "prompt", "prompt": "",
                 "platform": "xhs", "fields": ["body"]}
        check("prompt 为空 → 判为不可用",
              any(i["level"] == "err" for i in SK.check_skill(empty)))

        # 用户那个 gzh-to-xhs 的 SKILL.md 就是这种：描述了一堆要动手的动作
        bundle = {"id": "t3", "name": "公众号转小红书", "kind": "bundle",
                  "platform": "xhs", "fields": ["title", "body"],
                  "system": "第一步：抓取公众号链接正文。第二步：逐张读配图。"
                            "第三步：渲染出图并保存。",
                  "prompt": "围绕选题「{topic}」输出 JSON。"}
        iss = SK.check_skill(bundle)
        check("描述了「抓取 / 出图」却只有 prompt 形态 → 给出警告",
              any(i["level"] == "warn" and "动作" in i["text"] for i in iss),
              str([i["text"][:50] for i in iss]))
        check("并说明要配 pipeline 才行",
              any("pipeline" in i["text"] for i in iss))

        check("内置模板全部可用（没有误报）", SK.audit_all() == [],
              str([s["name"] for s, _ in SK.audit_all()]))

        # ---------------- 5. 工坊的能力从哪来
        # 工坊现在按「能力」组织（不再按平台），所以真正要守的不变量是：
        # 内置能力里必须**有能跑的流水线** —— 那是「贴链接就出图文 / 视频」的本体。
        print("\n--- 工坊的能力清单 ---")
        pipes = [s for s in SK.all_skills()
                 if SK.is_pipeline(s) and SK.can_run(s)]
        check("内置能力里有能跑的流水线（贴链接就能干活）",
              len(pipes) >= 2, "、".join(s["name"] for s in pipes))
        check("每条能力都声明了输入",
              all(SK.inputs_of(s) for s in pipes),
              str([s["name"] for s in pipes if not SK.inputs_of(s)]))
        check("每条能力都声明了输出",
              all(SK.outputs_of(s) for s in pipes),
              str([s["name"] for s in pipes if not SK.outputs_of(s)]))
        check("内置能力全部可用（没有误报）", SK.audit_all() == [],
              str([s["name"] for s, _ in SK.audit_all()]))

        # ---------------- 5. 复用：合并而不是整个替换
        print("\n--- 复用到工作台 ---")
        win = M.MainWindow()
        win.resize(1200, 800)

        # 先在工作台里放一份别的平台的内容
        other = DraftItem("douyin", "", "抖音口播脚本", {"title": "抖音那条"}, "别的选题")
        b = Batch("别的选题")
        b.items = [other]
        BM.set_batch(b)

        win.library_view.reload()
        target = next(x for x in win.library_view._items if x["id"] == it["id"])
        win.library_view._select(target)
        win.library_view._reuse()

        cur = BM.batch()
        keys = [x.platform_key for x in cur.items]
        check("复用后批次里有这条素材的平台", "xhs" in keys, str(keys))
        check("别的平台的内容没被冲掉", "douyin" in keys, str(keys))
        reused = next(x for x in cur.items if x.platform_key == "xhs")
        check("复用时带上了产出文件", reused.artifacts == imgs, str(reused.artifacts))
        check("工作台真的建出了这张卡片", "xhs" in win.workbench_view._cards,
              str(list(win.workbench_view._cards.keys())))

        # 再复用同一条 → 同平台替换，不重复
        win.library_view._reuse()
        cur = BM.batch()
        check("同平台重复复用不会出现两条",
              len([x for x in cur.items if x.platform_key == "xhs"]) == 1,
              str([x.platform_key for x in cur.items]))

        # ---------------- 6. 导航不该覆盖批次
        print("\n--- 导航不覆盖批次 ---")
        before = [x.platform_key for x in BM.batch().items]
        win._goto_workbench()
        after = [x.platform_key for x in BM.batch().items]
        check("走导航回调后批次原封不动", before == after, f"{before} → {after}")

        # ---------------- 7. 工作台卡片能拿到产出文件
        print("\n--- 工作台卡片 ---")
        card = win.workbench_view._cards.get("xhs")
        check("工作台卡片上挂上了产出文件",
              card is not None and card.artifacts == imgs,
              str(card.artifacts if card else None))

        # ---------------- 7·五. 工坊只列「真能干活的」能力
        # 口径 = skills.STUDIO_KINDS：bundle（上传的 Skill 包）+ pipeline
        # （抓网页 / 出图 / 渲染视频的多步流程）。
        # 不列随软件发的 6 个 prompt 基础模板 —— 它们只产文字、干不了实事。
        # 用户的原话是「这三个（流水线）就算是我上传的 skill」。
        print("\n--- 工坊只列 Skill 包 + 流水线 ---")
        st = win.studio_view
        st._rebuild_abilities()
        ids = st._combo_ids()
        prompt_ids = sorted(i for i in ids if SK.kind_of(SK.get_skill(i)) == "prompt")
        check("prompt 基础模板不出现在工坊里", not prompt_ids, str(prompt_ids))
        check("两条内置流水线出现在工坊里",
              {"xhs_from_gzh_dark", "xhs_from_gzh_both"} <= set(ids),
              str(sorted(ids)))
        check("下拉里的条目 = studio_skills()",
              set(ids) == {s["id"] for s in SK.studio_skills()})
        # 用户要的是「不用把所有能力都详细列出来」—— 下拉里一行装下，
        # 描述 / 要填 / 会得到这些长文本挪到 tooltip。
        check("下拉每一项只写「名称 · 形态 · 平台」，不铺描述",
              all("\n" not in st.combo.itemText(i) and len(st.combo.itemText(i)) <= 60
                  for i in range(st.combo.count())),
              st.combo.itemText(0))
        check("详细说明挪到了下拉项的 tooltip 里",
              "要填" in (st.combo.itemData(0, Qt.ItemDataRole.ToolTipRole) or ""),
              repr(st.combo.itemData(0, Qt.ItemDataRole.ToolTipRole))[:48])
        check("下拉框有占位提示（复位后不是一片空白）",
              bool(st.combo.placeholderText()), repr(st.combo.placeholderText()))
        check("下拉框有展开箭头（否则看不出这里能点）",
              "down-arrow" in theme.stylesheet())

        # 注意：这里必须用 isHidden() 而不是 isVisible() ——
        # 工坊当时不是当前页，父级没显示，isVisible() 会恒为 False，
        # 断不出「面板自己有没有被隐藏」。
        check("有内置流水线时选能力区是显示的，不是引导面板",
              not st.picker_box.isHidden() and st.no_skill_panel.isHidden(),
              f"panel_hidden={st.no_skill_panel.isHidden()} "
              f"picker_hidden={st.picker_box.isHidden()}")

        # 引导面板只在「一条能力都没有」时出现。内置流水线一直都在，
        # 正常路径走不到那条分支 —— 所以打桩把清单变空来验。
        from unittest import mock
        with mock.patch.object(SK, "studio_skills",
                               lambda include_disabled=False: []):
            st._rebuild_abilities()
            check("一条能力都没有时给的是引导面板，不是一片空白",
                  not st.no_skill_panel.isHidden() and st.picker_box.isHidden(),
                  f"panel_hidden={st.no_skill_panel.isHidden()} "
                  f"picker_hidden={st.picker_box.isHidden()}")
            check("空态下 hero 也跟着说「还没有能力」",
                  "还没有能力" in st.lb_hero_stat.text(), st.lb_hero_stat.text())

        # 回到真实清单：默认选的是**第一条能跑的能力**，且流水线优先
        st._picked_init = False
        st._picked = []
        st._rebuild_abilities()
        check("默认选上第一条能跑的能力（流水线优先）",
              len(st._picked) == 1 and SK.is_pipeline(SK.get_skill(st._picked[0])),
              str(st._picked))
        check("选中的能力以胶囊列出来",
              set(st._picked_chips) == set(st._picked), str(sorted(st._picked_chips)))
        check("选中的能力在下拉里带勾选图标",
              not st.combo.itemIcon(ids.index(st._picked[0])).isNull())

        # 加 / 摘：下拉选中即加入，胶囊上的 × 摘掉
        check("从下拉加一个能力 → 进清单，同时多一个胶囊",
              st._add_ability("xhs_from_gzh_dark")
              and "xhs_from_gzh_dark" in st._picked_chips,
              str(st._picked))
        check("重复加不会出现两条",
              not st._add_ability("xhs_from_gzh_dark")
              and st._picked.count("xhs_from_gzh_dark") == 1, str(st._picked))
        st._remove_ability("xhs_from_gzh_dark")
        check("点胶囊上的 × → 从清单和胶囊里一起摘掉",
              "xhs_from_gzh_dark" not in st._picked
              and "xhs_from_gzh_dark" not in st._picked_chips, str(st._picked))

        # 造几条 Skill 包 fixture —— 后面几节都要靠它们
        PACKS = [
            ("t_pack_gzh", "拆解重组包", "公众号长图文", "gzh"),
            ("t_pack_xhs", "钩子开头包", "图文", "xhs"),
            ("t_pack_dy", "口播分镜包", "短视频", "douyin"),
        ]
        for sid, nm, ct, pk in PACKS:
            SK.upsert_skill({"id": sid, "name": nm, "kind": "bundle",
                             "content_type": ct, "platform": pk,
                             "desc": "测试用 Skill 包",
                             "prompt": f"按方法论写：{{topic}}。" + "占位" * 20,
                             "fields": ["title", "body", "topics"]})
        st._rebuild_abilities()
        check("导入 Skill 包后它们就出现在下拉里",
              {p[0] for p in PACKS} <= set(st._combo_ids()),
              str(sorted(st._combo_ids())))

        # ---------------- 8. 工坊拦住跑不起来的能力
        # 「装上了、界面上也看得到，一点生成却报错」是最糟的体验。
        # 工坊必须把不可用的能力标出来，并且**不让选**。
        print("\n--- 工坊拦住跑不起来的能力 ---")
        SK.upsert_skill({"id": "t_bad_pack", "name": "缺指令的包", "kind": "bundle",
                         "content_type": "图文", "platform": "xhs",
                         "prompt": "", "fields": ["body"]})
        st._rebuild_abilities()
        ids = st._combo_ids()
        check("跑不起来的能力也在下拉里（不是藏掉）", "t_bad_pack" in ids, str(sorted(ids)))
        idx = ids.index("t_bad_pack") if "t_bad_pack" in ids else -1
        check("标成「不可用」",
              idx >= 0 and "不可用" in st.combo.itemText(idx),
              st.combo.itemText(idx) if idx >= 0 else "")
        item = st.combo.model().item(idx) if idx >= 0 else None
        check("下拉项被禁用（点不动）", item is not None and not item.isEnabled())
        check("强行加会被拒绝，不进清单", not st._add_ability("t_bad_pack"))
        check("它也不会被默认选上", "t_bad_pack" not in st._picked)
        SK.delete_skill("t_bad_pack")
        st._rebuild_abilities()

        # ---------------- 9. 多个能力共用同一个输入
        # 选两个 Skill 包，它们要的都是「选题 / 账号人设 / 补充要求」，
        # 弹窗里必须各只有一个框，填一次两边都用。
        print("\n--- 多个能力共用输入（弹窗）---")
        st._picked = ["t_pack_gzh", "t_pack_xhs"]
        st._rebuild_abilities()
        check("输入不再内嵌在页面上（页面里没有输入控件）", not st._editors)
        dlg = InputsDialog(win, st._picked_skills(), st._input_values)
        keys = list(dlg.editors.keys())
        check("两个能力都选上时，共用的输入只渲染一次",
              keys.count("topic") == 1, str(keys))
        check("两个能力各自的独有输入也在",
              "persona" in keys and "extra" in keys, str(keys))
        check("弹窗副标题里说明了「会同时喂给 2 个能力」",
              "2 个能力" in dlg.lb_sub.text(), dlg.lb_sub.text())
        check("弹窗标题是「填写输入」", dlg.lb_title.text() == "填写输入", dlg.lb_title.text())
        dlg.close()

        # ---------------- 10. 填写输入弹窗 + 摘要
        # 输入收进弹窗后，页面上只剩一句摘要（要填什么、还差什么）。
        print("\n--- 填写输入弹窗与摘要 ---")
        st._picked = ["t_pack_xhs"]
        st._input_values = {}
        st._rebuild_abilities()
        check("Skill 包的必填项没填时，摘要说清还差哪个",
              "要填" in st.lb_input_summary.text()
              and "还差" in st.lb_input_summary.text(),
              st.lb_input_summary.text())
        check("摘要列的是输入项的**标签**（不是 key）",
              "选题" in st.lb_input_summary.text(), st.lb_input_summary.text())

        dlg = InputsDialog(win, st._picked_skills(), st._input_values)
        dlg.editors["topic"].setPlainText("省考行测怎么提速")   # 选题是 textarea
        st._input_values.update(dlg.values())
        st._refresh_input_summary()
        check("填完必填项后，摘要改口说「必填项已填好」",
              "必填项已填好" in st.lb_input_summary.text(), st.lb_input_summary.text())
        check("填好的摘要标了 ok（主色变绿）",
              st.lb_input_summary.property("ok") in (True, 1),
              str(st.lb_input_summary.property("ok")))
        dlg.close()

        # 有默认值的输入（开关 / 下拉）不该被误报「还差」——
        # 用户没打开过弹窗时缓存是空的，得靠 Input.default 兜底。
        st._picked = ["xhs_from_gzh"]
        st._input_values = {}
        st._rebuild_abilities()
        check("开关 / 下拉这类有默认值的输入不会被误报「还差」",
              "还差" not in st.lb_input_summary.text(), st.lb_input_summary.text())
        check("摘要里写明「等 N 项」（输入多的时候不铺开）",
              "等" in st.lb_input_summary.text(), st.lb_input_summary.text())

        dlg = InputsDialog(win, st._picked_skills(), st._input_values)
        check("弹窗里每条输入都渲染了控件",
              set(dlg.editors) == {i.key for i in st._merged_inputs()},
              str(sorted(dlg.editors)))
        check("开关型输入按默认值预置（不是空着）",
              bool(dlg.editors["read_images"].isChecked()))
        check("下拉型输入按默认值预置",
              dlg.editors["pages"].currentText() == "8",
              dlg.editors["pages"].currentText())
        dlg.close()

        # 重开弹窗要带回上次填的值，不能每次都从空白开始
        st._input_values["url"] = "https://mp.weixin.qq.com/s/AbCdEf"
        dlg = InputsDialog(win, st._picked_skills(), st._input_values)
        check("重开弹窗会带回上次填的值",
              dlg.editors["url"].text() == "https://mp.weixin.qq.com/s/AbCdEf",
              dlg.editors["url"].text())
        dlg.close()

        # 「开始生成」时缺必填 → 直接把弹窗顶出来，而不是只弹个 toast
        st._picked = ["t_pack_xhs"]
        st._input_values = {}
        st._rebuild_abilities()
        _opened = []
        _orig_open = st._open_inputs
        st._open_inputs = lambda: (_opened.append(1), False)[1]
        try:
            st._start()
        finally:
            st._open_inputs = _orig_open
        check("缺必填就点生成 → 直接把填写输入弹窗顶出来",
              bool(_opened), str(_opened))
        check("并且没有真的开跑", not st._jobs, str(st._jobs))

    finally:
        # 只打扫自己造的那份临时图片目录。数据目录是整份临时目录，
        # 不在退出时删 —— 退场时删会和 Qt / Chromium 的收尾抢文件（退出码会变 139），
        # 交给下次启动时的「清上一轮的」就行。
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if fails:
        print(f"=== 失败 {len(fails)} 项 ===")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("=== 通过 全部 ===")


if __name__ == "__main__":
    main()
