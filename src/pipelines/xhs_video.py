# -*- coding: utf-8 -*-
"""Pipeline：文案 → 9:16 竖屏短视频（可选 AI 口播 + 字幕 + 背景音乐）。

流程
  1. 让模型把文案拆成分镜脚本（封面 / 要点 / 数字 / 段落 / 收尾），并给每镜一句口播
  2. 口播：edge-tts 逐镜合成语音 → 用真实语音时长决定每镜停留时间 → 拼成整轨
  3. 画面：PIL 逐帧渲染（元素错峰入场 + 打字机），RGB 裸帧直接喂 ffmpeg 管道
  4. 合成：H.264 + AAC，若有背景音乐则做侧链式压低混音
  5. 输出 mp4，路径写进素材卡片

依赖：Pillow、edge-tts（口播）、ffmpeg（用 imageio-ffmpeg 自带的二进制，免安装）
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import subprocess
import tempfile
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from .base import Ctx, Input, Pipeline, register
from . import kit_draw as K

W, H = 1080, 1920
FPS = 30
P = K.Palette

VOICES = {
    "女声 · 亲和": "zh-CN-XiaoxiaoNeural",
    "女声 · 活泼": "zh-CN-XiaoyiNeural",
    "男声 · 沉稳": "zh-CN-YunxiNeural",
    "男声 · 播报": "zh-CN-YunyangNeural",
    "不要口播": "",
}


# ================================================================ ffmpeg
def ffmpeg_exe() -> str:
    """找一个能用的 ffmpeg。

    顺序：imageio-ffmpeg 自带的二进制 → 冻结包里的同一路径 → PATH 上的 ffmpeg。
    打包后 imageio_ffmpeg 的定位逻辑有时找不到解包目录，所以这里再兜一层。
    """
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    try:
        import sys
        base = getattr(sys, "_MEIPASS", "")
        if base:
            d = os.path.join(base, "imageio_ffmpeg", "binaries")
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if f.lower().startswith("ffmpeg"):
                        return os.path.join(d, f)
    except Exception:
        pass
    return "ffmpeg"


# Windows 下 GUI 进程调控制台子程序（ffmpeg）每次都会闪一个黑框，
# 统一压掉；CREATE_NO_WINDOW 只有 Windows 的 subprocess 才有这个属性。
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _run(args: List[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=_NO_WINDOW, **kw)


def audio_duration(path: str) -> float:
    """用 ffmpeg 读一个音频文件的时长（秒）。"""
    if not path or not os.path.exists(path):
        return 0.0
    r = _run([ffmpeg_exe(), "-hide_banner", "-i", path, "-f", "null", "-"])
    m = re.search(rb"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or b"")
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ================================================================ 口播
async def _tts_save(text: str, voice: str, path: str) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice).save(path)


def synth(text: str, voice: str, path: str) -> bool:
    """合成一段口播到 path，成功返回 True。"""
    text = (text or "").strip()
    if not text or not voice:
        return False
    try:
        asyncio.run(_tts_save(text, voice, path))
        return os.path.getsize(path) > 1024
    except Exception:
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
            asyncio.run(_tts_save(text, voice, path))
            return os.path.getsize(path) > 1024
        except Exception:
            return False


def concat_audio(paths: List[str], out: str, gap: float = 0.28) -> bool:
    """把多段语音按顺序拼成一轨，段间留一点气口。"""
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        return False
    if len(paths) == 1:
        import shutil
        shutil.copy(paths[0], out)
        return True
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        for p in paths:
            f.write("file '%s'\n" % p.replace("\\", "/").replace("'", "'\\''"))
        lst = f.name
    sil = os.path.join(os.path.dirname(out), "_gap.m4a")
    try:
        _run([ffmpeg_exe(), "-y", "-f", "lavfi", "-i",
              f"anullsrc=r=24000:cl=mono", "-t", f"{gap}", sil])
        with open(lst, "a", encoding="utf-8") as f:
            for i in range(len(paths) - 1):
                f.write("file '%s'\n" % sil.replace("\\", "/"))
        r = _run([ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", lst,
                  "-c:a", "aac", "-b:a", "160k", out])
        return r.returncode == 0 and os.path.exists(out)
    finally:
        for p in (lst, sil):
            try:
                os.remove(p)
            except Exception:
                pass


# ================================================================ 分镜脚本
SYSTEM = (
    "你是短视频分镜编剧，擅长把一篇图文文案拆成 5-8 个竖屏镜头，每镜一句口语化口播。"
    "只输出 JSON，不要解释。不使用「包过」「保过」「最」「第一」「100%」等违规承诺词。"
)

PROMPT = """把下面的文案改写成一条竖屏短视频（9:16）的分镜脚本。

