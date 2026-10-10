"""内容流水线测试：不打网络、不调真模型，把「抓取 → 生成 → 出图 / 出视频」跑通。

做法：把 Ctx.llm 换成一个返回固定 JSON 的假模型，其余（PIL 出图、ffmpeg 编码、
edge-tts 之外的音频处理）全部走真实代码路径 —— 这样能验证：
  · 模型返回的畸形大纲不会让流程崩掉
  · 出图真的落了文件、尺寸正确
  · 视频真的编码成功、能被 ffmpeg 读出来
  · 中途取消能停下来

用法：
    python tests/test_pipelines.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

fails = []


def check(name, cond, detail=""):
    print(f"  {'[OK]  ' if cond else '[FAIL]'} {name}" + (f"  → {detail}" if detail else ""),
          flush=True)
    if not cond:
        fails.append(name)


# ================================================================ 正文解析回归
# 公众号正文里全是自闭合的 <img ... />。老解析器用「进入容器/闭合容器时的标签深度」
# 判断正文边界，而 HTMLParser 对自闭合标签会依次调 starttag + endtag ——
# starttag 对 img 提前 return（不加深度），endtag 却减了深度，
# 于是深度被扣到 0、正文刚开始就被判定结束，整篇只剩十几个换行。
# 这个 fixture 必须保留自闭合 <img />，否则测不出这个 bug。
_WECHAT_FIXTURE = """<!DOCTYPE html><html><head>
<meta property="og:title" content="2027广东选调生笔试提前研判">
</head><body>
<div class="rich_media">
  <h1 id="activity-name">2027广东选调生笔试提前研判</h1>
  <div id="js_name">粉笔广东</div>
  <div class="rich_media_content js_underline_content
              autoTypeSetting24psection
     "
     id="js_content" style="visibility: hidden; opacity: 0; ">
    <section><p>第一个要点：近年广东选调生的笔试时间整体前移。</p>
    <img class="rich_pages wxw-img" data-src="https://mmbiz.qpic.cn/a/0?wx_fmt=png" />
    <p>第二个要点：行测与申论的题量分布趋于稳定。</p>
    <img data-src="https://mmbiz.qpic.cn/b/0?wx_fmt=png" />
    <p>第三个要点：报名人数连续三年上升，竞争比从 12:1 涨到 31:1。</p>
    <img data-src="https://mmbiz.qpic.cn/c/0?wx_fmt=png" />
    <p>第四个要点：面试环节更看重结构化表达，笔试权重略有下调。</p>
    <p>第五个要点：备考周期建议拉到 5 个月以上，前期以打基础为主。</p>
    <p>第六个要点：真题至少刷三轮，第三轮只做错题和难题。</p>
    <p>第七个要点：考前两周要完整模拟三次，严格卡时间。</p>
    <p>第八个要点：把错题按模块归档，考前只看错题本。</p>
    </section>
  </div>
  <div class="rich_media_tool">底部工具栏垃圾文字，不该被抓进来。</div>
  <p>这段文字在正文容器之外，不应该被抓进来。</p>
