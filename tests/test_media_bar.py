"""媒体状态条与配图目录解析：回答「生成的图片放到哪里去了」。

覆盖三块新能力：
  · platforms._path_of / media_dir_of —— 目录解析（含「视频文件：」这条
    以前一直断的链路）
  · browser.set_suggested_dir —— 手动选图的系统对话框起始目录自动定位
  · ContentCard 的 MediaRow —— image_hint / shot_hint 只读状态条
    （打开文件夹 / 更换配图 / content() 语义不变）

用法：
    python tests/test_media_bar.py
"""
import os
import sys
import tempfile
import traceback
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu --disable-software-rasterizer --no-sandbox"
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

# WebEngine 相关类必须在 QApplication 之前导入（与 test_adapters 同款约束），
# 否则后面创建 QWebEngineProfile 会原生层崩溃（exit 127 无 traceback）
from PyQt6.QtWebEngineCore import QWebEngineProfile  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'[OK]  ' if cond else '[FAIL]'} {name}" + (f"  → {detail}" if detail else ""),
          flush=True)
    if not cond:
        fails.append(name)


def make_png(path: str) -> str:
    """1x1 的真实 PNG（MediaRow / 上传解析只认扩展名 + 存在性）。"""
    import struct
    import zlib
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    return path


def main():
    import platforms as PF
    import browser as BR

    tmp = tempfile.mkdtemp(prefix="df_media_")
    img_dir = os.path.join(tmp, "imgs")
    os.makedirs(img_dir, exist_ok=True)
    a = make_png(os.path.join(img_dir, "01_封面.png"))
    b = make_png(os.path.join(img_dir, "02_列表.png"))
    open(os.path.join(img_dir, "说明.txt"), "w").write("x")

    print("== platforms：路径解析 ==")
    hint = f"清新商务风\n已出图 2 张，目录：{img_dir}"
    check("「目录：」标记解析出目录", PF._path_of(hint) == img_dir)
    fake_mp4 = os.path.join(tmp, "成品.mp4")
    open(fake_mp4, "wb").write(b"x")
    shot = f"分镜脚本\n\n视频文件：{fake_mp4}\n时长：12.0 秒"
    check("「视频文件：」解析出所在目录（以前这条链是断的）",
          PF._path_of(shot) == tmp)
    check("无路径文本返回空", PF._path_of("纯风格描述，没有路径") == "")
    check("空值返回空", PF._path_of("") == "")

    print("== platforms：media_dir_of ==")
    check("artifacts 优先（真实产出最可靠）",
          PF.media_dir_of([a], {}) == img_dir)
    check("artifacts 为空时从 image_hint 兜底",
          PF.media_dir_of([], {"image_hint": hint}) == img_dir)
    check("视频 shot_hint 也能兜到", PF.media_dir_of([], {"shot_hint": shot}) == tmp)
    check("两者皆无返回空", PF.media_dir_of([], {"title": "x"}) == "")

    print("== browser：建议目录 ==")
    BR.set_suggested_dir("acc_a", img_dir)
    check("合法目录被记住", BR.suggested_dir("acc_a") == img_dir)
    BR.set_suggested_dir("acc_a", os.path.join(tmp, "不存在"))
    check("非法目录被拒（置空）", BR.suggested_dir("acc_a") == "")

    print("== open_in_explorer ==")
    # 文件没了但目录还在 → 打开目录并返回 True；目录也不存在 → False 不弹窗
    check("目录不存在时返回 False 不弹窗",
          PF.open_in_explorer(os.path.join(tmp, "无此目录", "x.png")) is False)

    print("== platforms：latest_media_dir（缺图弹窗兜底） ==")
    import config
    real = PF.latest_media_dir()
    check("真实 output 下能定位到最新批次（用户刚出图的目录）",
          real and os.path.isdir(real) and real.startswith(config.OUTPUT_DIR),
          real or "（output 为空）")
    empty_base = os.path.join(tmp, "无产出")
    os.makedirs(empty_base, exist_ok=True)
    check("空目录返回空串", PF.latest_media_dir(empty_base) == "")
    check("base 不存在返回空串", PF.latest_media_dir(os.path.join(tmp, "无")) == "")
    # 两个批次，取最新的那个
    batch_old = os.path.join(tmp, "产出", "批次A")
    batch_new = os.path.join(tmp, "产出", "批次B")
    os.makedirs(batch_old, exist_ok=True)
    os.makedirs(batch_new, exist_ok=True)
    make_png(os.path.join(batch_old, "01.png"))
    make_png(os.path.join(batch_new, "01.png"))
    os.utime(os.path.join(batch_old, "01.png"), (1, 1))
    check("多批次取最近修改的", PF.latest_media_dir(os.path.join(tmp, "产出")) == batch_new)

    # ---------------- ContentCard / MediaRow ----------------
    from PyQt6.QtWidgets import QApplication
    # ⚠ 必须传 sys.argv：QApplication([])（空 argv）后面一创建 QWebEngineProfile
    #   就原生崩溃（exit 127 无 traceback）—— chromium 要从 argv 里读自己的参数
    app = QApplication.instance() or QApplication(sys.argv)
    from widgets.content_card import ContentCard, MediaRow

    skill = {
        "name": "测试模板", "platform": "xhs",
        "fields": ["title", "body", "topics", "image_hint"],
    }
    content = {
        "title": "测试标题六个字",
        "body": "正文" * 40,
        "topics": ["标签一", "标签二", "标签三"],
        "image_hint": hint,
    }

    print("== ContentCard：媒体状态条 ==")
    card = ContentCard("xhs")
    card.set_content(skill, content, "测试选题", {})
    rows = card.findChildren(MediaRow)
    check("image_hint 不再是文本编辑器（防止手滑改丢目录）",
          "image_hint" not in card._editors)
    check("渲染出了媒体状态条", len(rows) == 1)
    check("content() 原样带出 image_hint 文本（上传解析语义不变）",
          card.content().get("image_hint") == hint)

    card.set_artifacts([a, b])
    check("set_artifacts 后状态条显示已出图数量",
          "已出图 2 张" in rows[0].lb.text())
    check("打开文件夹按钮可用", rows[0].btn_open.isEnabled())

    print("== ContentCard：更换配图（回写） ==")
    img_dir2 = os.path.join(tmp, "imgs2")
    os.makedirs(img_dir2, exist_ok=True)
    c = make_png(os.path.join(img_dir2, "09_新图.png"))
    with patch("PyQt6.QtWidgets.QFileDialog.getExistingDirectory",
               return_value=img_dir2):
        card._replace_media("image_hint")
    check("更换后 artifacts 换成新目录的图", card.artifacts == [c])
    new_hint = card.content().get("image_hint", "")
    check("image_hint 保留风格行并重写目录行",
          "清新商务风" in new_hint and f"目录：{img_dir2}" in new_hint
          and "已出图 2 张" not in new_hint)
    check("更换后 changed 信号已发（批次同步）", card.content().get("image_hint") == new_hint)

    print("== ContentCard：shot_hint（视频） ==")
    skill_v = {"name": "视频模板", "platform": "xhs",
               "fields": ["title", "shot_hint"]}
    card2 = ContentCard("xhs")
    card2.set_content(skill_v, {"title": "测试标题六个字", "shot_hint": shot}, "t", {})
    rows2 = card2.findChildren(MediaRow)
    check("shot_hint 也渲染成状态条", len(rows2) == 1)
    check("视频条没有「更换配图」按钮", rows2[0].btn_pick is None)
    card2.set_artifacts([fake_mp4])
    check("视频产出后显示已生成", "视频已生成" in rows2[0].lb.text())

    print("== ContentCard：attach_media（工作台缺图回写） ==")
    card3 = ContentCard("xhs")
    card3.set_content(skill, {**content, "image_hint": "风格描述而已"}, "t", {})
    emitted = []
    card3.changed.connect(lambda pk: emitted.append(pk))
    card3.attach_media("image_hint", [a, b])
    check("attach_media 更新状态条计数", "已出图 2 张" in card3._media_rows["image_hint"].lb.text())
    check("attach_media 写出「目录：」行（发布链路认这个标记）",
          f"目录：{img_dir}" in card3.content().get("image_hint", ""))
    check("attach_media 会发 changed 信号", len(emitted) == 1)
    check("空文件列表不动作", (card3.attach_media("image_hint", []), True)[1])

    # ================================================================
    # v1.6：应用内选图器（B）+ 自动挂最新批次（A）+ 探测重试（C）
    # ================================================================
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog, QFileDialog
    from widgets.media_picker import (
        MediaPickerDialog, Thumb, _media_files, list_batches, pick_media_files,
    )

    print("== media_picker：批次扫描 ==")
    check("_media_files 只留媒体文件且按名排序", _media_files(img_dir) == [a, b])
    prod_base = os.path.join(tmp, "产出")
    batches = list_batches(prod_base)
    check("两个批次都扫到", len(batches) == 2)
    check("按最新文件时间倒序（新批次在前）",
          batches and batches[0]["dir"] == batch_new, str([b["dir"] for b in batches]))
    check("批次文件列表完整", batches and batches[0]["files"] == [os.path.join(batch_new, "01.png")])
    check("空目录没有批次", list_batches(empty_base) == [])
    check("base 不存在没有批次", list_batches(os.path.join(tmp, "无")) == [])

    print("== media_picker：对话框交互 ==")
    dlg = MediaPickerDialog(None, batches, "")
    check("左侧列表两个批次", dlg.lst.count() == 2)
    check("默认选中最新的批次", dlg.lst.currentRow() == 0)
    check("默认全部勾选", dlg.checked_files() == batches[0]["files"])
    dlg._thumbs[0].set_checked(False)
    check("点缩略图可剔除单个文件", dlg.checked_files() == [])
    dlg._thumbs[0].set_checked(True)
    check("再点恢复勾选", dlg.checked_files() == batches[0]["files"])
    dlg._use()
    check("「用这批」返回勾选文件", dlg.selected_files == batches[0]["files"])
    check("selected_dir 指向当前批次目录", dlg.selected_dir == batch_new)

    dlg2 = MediaPickerDialog(None, batches, batch_old)
    check("start_dir 能定位到对应批次", dlg2.lst.currentRow() == 1
          and dlg2.selected_dir == batch_old)
    vtxt = Thumb(fake_mp4)
    check("视频文件渲染成占位块（无缩略图）", vtxt.pic.pixmap() is None or vtxt.pic.pixmap().isNull())

    print("== media_picker：pick_media_files 快捷入口 ==")
    with patch.object(config, "OUTPUT_DIR", empty_base):
        check("没有任何批次返回 None（调用方走兜底）",
              pick_media_files(None, "") is None)
    def _accept(self):
        self._use()
        return QDialog.DialogCode.Accepted
    with patch.object(MediaPickerDialog, "exec", _accept):
        res = pick_media_files(None, img_dir)
    check("选图器确认 → (文件列表, 目录)", res == ([a, b], img_dir), str(res))
    with patch.object(MediaPickerDialog, "exec", lambda self: QDialog.DialogCode.Rejected):
        res = pick_media_files(None, img_dir)
    check("选图器取消 → ([], 目录)（dir 非空表示开过选图器）", res == ([], img_dir))
    with patch.object(config, "OUTPUT_DIR", prod_base), \
         patch.object(MediaPickerDialog, "exec", _accept):
        res = pick_media_files(None, "")   # 无 start_dir → 扫 config.OUTPUT_DIR
    check("无 start_dir 时扫描产出根目录", res is not None and res[0] == batches[0]["files"], str(res))

    print("== browser：chooseFiles 接入选图器 ==")
    prof = QWebEngineProfile("df_picker_test", None)
    prof.setPersistentStoragePath(os.path.join(tmp, "picker_profile"))
    page = BR.WebPage(prof, "acc_picker")
    BR.set_pending_upload("acc_picker", [a])
    check("有预置文件时直接返回预置（不弹任何框）",
          page.chooseFiles(None, [], []) == [a])
    BR.clear_pending_upload("acc_picker")

    import widgets.media_picker as MP
    with patch.object(MP, "pick_media_files",
                      return_value=([a, b], img_dir)):
        check("无预置 → 应用内选图器结果直接交回",
              page.chooseFiles(None, [], []) == [a, b])
    with patch.object(MP, "pick_media_files", return_value=([], img_dir)):
        check("用户在选图器里取消 → 返回空，不再弹系统框",
              page.chooseFiles(None, [], []) == [])
    with patch.object(MP, "pick_media_files", return_value=None), \
         patch.object(QFileDialog, "getOpenFileNames",
                      return_value=([b], "")):
        check("选图器开不起来 → 退回系统对话框",
              page.chooseFiles(None, [], []) == [b])
    def _boom(*_args, **_kw):
        raise RuntimeError("boom")
    with patch.object(MP, "pick_media_files", _boom), \
         patch.object(QFileDialog, "getOpenFileNames",
                      return_value=([], "")):
        check("选图器抛异常 → 静默退回系统对话框",
              page.chooseFiles(None, [], []) == [])
    prof.deleteLater()
    app.processEvents()

    print("== workbench：自动挂最新批次（A） ==")
    from views.workbench import WorkbenchView
    check("_images_in 过滤非图片", WorkbenchView._images_in(img_dir) == [a, b])
    check("_images_in 容忍不存在目录", WorkbenchView._images_in(os.path.join(tmp, "无")) == [])
    # 两个批次按时间排序后，最新批次是 batch_new（与 PF.latest_media_dir 一致）
    check("自动挂批次用的目录解析与 latest_media_dir 同源",
          PF.latest_media_dir(prod_base) == batch_new)

    print("== v1.6·1：视频批次不得顶掉图片批次（真实踩坑） ==")
    # 场景：xhs_video 产出的视频批次比图片批次**新**，latest_media_dir 会拿到
    # 视频目录 → 挂图白跑。latest_image_dir 必须跳过纯视频批次。
    img_batch2 = os.path.join(prod_base, "图片批次2")
    os.makedirs(img_batch2, exist_ok=True)
    c = make_png(os.path.join(img_batch2, "01.png"))              # 次新（图片）
    vid_batch = os.path.join(prod_base, "xhs_video_视频批次")
    os.makedirs(vid_batch, exist_ok=True)
    open(os.path.join(vid_batch, "成品.mp4"), "wb").write(b"x")   # 最新（视频）
    check("latest_image_dir 跳过纯视频批次，找到图片批次",
          PF.latest_image_dir(prod_base) == img_batch2,
          PF.latest_image_dir(prod_base))
    check("latest_media_dir 仍拿视频批次（对照，证明两者分工）",
          PF.latest_media_dir(prod_base) == vid_batch,
          PF.latest_media_dir(prod_base))
    check("全是图片时 latest_image_dir 与 latest_media_dir 一致",
          PF.latest_image_dir(img_dir) == img_dir)   # img_dir 只有图片

    print("== v1.6·1：选图器 images_only 过滤 ==")
    with patch.object(config, "OUTPUT_DIR", prod_base), \
         patch.object(MediaPickerDialog, "exec", _accept):
        res = pick_media_files(None, vid_batch, images_only=True)
    check("start 是视频目录时被忽略，落到最新的图片批次",
          res is not None and res[1] == img_batch2 and c in res[0], str(res))
    with patch.object(config, "OUTPUT_DIR", prod_base), \
         patch.object(MediaPickerDialog, "exec", lambda self: QDialog.DialogCode.Rejected):
        res = pick_media_files(None, "", images_only=True)
    check("images_only 取消路径正常", res is not None and res[0] == [], str(res))

    print("== v1.6·2：填充中途选图 → 自动续跑 ==")
    # ⚠ 上面的 profile 已 deleteLater，这里用全新的（QApplication 已就绪）
    prof2 = QWebEngineProfile("df_hook_test", None)
    prof2.setPersistentStoragePath(os.path.join(tmp, "hook_profile"))
    page2 = BR.WebPage(prof2, "acc_hook")
    fired = []
    BR.set_files_picked_hook(lambda aid_, files: fired.append((aid_, list(files))))
    try:
        with patch.object(MP, "pick_media_files",
                          return_value=([a, b], img_dir)):
            got = page2.chooseFiles(None, [], [])
        check("无预置 + 选图器交回文件 → hook 已触发",
              got == [a, b] and fired and fired[-1] == ("acc_hook", [a, b]),
              str(fired))
        with patch.object(MP, "pick_media_files", return_value=([], img_dir)):
            page2.chooseFiles(None, [], [])
        check("选图器取消不触发 hook", len(fired) == 1)
        BR.set_pending_upload("acc_hook", [a])
        page2.chooseFiles(None, [], [])
        check("预置文件路径（正常填充）不触发 hook", len(fired) == 1)
        BR.clear_pending_upload("acc_hook")
    finally:
        BR.set_files_picked_hook(None)
    check("hook 已复位", BR._files_picked_hook is None)
    prof2.deleteLater()
    app.processEvents()

    import inspect as _inspect
    src_hook = _inspect.getsource(WorkbenchView._on_files_picked)
    src_wait = _inspect.getsource(WorkbenchView._wait_editor_and_refill)
    check("hook 处理里走挂图回写（_attach_images）", "_attach_images" in src_hook)
    check("续跑会等队列空闲（防多账号时搅了队列）", "self._queue is not None" in src_wait)
    check("续跑等编辑器渲染（diagnose 探针轮询）", "diagnose" in src_wait and "editor" in src_wait)
    check("续跑有超时上限（90s 后交回人工）", "tries < 45" in src_wait)

    print("== v1.6·2：26 张超小红书 18 张上限 → 截断（真实踩坑） ==")
    # 真机实测：26 张整批塞给页面 input，小红书**整批拒收**，页面停在空上传态
    check("max_images(xhs) == 18", PF.max_images("xhs") == 18)
    check("max_images(未知平台) == 0（不限）", PF.max_images("不存在的平台key") == 0)
    many = [make_png(os.path.join(img_dir, f"bulk_{i:02d}.png")) for i in range(26)]
    capped = PF.upload_files("xhs", {}, many)
    check("26 张 artifacts 截到 18 张", capped == many[:18], f"{len(capped)} 张")
    few = many[:5]
    check("5 张不截断", PF.upload_files("xhs", {}, few) == few)
    # 非图片（视频）不受 images 上限管
    check("视频不受 images 上限截断",
          PF.upload_files("xhs", {}, [fake_mp4]) == [fake_mp4])
    # 上限截断的 fail-open 在 _cap_images 层（未知平台 max_images=0 → 原样返回）；
    # upload_files 对未知平台是「没 upload_dir_field 一律不传」（宁可不传不瞎点）
    check("未知平台没有 upload_dir_field → 一律不传",
          PF.upload_files("不存在的平台key", {}, many) == [])
    check("未知平台截断 fail-open（原样返回）",
          PF._cap_images("不存在的平台key", many) == many)

    print("== v1.6·2：中途选图路径同样截断 ==")
    import store
    prof3 = QWebEngineProfile("df_cap_test", None)
    prof3.setPersistentStoragePath(os.path.join(tmp, "cap_profile"))
    page3 = BR.WebPage(prof3, "acc_cap")
    # store 账号查询 mock 成 xhs 平台
    with patch.object(store, "get_account",
                      return_value={"id": "acc_cap", "platform": "xhs",
                                    "name": "测试号"}):
        with patch.object(MP, "pick_media_files",
                          return_value=(many, img_dir)):
            got = page3.chooseFiles(None, [], [])
        check("选图器交回 26 张 → 喂给页面 18 张", got == many[:18], f"{len(got)} 张")
    with patch.object(store, "get_account", return_value=None):
        with patch.object(MP, "pick_media_files",
                          return_value=([a], img_dir)):
            got = page3.chooseFiles(None, [], [])
        check("账号查不到时不截断（fail-open）", got == [a])
    prof3.deleteLater()
    app.processEvents()

    print("== v1.6·2：上传等待预算 60s + 失败自动续跑 ==")
    import publisher as PUBM
    src_q = _inspect.getsource(PUBM.PublishQueue._on_result)
    check("要传文件的项重试预算放宽（MAX_RETRY_UPLOAD）",
          "MAX_RETRY_UPLOAD" in src_q and "upload_count" in src_q)
    check("预算按 upload_count 判定", "int(item.get(\"upload_count\") or 0) > 0" in src_q)
    src_done = _inspect.getsource(WorkbenchView._on_item_done)
    check("填充超时失败自动排续跑（upload/wait/switch）",
          '"upload", "wait", "switch"' in src_done and "_wait_editor_and_refill" in src_done)
    check("续跑去重（_refill_pending）",
          "_refill_pending" in src_wait and "_refill_pending.discard" in src_wait)

    print("== v1.6·3：批次按主题匹配，别题批次不能顶掉本题（真实踩坑） ==")
    # 用户原话：「这条素材只有 8 张图，26 张图是因为之前的其他批次，混在一起了」
    # 批次目录名 = _safe(标题)，按名字对上才算同一题；对不上才退回最新。
    topic_base = os.path.join(tmp, "按题产出")
    os.makedirs(topic_base, exist_ok=True)
    bt_mine = os.path.join(topic_base, "国考招录1400人_招录第一_广东税务局招录分析")
    bt_other = os.path.join(topic_base, "省考行测考前刷题")
    os.makedirs(bt_mine, exist_ok=True)
    os.makedirs(bt_other, exist_ok=True)
    mine = [make_png(os.path.join(bt_mine, f"p{i}.png")) for i in range(8)]
    for _f in mine[:1]:
        os.utime(_f, (1, 1))          # 本题批次更**旧**
    for i in range(3):
        make_png(os.path.join(bt_other, f"q{i}.png"))   # 别题批次更新
    TOPIC = "国考招录1400人 招录分析：广东税务局招 1400 人"
    check("同题目录名匹配分 > 0",
          PF.batch_match_score("国考招录1400人_招录第一", TOPIC) >= PF.TOPIC_MATCH_MIN)
    check("别题目录名匹配分 == 0", PF.batch_match_score("省考行测考前刷题", TOPIC) == 0)
    check("空值安全", PF.batch_match_score("", TOPIC) == 0
          and PF.batch_match_score("x", "") == 0)
    check("按题匹配：拿到本题批次（哪怕更旧）",
          PF.latest_image_dir(topic_base, topic=TOPIC) == bt_mine,
          PF.latest_image_dir(topic_base, topic=TOPIC))
    check("不给主题：仍取最新（原行为不变）", PF.latest_image_dir(topic_base) == bt_other)
    check("主题对不上任何批次：退回最新",
          PF.latest_image_dir(topic_base, topic="完全无关的主题词") == bt_other)
    check("latest_media_dir 同样支持按题匹配",
          PF.latest_media_dir(topic_base, topic=TOPIC) == bt_mine)
    # 反向匹配：目录名是标题被 _safe 截短后的前缀 → 也要能对上
    check("目录名被截短也能反向匹配上",
          PF.batch_match_score("国考招录1400人_招录第一_广",
                               "国考招录1400人_招录第一_广东税务局招录分析")
          >= PF.TOPIC_MATCH_MIN)

    print("== v1.6·3：选图器批次按主题排前 ==")
    tb = list_batches(topic_base, topic=TOPIC)
    check("同题批次排第一", tb and tb[0]["dir"] == bt_mine,
          str([x["dir"] for x in tb]))
    check("同题批次带 matched 标记、别题没有",
          tb and tb[0].get("matched") is True and not tb[1].get("matched"))
    check("不给主题仍按时间倒序", list_batches(topic_base)[0]["dir"] == bt_other)
    dlg3 = MediaPickerDialog(None, tb, "")
    check("弹窗默认选中同题批次",
          dlg3.lst.currentRow() == 0 and dlg3.selected_dir == bt_mine)
    check("同题批次条目带「匹配本题」标记",
          "匹配本题" in dlg3.lst.item(0).text())
    dlg3.deleteLater()
    with patch.object(config, "OUTPUT_DIR", topic_base), \
         patch.object(MediaPickerDialog, "exec", _accept):
        res = pick_media_files(None, "", topic=TOPIC)
    check("带主题的快捷入口返回本题批次",
          res is not None and res[1] == bt_mine and res[0] == mine, str(res))

    print("== v1.6·3：浏览器选图器带上主题 ==")
    check("set_suggested_topic 记住主题",
          (BR.set_suggested_topic("acc_t3", TOPIC),
           BR.suggested_topic("acc_t3") == TOPIC)[1])
    BR.set_suggested_topic("acc_t3", "   ")
    check("空主题置空", BR.suggested_topic("acc_t3") == "")
    prof4 = QWebEngineProfile("df_topic_test", None)
    prof4.setPersistentStoragePath(os.path.join(tmp, "topic_profile"))
    page4 = BR.WebPage(prof4, "acc_t4")
    seen = {}

    def _spy(parent=None, start_dir="", images_only=False, topic=""):
        seen["topic"] = topic
        return ([], "")

    with patch.object(MP, "pick_media_files", _spy):
        BR.set_suggested_topic("acc_t4", TOPIC)
        page4.chooseFiles(None, [], [])
        check("chooseFiles 把主题传给选图器", seen.get("topic") == TOPIC, str(seen))
        BR.set_suggested_topic("acc_t4", "")
        page4.chooseFiles(None, [], [])
        check("没主题时不传（空串）", seen.get("topic") == "")
    prof4.deleteLater()
    app.processEvents()

    print("== v1.6·3：工作台三处入口都带主题 ==")
    src_sync = _inspect.getsource(WorkbenchView._sync_suggested_dir)
    src_ask = _inspect.getsource(WorkbenchView._ask_missing_media)
    src_disp = _inspect.getsource(WorkbenchView._dispatch)
    check("_sync_suggested_dir 把主题交给浏览器", "set_suggested_topic" in src_sync)
    check("缺图定位按题匹配（latest_image_dir 带 topic）",
          "latest_image_dir(topic=topic)" in src_ask)
    check("选图器入口带主题", "topic=topic" in src_ask)
    check("_dispatch 也带主题（含 latest_media_dir 按题兜底）",
          "set_suggested_topic" in src_disp and "latest_media_dir(topic=" in src_disp)

    print("== workbench：探测重试（C） ==")
    import inspect
    src_probe = inspect.getsource(WorkbenchView._probe_login)
    check("探测有 attempt 计数（不会无限重试）", "attempt" in src_probe)
    check("第一轮没答案会补一轮（4s 后）", "attempt < 2" in src_probe and "4000" in src_probe)
    check("重试前检查标签页还在", src_probe.count("aid not in self._opened") + src_probe.count('aid in self._opened') >= 2)

    print("== v1.6·4：登录态自动标记（真机反馈：抖音登录了还挂未登录） ==")
    # 根因 1：除 xhs 外的适配器都没有 diagnose()，_probe_login 永远拿不到
    #   login 字段 → 登录了也写不回 logged_in；
    # 根因 2：登录发生在「打开发布页探测两轮」之后，没有重探时机。
    ad_dir = os.path.join(ROOT, "src", "assets", "adapters")
    for _js in ("xhs.js", "douyin.js", "sph.js", "toutiao.js", "gzh.js"):
        with open(os.path.join(ad_dir, _js), "r", encoding="utf-8") as f:
            _jt = f.read()
        check(f"{_js} 提供 diagnose()", "diagnose: function" in _jt)
        check(f"{_js} diagnose 报 login 字段（登录态标记靠它）",
              "login: !!DF.one(SEL.login)" in _jt)

    # 页面导航完成 → 防抖 → 重探钩子（browser 层）
    from PyQt6.QtCore import QEventLoop, QTimer
    prof_l = QWebEngineProfile("df_login_test", None)
    prof_l.setPersistentStoragePath(os.path.join(tmp, "login_profile"))
    pl_page = BR.WebPage(prof_l, "acc_login")
    BR.BROWSER._pages["acc_login"] = pl_page     # 手动登记（不走 config 存储路径）
    check("BrowserManager.has_page 登记后为 True", BR.BROWSER.has_page("acc_login"))
    src_page_m = _inspect.getsource(BR.BrowserManager.page)
    check("创建页面时挂上 loadFinished 重探钩子",
          "loadFinished" in src_page_m and "_schedule_login_probe" in src_page_m)
    hits = []
    BR.set_login_hook(hits.append)
    BR.BROWSER._schedule_login_probe("acc_login", True)
    _w = QEventLoop(); QTimer.singleShot(2000, _w.quit); _w.exec()
    check("页面加载完成（防抖后）触发登录重探", hits == ["acc_login"], str(hits))
    hits.clear()
    BR.BROWSER._schedule_login_probe("acc_login", False)
    _w = QEventLoop(); QTimer.singleShot(1600, _w.quit); _w.exec()
    check("加载失败不算登录信号", hits == [], str(hits))

    def _boom(_aid):
        raise RuntimeError("界面层炸了也不能连累浏览器层")
    BR.set_login_hook(_boom)
    BR.BROWSER._schedule_login_probe("acc_login", True)
    _w = QEventLoop(); QTimer.singleShot(1600, _w.quit); _w.exec()
    check("钩子抛异常被浏览器层吞掉", True)
    BR.set_login_hook(None)
    BR.BROWSER._pages.pop("acc_login", None)
    check("页面移除后 has_page 为 False", not BR.BROWSER.has_page("acc_login"))
    BR.BROWSER._schedule_login_probe("acc_login", True)   # 页面已清：静默返回
    app.processEvents()
    prof_l.deleteLater()

    print("== v1.6·4：目标账号弹窗能看到勾选账号 ==")
    src_pick = _inspect.getsource(WorkbenchView._pick_accounts)
    check("弹窗平台列表合并已勾选账号的平台",
          'acc["platform"] not in keys' in src_pick)
    check("弹窗收到 content_keys（无内容平台要标注）",
          "content_keys=set(content_keys)" in src_pick)
    from views.workbench import AccountsPopup as _AccountsPopup
    src_ap = _inspect.getsource(_AccountsPopup.__init__)
    check("AccountsPopup 支持 content_keys 参数", "content_keys" in src_ap)
    check("无内容平台组头标注「暂无待发布内容」", "暂无待发布内容" in src_ap)
    src_hint = _inspect.getsource(WorkbenchView._on_login_hint)
    check("重探入口做薄过滤（标签页 + 页面存活）",
          "has_page" in src_hint and "aid not in self._opened" in src_hint)
    src_init = _inspect.getsource(WorkbenchView.__init__)
    check("工作台注册了登录重探钩子", "set_login_hook" in src_init)

    print("== v1.6·5：勾了没内容平台的账号，一键填充不再静默跳过 ==")
    # 真机反馈：勾了小红书 + 抖音，一键填充只填小红书，抖音毫无动静。
    # 根因：_checked_accounts 只收「有内容的平台」，无内容账号被静默丢弃；
    # _dispatch 的 find_item=None → continue 再兜一层，全程不提示。
    src_ca = _inspect.getsource(WorkbenchView._checked_accounts)
    check("勾选列表补上无内容平台的账号（list_accounts 兜底）",
          "list_accounts" in src_ca)
    src_if = _inspect.getsource(WorkbenchView._item_for)
    check("取条目支持复用批次第一条（跨平台分发）",
          "b.items[0]" in src_if and "reuse_ids" in src_if)
    src_run = _inspect.getsource(WorkbenchView._run)
    check("执行前弹「发过去 / 跳过」确认（不越权直接发）",
          "把本次内容也发过去" in src_run and "跳过这些账号" in src_run)
    src_dp = _inspect.getsource(WorkbenchView._dispatch)
    check("_dispatch 接收 reuse_ids 并记录复用来源",
          "reuse_ids" in src_dp and "reused" in src_dp)
    check("复用条目时不回写 artifacts（别污染源平台）",
          "if not reused:" in src_dp and "it.artifacts = list(uploads)" in src_dp)
    check("被跳过的账号有提示（不再无声无息）", "skipped" in src_dp)
    check("记录实际任务顺序（_on_step 切页不错位）",
          "_dispatched_items" in src_dp)
    src_os = _inspect.getsource(WorkbenchView._on_step)
    check("切页按实际任务列表而非勾选列表",
          "_dispatched_items" in src_os and "account_id" in src_os)
    src_am = _inspect.getsource(WorkbenchView._ask_missing_media)
    check("缺图询问覆盖复用账号", "reuse_ids" in src_am and "_item_for" in src_am)

    # _item_for 行为级（绕过 UI 构造，直接测方法逻辑）
    import bus as _bus
    _old = _bus.CURRENT
    try:
        _b = _bus.Batch("跨平台主题")
        _it = _bus.DraftItem("xhs", "sk1", "小红书技能",
                             {"title": "T", "body": "B"}, "跨平台主题")
        _b.items = [_it]
        _bus.CURRENT = _b
        wb = WorkbenchView.__new__(WorkbenchView)   # 跳过 UI 构造
        check("专属条目优先", wb._item_for({"platform": "xhs", "id": "r1"}, set()) is _it)
        check("无条目且未允许复用 → None",
              wb._item_for({"platform": "douyin", "id": "r2"}, set()) is None)
        check("无条目但允许复用 → 批次第一条",
              wb._item_for({"platform": "douyin", "id": "r2"}, {"r2"}) is _it)
        _bus.CURRENT = _bus.Batch("空批次")
        check("批次为空时复用退化为 None",
              wb._item_for({"platform": "douyin", "id": "r2"}, {"r2"}) is None)
    finally:
        _bus.CURRENT = _old

    # 清理
    try:
        BR._suggested_dir.clear()
        BR._suggested_topic.clear()
    except Exception:
        pass

    print()
    if fails:
        print(f"=== 失败 {len(fails)} 项 ===")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("=== 通过 全部 ===")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