【标题】{title}
【文案】
{body}
【补充要求】{extra}

输出一个 JSON 对象：
{{
  "title": "视频标题，≤16 字",
  "scenes": [
    {{"type":"cover","title":"主标题≤14字","sub":"副标题≤20字","tag":"角标≤8字",
      "narration":"这一镜的口播，1-2 句，口语化，≤45 字"}},
    {{"type":"points","title":"小标题≤12字","items":["要点1≤16字","要点2≤16字","要点3≤16字"],
      "narration":"…"}},
    {{"type":"stats","title":"小标题≤12字","stats":[["数字","单位","说明≤8字"]],"narration":"…"}},
    {{"type":"text","title":"小标题≤12字","text":"一段话≤80字","narration":"…"}},
    {{"type":"end","title":"收尾≤10字","cta":"行动号召≤14字","narration":"…"}}
  ]
}}

硬性要求：
- scenes 数量 {n} 个：第 1 个必须是 cover，最后 1 个必须是 end，中间至少 1 个 points 或 stats。
- 每个 scene 的 narration 必须能独立听懂，前后连贯，合起来是一段完整的话。
- 所有数字和结论必须来自原文，不许编造。
- 只输出 JSON。
"""


def _clip(v: Any, n: int) -> str:
    return str(v if v is not None else "").strip()[:n]


def _lst(v: Any) -> List[Any]:
    return list(v) if isinstance(v, (list, tuple)) else []


def normalize_scenes(raw: Any, want: int) -> List[dict]:
    out = [s for s in _lst(raw) if isinstance(s, dict)]
    if not out:
        return []
    if str(out[0].get("type", "")).lower() != "cover":
        out.insert(0, {"type": "cover", "title": "看这一条就够了", "sub": "",
                       "tag": "", "narration": ""})
    if str(out[-1].get("type", "")).lower() != "end":
        out.append({"type": "end", "title": "就到这里", "cta": "收藏起来慢慢看",
                    "narration": ""})
    for s in out:
        t = str(s.get("type", "")).lower()
        if t not in ("cover", "points", "stats", "text", "end"):
            s["type"] = "text"
    return out[:max(3, want)]


# ================================================================ 画面
# 版心：上下各留出平台 UI 会盖住的区域，内容整体在 300~1560 之间垂直居中
SAFE_TOP, SAFE_BOTTOM = 300, 1560
CX = 96                      # 左右边距
CW = W - CX * 2              # 可用宽度


# ---- 画面主题 --------------------------------------------------------------
# navy  = 深蓝渐变（默认，自用模板的既有风格）
# cream = 暖橙奶油杂志风（分享版「一题多发」用，与 gzh_to_xhs_magazine 同一色系）
VIDEO_THEMES: Dict[str, Dict[str, tuple]] = {
    "navy": dict(
        bg_top=(13, 32, 58), bg_add=(20, 36, 62),
        glow=((222, 84, 44), (60, 126, 208)), glow_alpha=0.32, glow_base=(0, 0, 0),
        grain=(26, 26, 26), grain_alpha=0.20,
        title=P.WHITE, sub=(214, 226, 244, 255), muted=(196, 210, 232, 255),
        body=(226, 234, 246, 255), tag=(250, 214, 140, 255),
        bar=P.ORANGE, accent=(250, 214, 140, 255),
        card_fill=(255, 255, 255, 30), card_line=(255, 255, 255, 46),
        num_text=(255, 255, 255, 255), on_accent=(19, 46, 82, 255),
    ),
    "cream": dict(
        bg_top=(252, 246, 237), bg_add=(-9, -16, -26),
        glow=((232, 98, 43), (201, 138, 46)), glow_alpha=0.22,
        glow_base=(250, 243, 233),          # 亮底不能往黑里混，会发脏
        grain=(72, 54, 38), grain_alpha=0.10,
        title=(42, 33, 24, 255), sub=(107, 74, 42, 255), muted=(138, 123, 105, 255),
        body=(74, 62, 48, 255), tag=(201, 138, 46, 255),
        bar=(232, 98, 43, 255), accent=(201, 138, 46, 255),
        card_fill=(255, 255, 255, 200), card_line=(72, 54, 38, 60),
        num_text=(255, 255, 255, 255), on_accent=(250, 243, 233, 255),
    ),
}


def _th(key: str) -> Dict[str, tuple]:
    return VIDEO_THEMES.get(key) or VIDEO_THEMES["navy"]


def _rgba(c, a):
    """给主题色临时换一个 alpha（主题色一律存满 alpha 的 RGBA）。"""
    return (c[0], c[1], c[2], a)


def _bg(scene_i: int, th: Optional[Dict[str, tuple]] = None) -> Image.Image:
    """每镜一张背景：主题色渐变 + 两团柔光，按镜次微调光斑位置。"""
    from PIL import ImageFilter
    t_ = th or VIDEO_THEMES["navy"]
    img = Image.new("RGB", (W, H), t_["bg_top"])
    d = ImageDraw.Draw(img)
    shift = (scene_i * 53) % 120
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)],
               fill=tuple(max(0, min(255, int(t_["bg_top"][c] + t_["bg_add"][c] * t)))
                          for c in range(3)))
    g1, g2 = t_["glow"]
    for cx, cy, rad, col in ((W - 200, 340 + shift, 520, g1),
                             (150, H - 400 - shift, 580, g2)):
        # 柔光层必须以「本底色」为底 —— 往黑里混会把亮色主题搞得灰暗发脏
        layer = Image.new("RGB", (W, H), t_["glow_base"])
        ImageDraw.Draw(layer).ellipse(
            (cx - rad, cy - rad, cx + rad, cy + rad), fill=col)
        img = Image.blend(img, layer.filter(ImageFilter.GaussianBlur(190)),
                          t_["glow_alpha"])
    ov = Image.new("RGB", (W, H), (0, 0, 0))
    od = ImageDraw.Draw(ov)
    for yy in range(80, H, 52):
        for xx in range(60, W, 52):
            od.ellipse((xx, yy, xx + 3, yy + 3), fill=t_["grain"])
    return Image.blend(img, ov, t_["grain_alpha"])


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _compose(bg: Image.Image, ov: Image.Image) -> Image.Image:
    """把带透明度的绘制层合到背景上。半透明元素必须走这条路，否则 alpha 会被吃掉。"""
    return Image.alpha_composite(bg.convert("RGBA"), ov).convert("RGB")


# ---- 绘制小工具（都在 RGBA 层上画） ----
def _lines(text: str, f, maxw: int, n: int) -> List[str]:
    return K.fit_lines(text, f, maxw, n)


def _block_h(lines: Sequence[str], f, lh: int) -> int:
    return len(lines) * lh


def _draw_title(d, x: int, y: int, text: str, f, maxw: int, n: int = 2,
                fill=None, th=None) -> int:
    ls = _lines(text, f, maxw, n)
    t_ = th or VIDEO_THEMES["navy"]
    for i, ln in enumerate(ls):
        d.text((x, y + i * int(f.size * 1.22)), ln, font=f,
               fill=fill or t_["title"])
    return int(len(ls) * f.size * 1.22)


def _draw_para(d, x: int, y: int, text: str, f, maxw: int, n: int,
               fill=None, lh: Optional[int] = None, th=None) -> int:
    lh = lh or int(f.size * 1.5)
    t_ = th or VIDEO_THEMES["navy"]
    for ln in _lines(text, f, maxw, n):
        d.text((x, y), ln, font=f, fill=fill or t_["body"])
        y += lh
    return y


def _draw_scene(bg: Image.Image, scene: dict, p: float,
                th: Optional[Dict[str, tuple]] = None) -> Image.Image:
    """p ∈ [0,1] 是这一镜的播放进度。返回 RGB 帧。"""
    t_ = th or VIDEO_THEMES["navy"]
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    t = str(scene.get("type", "text")).lower()

    if t == "cover":
        f_tag, f_title, f_sub = K.font(36, True), K.font(100, True), K.font(42, False)
        title = _lines(_clip(scene.get("title"), 16), f_title, CW, 2)
        sub = _lines(_clip(scene.get("sub"), 34), f_sub, CW, 2)
        total = 60 + len(title) * 122 + 40 + len(sub) * 66 + 60
        y = int(SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP - total) / 2)

        _appear(d, 0.02, p, lambda: d.text(
            (CX, y), _clip(scene.get("tag"), 10), font=f_tag,
            fill=t_["tag"]))
        _appear(d, 0.12, p, lambda: _draw_title(d, CX, y + 60, "", f_title, CW))
        for i, ln in enumerate(title):
            st = 0.12 + i * 0.1
            _appear(d, st, p, lambda i=i, ln=ln: d.text(
                (CX, y + 60 + i * 122), ln, font=f_title, fill=t_["title"]))
        yb = y + 60 + len(title) * 122 + 30
        _appear(d, 0.34, p, lambda: d.rounded_rectangle(
            (CX, yb, CX + 200, yb + 14), radius=7, fill=t_["bar"]))
        for i, ln in enumerate(sub):
            _appear(d, 0.42 + i * 0.08, p, lambda i=i, ln=ln: d.text(
                (CX, yb + 50 + i * 66), ln, font=f_sub, fill=t_["sub"]))

    elif t == "points":
        f_title, f_item = K.font(64, True), K.font(44, True)
        items = [_clip(x, 22) for x in _lst(scene.get("items"))[:4]]
        rh, gap = 168, 32
        total = 120 + len(items) * (rh + gap)
        y0 = int(SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP - total) / 2)
        _appear(d, 0.0, p, lambda: d.text(
            (CX, y0), _clip(scene.get("title"), 14), font=f_title,
            fill=t_["title"]))
        for i, it in enumerate(items):
            st = 0.18 + i * 0.15
            if p < st:
                continue
            a = _ease((p - st) / 0.28)
            off = int((1 - a) * 56)
            y = y0 + 120 + i * (rh + gap) + off
            d.rounded_rectangle((CX, y, CX + CW, y + rh), radius=30,
                                fill=t_["card_fill"],
                                outline=t_["card_line"], width=2)
            d.ellipse((CX + 34, y + rh / 2 - 34, CX + 102, y + rh / 2 + 34),
                      fill=t_["bar"])
            d.text((CX + 68, y + rh / 2), str(i + 1), font=K.font(38, True),
                   fill=t_["num_text"], anchor="mm")
            _draw_para(d, CX + 132, y + rh / 2 - 30, it, f_item, CW - 180, 2,
                       fill=t_["body"], lh=62, th=t_)

    elif t == "stats":
        f_title = K.font(64, True)
        stats = [s for s in _lst(scene.get("stats"))[:3] if _lst(s)]
        total = 120 + len(stats) * 300
        y0 = int(SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP - total) / 2)
        _appear(d, 0.0, p, lambda: d.text(
            (CX, y0), _clip(scene.get("title"), 14), font=f_title,
            fill=t_["title"]))
        for i, s in enumerate(stats):
            st = 0.15 + i * 0.18
            if p < st:
                continue
            a = _ease((p - st) / 0.3)
            y = y0 + 130 + i * 300
            num = _clip(s[0], 8)
            f_num = K.font(124, True)
            d.text((CX, y + int((1 - a) * 40)), num, font=f_num,
                   fill=_rgba(t_["title"], int(255 * a)))
            d.text((CX + f_num.getlength(num) + 18, y + 74),
                   _clip(s[1], 4) if len(s) > 1 else "", font=K.font(42, True),
                   fill=_rgba(t_["accent"], int(255 * a)))
            if len(s) > 2:
                _draw_para(d, CX, y + 170, _clip(s[2], 14), K.font(38, False),
                           CW, 1, fill=_rgba(t_["muted"], int(255 * a)), th=t_)

    elif t == "end":
        f_title, f_cta = K.font(88, True), K.font(44, True)
        cta = _clip(scene.get("cta"), 16)
        title = _lines(_clip(scene.get("title"), 12), f_title, CW, 2)
        total = len(title) * 108 + 120 + 110
        y = int(SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP - total) / 2)
        for i, ln in enumerate(title):
            _appear(d, 0.05 + i * 0.1, p, lambda i=i, ln=ln: d.text(
                (CX, y + i * 108), ln, font=f_title, fill=t_["title"]))
        yb = y + len(title) * 108 + 30
        _appear(d, 0.3, p, lambda: d.rounded_rectangle(
            (CX, yb, CX + 200, yb + 14), radius=7, fill=t_["bar"]))
        pw = f_cta.getlength(cta) + 88
        _appear(d, 0.42, p, lambda: d.rounded_rectangle(
            (CX, yb + 80, CX + pw, yb + 180), radius=50, fill=t_["accent"]))
        _appear(d, 0.46, p, lambda: d.text(
            (CX + 44, yb + 130), cta, font=f_cta, fill=t_["on_accent"],
            anchor="lm"))

    else:                                            # text
        f_title, f_body = K.font(64, True), K.font(44, False)
        full = _clip(scene.get("text"), 110)
        all_lines = _lines(full, f_body, CW, 6)
        total = 120 + len(all_lines) * 66
        y0 = int(SAFE_TOP + (SAFE_BOTTOM - SAFE_TOP - total) / 2)
        _appear(d, 0.0, p, lambda: d.text(
            (CX, y0), _clip(scene.get("title"), 14), font=f_title,
            fill=t_["title"]))
        n = int(len(full) * _ease((p - 0.18) / 0.6)) if p > 0.18 else 0
        if n:
            _draw_para(d, CX, y0 + 130, full[:n], f_body, CW, 6, th=t_)

    return _compose(bg, ov)


def _appear(d, start: float, p: float, fn) -> None:
    if p >= start:
        fn()


def frames_of(scene: dict, bg: Image.Image, dur: float,
              th: Optional[Dict[str, tuple]] = None) -> Iterator[bytes]:
    """把一镜渲染成若干 RGB 裸帧。"""
    total = max(1, int(round(dur * FPS)))
    for i in range(total):
        yield _draw_scene(bg, scene, i / max(1, total - 1), th).tobytes()


# ================================================================ 编码
def encode(frames: Iterator[bytes], out_path: str, audio: str = "") -> bool:
    # ffmpeg 不会自己建目录，父目录不存在会直接报 No such file or directory
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    ff = ffmpeg_exe()
    cmd = [ff, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-"]
    if audio and os.path.exists(audio):
        cmd += ["-i", audio]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio and os.path.exists(audio):
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [out_path]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW)
    try:
        for buf in frames:
            proc.stdin.write(buf)
    except Exception:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
    err = proc.stderr.read() if proc.stderr else b""
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 编码失败：" + err.decode("utf-8", "replace")[-400:])
    return os.path.exists(out_path)


def mix_bgm(voice: str, out_path: str) -> str:
    """给口播垫一段很轻的正弦和声当背景，避免用有版权的音乐。"""
    ff = ffmpeg_exe()
    r = _run([ff, "-y", "-loglevel", "error",
              "-i", voice,
              "-f", "lavfi", "-i", "sine=frequency=196:duration=600,volume=0.05",
              "-filter_complex",
              "[1:a]lowpass=f=400,volume=0.16[b];[0:a][b]amix=inputs=2:duration=first:"
              "dropout_transition=0[a]",
              "-map", "[a]", "-c:a", "aac", "-b:a", "160k", out_path])
    if r.returncode == 0 and os.path.exists(out_path):
        return out_path
    return voice


# ================================================================ Pipeline
@register
class XhsVideo(Pipeline):
    key = "xhs_video"
    name = "文案转竖屏短视频"
    desc = "把文案拆成分镜，逐帧渲染成 9:16 短视频，可加 AI 口播与字幕、背景音乐"
    note = ("耗时约为成片时长的 4 倍（实测 21 秒的片子约 90 秒）。"
            "开启口播需要联网调用 edge-tts；渲染期间可以点「停止」中断。")
    platform = "xhs"
    content_type = "视频"
    icon = "play"
    fields = ["title", "body", "shot_hint", "topics", "cover"]
    outputs = ["分镜脚本", "9:16 竖屏短视频（mp4）"]

    def inputs(self) -> List[Input]:
        return [
            Input("title", "视频标题", "text", required=False,
                  placeholder="例如：省考行测数量关系怎么提速"),
            Input("body", "文案 / 脚本", "textarea", required=True, rows=8,
                  placeholder="把要讲的文案整段贴进来；也可以只写几条要点，模型会扩成口播稿"),
            Input("scenes", "分镜数量", "choice", default="6",
                  choices=["5", "6", "8"], required=False),
            Input("voice", "口播音色", "choice", default="女声 · 亲和",
                  choices=list(VOICES.keys()), required=False,
                  help="口播时长会决定每镜的停留时间，画面对齐语音"),
            Input("bgm", "背景音乐", "choice", default="轻和声（无版权）",
                  choices=["轻和声（无版权）", "不要"], required=False),
            Input("extra", "补充要求", "textarea", required=False, rows=2,
                  placeholder="例如：面向在职备考，节奏快一点"),
        ]

    def run(self, values: Dict[str, str], ctx: Ctx) -> Dict[str, Any]:
        body = (values.get("body") or "").strip()
        if len(body) < 10:
            raise ValueError("先把要讲的文案贴进来")
        title = (values.get("title") or "").strip()
        n = int(values.get("scenes") or 6)
        voice_label = values.get("voice") or "女声 · 亲和"
        voice_id = VOICES.get(voice_label, VOICES["女声 · 亲和"])
        # 画面主题：cream = 暖橙奶油杂志风（「一题多发」分享版用）；缺省深蓝
        th = _th("cream" if str(values.get("style") or "").strip() == "cream"
                 else "navy")
        bgm_on = (values.get("bgm") or "").startswith("轻和声")
        extra = (values.get("extra") or "").strip() or "无"

        if len(body) > 9000:
            body = body[:9000]

        ctx.progress(0.05, "生成分镜脚本")
        data = ctx.llm_json(SYSTEM, PROMPT.format(title=title or "（无）", body=body,
                                                  extra=extra, n=n),
                            max_tokens=4000, temperature=0.75)
        if not data:
            raise ValueError("模型没有返回可解析的分镜 JSON，请重试")
        scenes = normalize_scenes(data.get("scenes"), n)
        if not scenes:
            raise ValueError("分镜脚本为空")
        ctx.log(f"分镜 {len(scenes)} 镜")

        out_dir = self.output_dir(title or _clip(data.get("title"), 20) or "短视频")
        tmp = tempfile.mkdtemp(prefix="df_video_")

        # ---- 口播：每镜一段，用真实时长决定画面停留
        durs: List[float] = []
        voice_files: List[str] = []
        if voice_id:
            ctx.progress(0.2, "合成口播")
            for i, sc in enumerate(scenes, start=1):
                ctx.check()
                txt = _clip(sc.get("narration"), 120)
                if not txt:
                    durs.append(3.0)
                    voice_files.append("")
                    continue
                p = os.path.join(tmp, f"v{i:02d}.mp3")
                ok = synth(txt, voice_id, p)
                if ok:
                    d = audio_duration(p)
                    voice_files.append(p)
                    durs.append(max(1.6, min(12.0, d + 0.45)))
                else:
                    voice_files.append("")
                    durs.append(max(2.6, len(txt) / 5.2))
                ctx.progress(0.2 + 0.25 * i / len(scenes), f"口播 {i}/{len(scenes)}")
        else:
            for sc in scenes:
                txt = _clip(sc.get("narration"), 200)
                durs.append(max(2.8, min(8.0, len(txt) / 6.0 if txt else 3.2)))

        narration = os.path.join(tmp, "voice.m4a")
        has_voice = False
        if voice_id:
            has_voice = concat_audio(voice_files, narration)
        if has_voice and bgm_on:
            ctx.progress(0.5, "混入背景音乐")
            narration = mix_bgm(narration, os.path.join(tmp, "mixed.m4a"))
        if not has_voice:
            narration = ""

        # ---- 逐帧渲染 → 管道喂 ffmpeg
        ctx.progress(0.55, "渲染画面")
        out_path = os.path.join(out_dir, (K._safe_name(title) or "video") + ".mp4")
        bgs = [_bg(i, th) for i in range(len(scenes))]

        def gen() -> Iterator[bytes]:
            for i, sc in enumerate(scenes):
                for buf in frames_of(sc, bgs[i], durs[i], th):
                    yield buf

        total = sum(durs)
        ctx.log(f"预计时长 {total:.1f} 秒，共 {int(total * FPS)} 帧")
        ctx.progress(0.6, f"编码中（{total:.1f} 秒视频）")
        encode(gen(), out_path, narration)
        ctx.add(out_path)
        ctx.progress(1.0, "完成")

        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

        shot = "\n".join(
            f"{i + 1}. [{_clip(s.get('type'), 8)}] {_clip(s.get('title'), 20)}"
            f"（{durs[i]:.1f}s）" for i, s in enumerate(scenes))
        return {
            "title": _clip(data.get("title"), 40) or title or "竖屏短视频",
            "body": "\n\n".join(_clip(s.get("narration"), 200)
                                for s in scenes if s.get("narration")).strip()
                    or body,
            "shot_hint": shot + f"\n\n视频文件：{out_path}\n时长：{total:.1f} 秒",
            "topics": "",
            "cover": _clip(data.get("title"), 20),
            "_artifacts": [out_path],
            "_out_dir": out_dir,
        }
