"""用真实 WebEngine 的模拟页验证小红书填充脚本。

为什么值得单独写一个：`xhs.js` 里的选择器全靠猜页面结构，而页面结构
在真实环境里看不到（要登录、要点进去）。这个测试把「我知道的页面长相」
做成两个本地 fixture，直接在真 Chromium 里跑一遍注入脚本，
就能证明三件事：

  1. 标题**没**填进那个 4px 宽的隐藏替身（v-model 不 commit 的那个）
  2. 正文真的写进了 contenteditable
  3. 停在「视频页」时会返回 retry:true 而不是报死，队列也会真的重试

用法：
    python tests/test_fill_xhs.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu --disable-software-rasterizer --no-sandbox"
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

fails = []


def check(name, cond, detail=""):
    print(f"  {'[OK]  ' if cond else '[FAIL]'} {name}" + (f"  → {detail}" if detail else ""),
          flush=True)
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- 页面 fixture
# 关键点：标题框故意放一个 4px 宽的「隐藏替身」在前面（真页面就是这样），
# 不带宽度过滤的取值会命中它，而它填了等于没填。
_COMMON_STYLE = """
  body { font-family: sans-serif; margin: 0; padding: 20px; }
  .decoy { width: 4px; height: 20px; }
  .real  { width: 320px; height: 32px; }
  .editor { width: 480px; height: 160px; border: 1px solid #ccc; }
  .tab { display: inline-block; padding: 6px 14px; border: 1px solid #ddd; }
"""

# 正确的「上传图文」页：标题 + 正文编辑器都在
# file input 上挂了计数，用来验证「该传图时真的点了上传控件、且只点一次」
FIXTURE_IMAGE = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_COMMON_STYLE}</style></head><body>
  <div class="tabs">
    <span class="tab" id="tab-video">上传视频</span>
    <span class="tab" id="tab-image">上传图文</span>
  </div>
  <div id="form">
    <input class="d-text decoy" id="decoy" placeholder="请输入标题" value="">
    <input class="d-text real"  id="real"  placeholder="请输入标题" value="">
    <div id="editor" class="editor" contenteditable="true" placeholder="描述"></div>
  </div>
  <input type="file" id="file" accept="image/*" style="display:none">
  <script>
    window.__fileClicks = 0;
    document.getElementById('file').addEventListener('click', function (e) {{
      window.__fileClicks++;
      e.preventDefault();   // 别真弹文件框
    }});
  </script>
</body></html>"""

# 停在「上传视频」页：没有标题框、没有正文编辑器，但有「上传图文」入口和上传控件
FIXTURE_VIDEO = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_COMMON_STYLE}</style></head><body>
  <div class="tabs">
    <span class="tab" id="tab-video">上传视频</span>
    <span class="tab" id="tab-image">上传图文</span>
  </div>
  <div id="dropzone">拖拽视频到此或点击上传</div>
  <input type="file" id="file" accept="video/*" style="display:none">
</body></html>"""

# 「要先上传图片才有编辑框」的图文页 —— 真实小红书图文页就是这个样子：
# 没有标题框、没有正文编辑器，只有一个「上传图片」按钮（或隐藏的 file input）。
# 以前脚本靠「有没有文件可传」决定点不点上传，于是内容里没配图时一步都不点，
# 永远停在「没有找到正文编辑器」。
FIXTURE_NEED_UPLOAD = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_COMMON_STYLE}</style></head><body>
  <div id="dropzone">上传图片，或写文字生成图片</div>
  <button id="up">上传图片</button>
  <input type="file" id="file" accept="image/*" style="display:none">
  <script>
    window.__fileClicks = 0;
    document.getElementById('file').addEventListener('click', function (e) {{
      window.__fileClicks++;
      e.preventDefault();   // 别真弹文件框
    }});
  </script>
</body></html>"""


def main():
    print("\n=== 小红书填充脚本（真实 WebEngine 模拟页）===\n")

    from PyQt6.QtCore import QTimer, QUrl
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineCore import QWebEnginePage

    import publisher as PUB
    import platforms as PF

    app = QApplication(sys.argv)

    def run_on(html, script, timeout=45000):
        """在离线页面上跑一段脚本，返回 (结果 dict, 页面探针 dict)。

        ⚠ 兜底定时器必须带「已完成」令牌：整个套件共用一个 QApplication
        反复 exec/quit，上一节遗留的定时器会在下一节的 exec 里触发，
        把还没跑完的节提前杀掉（实测：与其它重套件并行跑时，
        「停在视频页」一节被杀成空结果 {}）。令牌让残定时器变空操作。
        ⚠ 兜底只防「真卡死」，不当性能断言 —— 进程冷启动（前一个套件
        刚释放大量内存 + 首个 Chromium 子进程拉起）在老机器上可能 >20s，
        兜底给足 45s（正常路径 ~1s 就返回，不受影响）。
        """
        page = QWebEnginePage()
        out = {}
        done = {"v": False}

        def after_load(ok):
            QTimer.singleShot(250, lambda: page.runJavaScript(
                script, lambda r: (out.__setitem__("res", PUB.parse_result(r)),
                                   _probe(page, out, app))))

        page.loadFinished.connect(after_load)
        page.setHtml(html, QUrl("https://creator.xiaohongshu.com/publish/publish?target=image"))
        QTimer.singleShot(timeout, lambda: (not done["v"]) and app.quit())
        app.exec()
        done["v"] = True
        return out.get("res"), out.get("probe")

    def _probe(page, out, app):
        probe = ("(function(){var r={};"
                 "var d=document.getElementById('decoy');"
                 "var t=document.getElementById('real');"
                 "var e=document.getElementById('editor');"
                 "r.decoy = d ? d.value : null;"
                 "r.title = t ? t.value : null;"
                 "r.body  = e ? (e.innerText||e.textContent||'') : null;"
                 "r.clicks = window.__fileClicks || 0;"
                 "return JSON.stringify(r);})()")
        page.runJavaScript(probe, lambda r: (out.__setitem__("probe", r), app.quit()))

    # ---------------- 1. 正确的图文页：应该填成功
    print("--- 正确的图文页 ---")
    payload = {"title": "广东省考题型题量", "body": "行测共100题。\n申论两小题一大题。",
               "topics": ["公考", "广东省考"]}
    script = PUB.build_fill_script("xhs", "xhs.js", payload)
    check("填充脚本能拼出来", bool(script))

    res, probe = run_on(FIXTURE_IMAGE, script)
    res = res or {}
    check("填充返回 ok", bool(res.get("ok")), str(res.get("message", ""))[:60])
    check("标题被标记为已填", "title" in (res.get("filled") or []))
    check("正文被标记为已填", "body" in (res.get("filled") or []))

    probe = PUB.parse_result(probe) if probe else {}
    check("标题填进了真框（不是 4px 隐藏替身）",
          probe.get("title") == "广东省考题型题量",
          f"真框={probe.get('title')!r} 替身={probe.get('decoy')!r}")
    check("隐藏替身始终为空", not probe.get("decoy"), repr(probe.get("decoy")))
    check("正文写进了编辑器",
          "行测共100题" in (probe.get("body") or ""),
          repr((probe.get("body") or "")[:40]))
    check("话题以 # 形式追加在正文后",
          "#公考" in (probe.get("body") or "") and "#广东省考" in (probe.get("body") or ""))

    # ---------------- 2. 配图上传：该点一次，且只点一次
    # 用「还没有编辑框」的页面 —— 图文页是先传图才渲染编辑框的，
    # 所以上传只发生在编辑框还没出现的时候。
    print("\n--- 配图上传 ---")
    page2 = QWebEnginePage()
    seq_out = {"res": []}

    def seq_done(_ok):
        def step(i):
            if i >= 2:
                page2.runJavaScript(
                    "JSON.stringify({clicks: window.__fileClicks})",
                    lambda r: (seq_out.update(probe=PUB.parse_result(r)), app.quit()))
                return
            # 第一次：宿主告诉脚本「这个平台要先传」且有 3 个文件；
            # 第二次：重试，不该再点上传。
            # _want_upload 每次都要带 —— 它是「平台要求先传素材」，
            # 与「这次有几个文件」是两回事。
            payload = {"title": "广东省考题型题量", "body": "行测共100题。",
                       "_want_upload": True,
                       "_upload_count": 3 if i == 0 else 0}
            sc = PUB.build_fill_script("xhs", "xhs.js", payload)
            page2.runJavaScript(sc, lambda r, i=i: (
                seq_out["res"].append(PUB.parse_result(r)), step(i + 1)))

        QTimer.singleShot(250, lambda: step(0))

    page2.loadFinished.connect(seq_done)
    page2.setHtml(FIXTURE_NEED_UPLOAD,
                  QUrl("https://creator.xiaohongshu.com/publish/publish?target=image"))
    sec2_done = {"v": False}
    QTimer.singleShot(45000, lambda: (not sec2_done["v"]) and app.quit())
    app.exec()
    sec2_done["v"] = True

    while len(seq_out["res"]) < 2:
        seq_out["res"].append({})
    r0, r1 = seq_out["res"][0], seq_out["res"][1]
    check("第一次带文件时点了上传控件并要求重试",
          bool(r0.get("retry")) and r0.get("stage") == "upload", str(r0))
    check("提示里说清了在传几个文件", "3" in str(r0.get("message", "")),
          str(r0.get("message")))
    check("重试时不再点上传（上传控件总共只被点了一次）",
          (seq_out.get("probe") or {}).get("clicks") == 1, str(seq_out.get("probe")))
    check("上传后编辑框还没出来 → 继续等，不报死",
          bool(r1.get("retry")) and r1.get("stage") == "wait", str(r1))

    # ---------------- 2·五、要先传图才有编辑框：没图可传时交人工，别死等
    # 这是用户真实报障的那条路径：内容里没有配图 → 以前一步都不点上传 →
    # 永远停在「没有找到正文编辑器」。现在应该点开上传、把控制权交回用户。
    print("\n--- 平台要求先传素材，但这次没图可传 ---")
    r_nu, probe_nu = run_on(
        FIXTURE_NEED_UPLOAD,
        PUB.build_fill_script("xhs", "xhs.js",
                              {"title": "标题", "body": "正文",
                               "_want_upload": True, "_upload_count": 0}))
    r_nu = r_nu or {}
    probe_nu = PUB.parse_result(probe_nu) if probe_nu else {}
    check("标记为「需人工」而不是失败", r_nu.get("manual") is True, str(r_nu))
    check("不做无限重试（没有 retry）", not r_nu.get("retry"), str(r_nu))
    msg_nu = str(r_nu.get("message", ""))
    check("说明里告诉用户「选好图再点一次一键填充」",
          "上传" in msg_nu and "一键填充" in msg_nu, msg_nu)
    check("已经帮用户点开了上传入口（不用他自己找）",
          probe_nu.get("clicks") == 1, str(probe_nu))

    # ---------------- 3. 停在视频页：应该返回 retry，而不是报死
    print("\n--- 停在「上传视频」页 ---")
    res2, _ = run_on(FIXTURE_VIDEO, script)
    res2 = res2 or {}
    check("不报死，而是要求重试", bool(res2.get("retry")) is True, str(res2))
    check("重试原因说的是「正在切到上传图文」",
          "上传图文" in str(res2.get("message", "")), str(res2.get("message")))
    check("没把「填不上」当成终态失败", res2.get("ok") is False)

    # ---------------- 4. 发布队列：retry 会真的重试，超限才判失败
    print("\n--- 发布队列的重试 ---")

    class FakePage:
        """按预设序列依次返回结果，模拟「前几次页面没就绪」。"""

        def __init__(self, seq):
            self.seq = list(seq)
            self.calls = 0
            self.scripts = []

        def runJavaScript(self, script, cb):
            self.calls += 1
            self.scripts.append(script)
            cb(self.seq.pop(0) if self.seq else {"ok": True, "message": "完成"})

    def run_queue(seq, max_retry=8, upload_count=3):
        page = FakePage(seq)
        q = PUB.PublishQueue(lambda aid: page)
        q.RETRY_DELAY_MS = 20
        q.MAX_RETRY = max_retry
        out = {}
        done = {"v": False}   # 防残留定时器杀掉后续 exec（同 run_on）
        q.item_done.connect(lambda rid, ok, msg, meta: out.update(ok=ok, msg=msg, meta=meta))
        q.all_done.connect(lambda allok: (done.__setitem__("v", True), app.quit()))
        q.run([{"record_id": "r1", "platform_key": "xhs", "platform_name": "小红书",
                "account_id": "a1", "adapter": "xhs.js", "payload": {},
                "upload_count": upload_count}], mode="fill")
        QTimer.singleShot(10000, lambda: (not done["v"]) and app.quit())
        app.exec()
        done["v"] = True
        return out, page

    retry_res = {"ok": False, "message": "正在切到「上传图文」页…", "retry": True, "stage": "switch"}
    out, page = run_queue([retry_res, retry_res, {"ok": True, "message": "填充完成"}])
    check("遇到 retry 会重跑同一项，直到成功", out.get("ok") is True, str(out))
    check("确实重试了两次（共调用 3 次）", page.calls == 3, f"calls={page.calls}")

    # 关键：只在第一次尝试时把 _upload_count 交给脚本，重试时必须置 0，
    # 否则同一批图会被重复上传。
    def upload_counts(scripts):
        return [int(m.group(1)) for m in
                (__import__("re").search(r'"_upload_count":\s*(\d+)', s) for s in scripts)
                if m]

    check("第一次尝试带着 _upload_count", upload_counts(page.scripts)[:1] == [3],
          str(upload_counts(page.scripts)))
    check("重试时 _upload_count 归零（不会重复传图）",
          upload_counts(page.scripts)[1:] == [0, 0],
          str(upload_counts(page.scripts)))

    # v1.6·2：带文件的项（upload_count>0）重试预算放宽到 MAX_RETRY_UPLOAD
    #（约 60s）—— 几十张图传完之前不该被判死，不再按 max_retry 截
    out2, page2q = run_queue([retry_res] * 50, max_retry=3)
    calls2 = page2q.calls
    check("重试超上限后判为失败", out2.get("ok") is False)
    check("上传项预算放宽到 MAX_RETRY_UPLOAD",
          calls2 == PUB.PublishQueue.MAX_RETRY_UPLOAD + 1, f"calls={calls2}")
    check("上传项超时说明写清「已等约 N 秒 + 会自动继续填充」",
          "已等约" in str(out2.get("msg", ""))
          and "自动继续填充" in str(out2.get("msg", "")), str(out2.get("msg")))
    check("超时结果保留 stage（工作台靠它排自动续跑）",
          (out2.get("meta") or {}).get("stage") == "switch", str(out2.get("meta")))

    # 非上传项仍走普通 MAX_RETRY 预算，超时说明「已重试 N 次」（原行为不变）
    out3, page3q = run_queue([retry_res] * 50, max_retry=3, upload_count=0)
    check("非上传项仍按 max_retry 预算",
          page3q.calls == 4, f"calls={page3q.calls}")
    check("非上传项超时说明写清「已重试 N 次」",
          "已重试 3 次" in str(out3.get("msg", "")), str(out3.get("msg")))

    # ---------------- 5. 平台定义：发布页 URL 直接落到图文页
    print("\n--- 平台定义 ---")
    PF.reload()
    url = PF.publish_url_for("xhs", {})
    check("小红书发布页 URL 带 target=image", "target=image" in url, url)
    check("视频内容才用 target=video",
          "target=video" in PF.publish_url_for("xhs", {"video_path": "a.mp4"}))
    check("别的平台不受影响",
          "creator.douyin.com" in PF.publish_url_for("douyin", {}))

    # ---------------- 6. 配图目录解析
    print("\n--- 配图目录解析 ---")
    import tempfile
    d = tempfile.mkdtemp(prefix="df_img_")
    for n in ("01.png", "02.jpg", "note.txt"):
        open(os.path.join(d, n), "wb").close()
    imgs = PF.local_images("xhs", {"image_hint": f"已出图 2 张，目录：{d}"})
    check("从「目录：」标记后面抠出路径并列出图片", len(imgs) == 2, str(imgs))
    check("非图片文件被排除", all(i.endswith((".png", ".jpg")) for i in imgs))
    check("目录不存在时返回空，不瞎猜",
          PF.local_images("xhs", {"image_hint": "已出图 0 张，目录：Z:/nope"}) == [])
    check("没有这个字段的平台返回空", PF.local_images("douyin", {"image_hint": d}) == [])

    print()
    if fails:
        print(f"=== 失败 {len(fails)} 项 ===")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("=== 通过 全部 ===")


if __name__ == "__main__":
    main()