</div>
</body></html>"""


def test_article_parser():
    print("\n=== 公众号正文解析（回归）===", flush=True)
    from pipelines import gzh_to_xhs as G

    frag = G._extract_content_html(_WECHAT_FIXTURE)
    check("能从带换行的 class 属性里定位正文容器", bool(frag) and "第一个要点" in frag)

    p = G._ContentParser()
    p.feed(frag)
    text = p.text()

    check("自闭合 <img /> 不会导致正文丢失", "第七个要点" in text,
          f"抓到 {len(text)} 字")
    check("正文首句完整", "第一个要点：近年广东选调生的笔试时间整体前移。" in text)
    check("数字未被截断", "31:1" in text)
    check("容器外的文字未被误抓", "不应该被抓进来" not in text
          and "底部工具栏垃圾文字" not in text)
    check("正文末句完整（未被容器边界截断）", "第八个要点" in text)
    check("收集到 3 张配图", len(p.images) == 3, str(p.images))
    check("配图地址去重且保留顺序",
          p.images[0].endswith("/a/0?wx_fmt=png") and p.images[-1].endswith("/c/0?wx_fmt=png"))

    # 错误页要给出可照做的原因，而不是笼统的「没抓到正文」
    dead = "<html><head><title></title></head><body>参数错误</body></html>"
    check("参数错误页能识别", "参数错误" in G._diagnose(dead))
    check("参数错误页的提示含补救动作", "复制链接" in G._diagnose(dead)
          or "手动粘贴正文" in G._diagnose(dead))
    check("验证页能识别", "环境异常" in G._diagnose("<html>环境异常</html>"))
    check("删除页能识别", "已被作者删除" in G._diagnose("<html>该内容已被发布者删除</html>"))


# ================================================================ 假模型
GZH_OUTLINE = {
    "title": "行测提速就靠这三个动作",
    "body": "先说结论：行测提分的关键不在刷题量，而在做题顺序。\n\n"
            "先做常识和言语进入状态，数量关系放最后，资料分析留足 25 分钟。",
    "topics": "省考 行测 公考备考 上岸经验 备考规划",
    "cover": "三个动作提速度",
    "image_hint": "深蓝底 + 白字，数据感强",
    "pages": [
        {"type": "cover", "tag": "备考干货", "title_small": "省考行测",
         "title_big": ["提速三个动作", "一次讲清"], "sub1": "顺序对了，速度自然起来",
         "sub2": "别再用刷题量掩盖方法问题",
         "stats": [["3", "个动作", "做题顺序"], ["25", "分钟", "资料分析"],
                   ["1", "条主线", "先易后难"]]},
        {"type": "rows", "tag": "模块 02", "title": "三个关键动作", "sub": "按顺序做",
         "banner": "顺序错了，刷再多题也没用",
         "rows": [["先扫题干", "20 秒", "判断题型再动笔", False],
                  ["再定顺序", "分值", "把时间花在能拿分的题上", True],
                  ["最后回头", "5 分钟", "检查计算和涂卡", False]]},
        {"type": "table", "tag": "数据", "title": "各模块时间分配", "sub": "参考值",
         "banner": "单位：分钟", "headers": ["模块", "建议用时", "占比"],
         "rows": [["常识", "8", "9%", "none"], ["言语", "35", "39%", "none"],
                  ["数量", "10", "11%", "hot"], ["资料", "25", "28%", "none"],
                  ["合计", "90", "100%", "total"]]},
        {"type": "bullets", "tag": "方法论", "title": "练的时候注意", "sub": "三件事",
         "banner": "练三套就能感觉到差别",
         "items": [["先扫题干", "20 秒内判断题型，别一上来就列方程"],
                   ["再定顺序", "按分值和把握度排，先拿能拿的分"],
                   ["最后回头", "留 5 分钟检查计算和涂卡"]]},
        {"type": "quote", "tag": "一句话", "title": "别急着刷题",
         "quote": "先把卷子结构搞清楚，比多刷一百道题有用", "source": "教研组"},
        {"type": "text", "tag": "拆解", "title": "为什么先扫题干", "sub": "题干里有信号",
         "paras": ["题干里往往藏着题型信号词，先认出题型再动笔，能省掉大量试错时间。",
                   "很多人卡住不是不会算，而是花了三分钟才反应过来这题考什么。"]},
        {"type": "unknown_type", "tag": "兜底", "title": "未知版式",
         "rows": [["这一页类型模型编的", "兜底", "会按列表页渲染", True]]},
        {"type": "end", "title": "就这样练", "lines": ["先看结构", "再定顺序", "最后回头"],
         "cta": "收藏起来慢慢看"},
    ],
}

VIDEO_SCRIPT = {
    "title": "行测提速的三个动作",
    "scenes": [
        {"type": "cover", "title": "行测提速三个动作", "sub": "顺序对了，速度自然起来",
         "tag": "备考干货", "narration": "行测提分的关键不在刷题量，而在做题顺序。"},
        {"type": "points", "title": "三个关键动作",
         "items": ["先扫题干定题型", "按分值排顺序", "留五分钟回头查"],
         "narration": "第一先扫题干，第二按分值排顺序，第三留五分钟回头检查。"},
        {"type": "stats", "title": "时间怎么分",
         "stats": [["90", "分钟", "整套行测"], ["25", "分钟", "资料分析"]],
         "narration": "资料分析必须留足二十五分钟。"},
        {"type": "text", "title": "为什么要先扫题干", "text": "题干里藏着题型信号词，先认出题型再动笔，能省掉大量试错时间。",
         "narration": "很多人卡住不是不会算，是花了三分钟才反应过来考什么。"},
        {"type": "end", "title": "就这样练", "cta": "收藏起来慢慢看",
         "narration": "按这个顺序练三套，你会明显感觉到差别。"},
    ],
}


class FakeCtx:
    """替换 Ctx：llm 返回预设 JSON，其余（日志 / 进度 / 产物）与真实一致。"""

    def __init__(self, out_dir, payload):
        self.out_dir = out_dir
        self.payload = payload
        self.artifacts = []
        self.logs = []
        self.progress_seen = []
        os.makedirs(out_dir, exist_ok=True)

    def log(self, m):
        self.logs.append(str(m))

    def progress(self, p, m=""):
        self.progress_seen.append((p, m))

    def stopped(self):
        return False

    def check(self):
        pass

    def add(self, path):
        if path and path not in self.artifacts:
            self.artifacts.append(path)
        return path

    def llm(self, system, user, **kw):
        return "```json\n" + json.dumps(self.payload, ensure_ascii=False) + "\n```"

    def llm_json(self, system, user, **kw):
        return json.loads(json.dumps(self.payload))


def main():
    print("\n=== 内容流水线测试 ===\n")
    import config
    import pipelines as PL
    from pipelines import kit_draw as KD

    check("流水线注册表完整", set(PL.keys()) >= {"gzh_to_xhs", "xhs_video"},
          "、".join(PL.keys()))
    check("中文字体可用", KD.has_cjk_font(), "找不到会退回默认字体（中文会变方块）")

    tmp = tempfile.mkdtemp(prefix="df_pipe_test_")
    # 把产出目录指到临时目录，别污染用户数据目录
    old_out = config.OUTPUT_DIR
    config.OUTPUT_DIR = tmp

    try:
        # ============================================ 公众号转图文
        print("\n--- 公众号链接转小红书图文 ---")
        pipe = PL.get("gzh_to_xhs")
        ctx = FakeCtx(os.path.join(tmp, "gzh"), GZH_OUTLINE)
        src = (
            "导语：行测提分的关键不在刷题量，而在做题顺序。\n"
            "先做常识和言语进入状态，把数量关系放到最后，资料分析留足二十五分钟。\n"
            "很多人卡住不是不会算，而是花了三分钟才反应过来这题考什么。\n"
            "按这个顺序练三套，你会明显感觉到差别。\n"
        )
        res = pipe.run({"url": "", "text": src * 4, "pages": "8", "extra": ""}, ctx)
        arts = [p for p in ctx.artifacts if p.endswith(".png")]
        check("出图数量与大纲页数一致", len(arts) == len(GZH_OUTLINE["pages"]),
              f"{len(arts)} 张 / {len(GZH_OUTLINE['pages'])} 页")
        check("全部图片文件真实存在", all(os.path.exists(p) for p in arts))
        from PIL import Image
        sizes = {Image.open(p).size for p in arts}
        check("图片尺寸统一为 1080x1440", sizes == {(1080, 1440)}, str(sizes))
        check("未知版式走列表页兜底而不是崩掉",
              any("未知版式" in os.path.basename(p) for p in arts))
        check("返回内容带上了文案字段",
              bool(res.get("title")) and bool(res.get("body")) and bool(res.get("topics")))
        check("image_hint 里写清了出图目录", str(res.get("image_hint", "")).find("已出图") >= 0)
        check("进度回调有推进", len(ctx.progress_seen) >= 3,
              f"{len(ctx.progress_seen)} 次")
        check("进度值在 0~1 之间",
              all(0.0 <= p <= 1.0 for p, _ in ctx.progress_seen))

        # ============================================ 文案转短视频
        print("\n--- 文案转竖屏短视频 ---")
        vpipe = PL.get("xhs_video")
        vctx = FakeCtx(os.path.join(tmp, "video"), VIDEO_SCRIPT)
        vres = vpipe.run({
            "title": "行测提速的三个动作",
            "body": "行测提分的关键不在刷题量，而在做题顺序。先扫题干定题型，"
                    "再按分值排顺序，最后留五分钟回头检查。资料分析必须留足二十五分钟。",
            "scenes": "5", "voice": "不要口播", "bgm": "不要", "extra": "",
        }, vctx)
        mp4 = [p for p in vctx.artifacts if p.endswith(".mp4")]
        check("产出 mp4", len(mp4) == 1 and os.path.getsize(mp4[0]) > 20000,
              f"{os.path.getsize(mp4[0]) if mp4 else 0} B")
        from pipelines.xhs_video import audio_duration, ffmpeg_exe
        dur = audio_duration(mp4[0]) if mp4 else 0
        check("视频时长合理（>3 秒）", dur > 3, f"{dur:.1f} 秒")
        probe = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", mp4[0]],
                               capture_output=True)
        meta = probe.stderr.decode("utf-8", "replace")
        check("视频流是 H.264 且分辨率 1080x1920",
              "h264" in meta and "1080x1920" in meta,
              next((l.strip() for l in meta.splitlines() if "Stream #" in l), ""))
        check("分镜提示写回了卡片", "视频文件" in str(vres.get("shot_hint", "")))
        check("口播关闭时文案仍完整回填", len(str(vres.get("body", ""))) > 20)

        # ============================================ 口播（要联网，失败不算错）
        print("\n--- AI 口播（edge-tts，需要联网）---")
        from pipelines.xhs_video import audio_duration, concat_audio, mix_bgm, synth
        tts_dir = os.path.join(tmp, "tts")
        os.makedirs(tts_dir, exist_ok=True)
        a = os.path.join(tts_dir, "a.mp3")
        b = os.path.join(tts_dir, "b.mp3")
        ok = synth("行测提分的关键不在刷题量，而在做题顺序。",
                   "zh-CN-XiaoxiaoNeural", a) and \
            synth("资料分析必须留足二十五分钟。", "zh-CN-XiaoxiaoNeural", b)
        if not ok:
            print("  [SKIP] 口播合成不可用（大概率是没联网），跳过这一组检查")
        else:
            da = audio_duration(a)
            check("口播单段时长可读", da > 1.0, f"{da:.1f} 秒")
            merged = os.path.join(tts_dir, "merged.m4a")
            check("多段口播能拼接", concat_audio([a, b], merged)
                  and audio_duration(merged) > da,
                  f"合并后 {audio_duration(merged):.1f} 秒")
            mixed = mix_bgm(merged, os.path.join(tts_dir, "mixed.m4a"))
            check("背景和声能混进音轨", os.path.exists(mixed)
                  and audio_duration(mixed) > 1.0)

        # ============================================ 缺参数
        print("\n--- 参数校验 ---")
        try:
            vpipe.run({"body": ""}, FakeCtx(os.path.join(tmp, "x"), {}))
            check("空文案应该被拒绝", False)
        except ValueError as e:
            check("空文案被拒绝并给出原因", "文案" in str(e), str(e))

        # ============================================ 组合流水线
        # 「输入链接，同时出图文和视频」—— 用户明确要的那条。
        # 关键不变量：中间那份文案由抓取产生，**不能让用户填第二遍**，
        # 否则这条链就不是「一次输入」了。
        print("\n--- 组合流水线：链接 → 图文 + 视频 ---")
        import pipelines as _P
        both = _P.get("gzh_to_both")
        check("组合流水线已注册", both is not None, str(_P.keys()))
        if both is not None:
            keys = [i.key for i in both.inputs()]
            check("不让用户填 title / body（由抓取那步产生）",
                  "title" not in keys and "body" not in keys, str(keys))
            check("图文那半边的输入都在", "url" in keys and "pages" in keys, str(keys))
            check("视频那半边的输入都在", "scenes" in keys and "voice" in keys, str(keys))
            check("补充要求只有一个（两边共用）", keys.count("extra") == 1, str(keys))
            check("没有重复的输入项", len(keys) == len(set(keys)), str(keys))
            check("声明了三样产出", len(both.output_labels()) == 3,
                  str(both.output_labels()))

        # ============================================ 取消
        print("\n--- 中途取消 ---")
        cctx = FakeCtx(os.path.join(tmp, "cancel"), GZH_OUTLINE)

        class Stopping(FakeCtx):
            def stopped(self):
                return len(self.progress_seen) > 2

            def check(self):
                if self.stopped():
                    raise InterruptedError("已停止")

        try:
            pipe.run({"url": "", "text": src * 4, "pages": "8"}, Stopping(
                os.path.join(tmp, "cancel"), GZH_OUTLINE))
            check("取消时应该抛 InterruptedError", False)
        except InterruptedError:
            check("中途取消能立刻停下", True)

    finally:
        config.OUTPUT_DIR = old_out
        shutil.rmtree(tmp, ignore_errors=True)

    test_article_parser()

    print(f"\n=== {'通过 全部' if not fails else f'失败 {len(fails)} 项'} ===")
    for f in fails:
        print(f"  - {f}")
    print()
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
