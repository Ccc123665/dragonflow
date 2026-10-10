# -*- coding: utf-8 -*-
"""小红书 3:4 图文出图工具箱。

从本地 gzh-to-xhs skill 的 assets/template.py 移植并扩展：
  · 画布尺寸 / 输出目录 / 主题色都改成参数，不再写死在模块里
  · 字体路径按平台探测（Windows / macOS / Linux），找不到就退回默认字体
  · 新增要点页、金句页、段落页三种版式，覆盖「一篇文章拆成 8 张图」的常见结构

版式清单
  cover()        封面：深蓝渐变 + 标题 + 数据卡
  rows_card()    列表页：顶部色带 + 若干行（名称 / 数值胶囊 / 说明）
  table_page()   表格页：多列数据表，支持重点行与合计行
  bullets_page() 要点页：序号圆圈 + 若干条要点
  quote_page()   金句页：大字引用 + 出处
  text_page()    段落页：小标题 + 正文段落（长文拆解用）
  end_page()     收尾页：行动号召 + 账号署名

出图后务必逐张看图确认最后一行没被裁掉 —— 溢出不会报错。
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------------------------------------------------------- 字体
_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyhbd.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
_CANDIDATES_REG = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

_FONT_CACHE: dict = {}


def _first_existing(paths: Sequence[str]) -> str:
    for p in paths:
        if os.path.exists(p):
            return p
    return ""


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = _first_existing(_CANDIDATES_BOLD if bold else _CANDIDATES_REG) \
        or _first_existing(_CANDIDATES_REG)
    try:
        f = ImageFont.truetype(path, size, index=0) if path else ImageFont.load_default(size)
    except Exception:
        try:
            f = ImageFont.load_default(size)
        except Exception:
            f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def has_cjk_font() -> bool:
    return bool(_first_existing(_CANDIDATES_BOLD) or _first_existing(_CANDIDATES_REG))


# ---------------------------------------------------------------- 配色
class Palette:
    BG = (246, 244, 239, 255)
    WHITE = (255, 255, 255, 255)
    NAVY = (19, 46, 82, 255)
    NAVY2 = (40, 82, 140, 255)
    ORANGE = (222, 84, 44, 255)
    GOLD = (240, 169, 62, 255)
    INK = (30, 39, 52, 255)
    INK2 = (106, 116, 130, 255)
    LINE = (233, 230, 223, 255)
    PALE = (237, 242, 249, 255)
    WARM = (252, 245, 238, 255)
    MUTE = (196, 200, 208, 255)


# ---------------------------------------------------------------- 断行
# 数字/日期整体不可拆（"10月11日" 不能被切成 "1" + "0月11日"），
# 行首不出现收尾标点（"，。" 之类不能被顶到下一行开头）。
_UNIT = "年月日时分秒周天个期点"
_TOK = re.compile(
    r"\d+(?:[.\-/:]\d+)*[" + _UNIT + r"]?(?:\d+(?:[.\-/:]\d+)*[" + _UNIT + r"]?)*"
    r"|[A-Za-z]+"
    r"|."
)
_NO_HEAD = "，。、；：？！）】》”’%,.;:?!)]}>"


def wrap(text: str, f: ImageFont.FreeTypeFont, maxw: float) -> List[str]:
    lines: List[str] = []
    for raw in str(text or "").split("\n"):
        seg, cur = [], ""
        for tk in _TOK.findall(raw):
            if cur and f.getlength(cur + tk) > maxw:
                seg.append(cur)
                cur = ""
            if not cur and tk in _NO_HEAD and seg:
                seg[-1] += tk
                continue
            cur += tk
        seg.append(cur)
        lines.extend(seg)
    return lines


def fit_lines(text: str, f: ImageFont.FreeTypeFont, maxw: float,
              max_lines: int) -> List[str]:
    """断行并限制行数，超出部分用省略号收尾。"""
    lines = wrap(text, f, maxw)
    if len(lines) <= max_lines:
        return lines
    keep = lines[:max_lines]
    keep[-1] = keep[-1].rstrip("，。、；：,. ") + "…"
    return keep


def text_mixed(d, x: float, y: float, text: str, f: ImageFont.FreeTypeFont,
               base_fill, accent: str, accent_fill) -> None:
    """画一行字，把其中的 accent 子串染成强调色（封面标题的高光词）。

    accent 不是 text 的连续子串时整行按原色画 —— 宁可不高亮，不能画错。
    """
    text, accent = str(text or ""), str(accent or "")
    if not accent or accent not in text:
        d.text((x, y), text, font=f, fill=base_fill)
        return
    i = text.index(accent)
    left, mid, right = text[:i], text[i:i + len(accent)], text[i + len(accent):]
    if left:
        d.text((x, y), left, font=f, fill=base_fill)
        x += f.getlength(left)
    d.text((x, y), mid, font=f, fill=accent_fill)
    x += f.getlength(mid)
    if right:
        d.text((x, y), right, font=f, fill=base_fill)


# ================================================================ 画布
class Deck:
    """一个出图画布。一次出多张图就复用同一个 Deck。"""

    def __init__(self, out_dir: str, w: int = 1080, h: int = 1440,
                 pal: type = Palette, total: int = 8):
        self.out_dir = out_dir
        self.W = w
        self.H = h
        self.P = pal
        self.total = total
        self.saved: List[str] = []
        os.makedirs(out_dir, exist_ok=True)

    # ------------------------------------------------ 底层
    def _shadow(self, base, box, r=28, dy=10, blur=22, alpha=38):
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(
            (box[0], box[1] + dy, box[2], box[3] + dy), radius=r, fill=(24, 40, 72, alpha))
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))

    def card(self, base, box, r=28, fill=None):
        self._shadow(base, box, r=r)
        ImageDraw.Draw(base).rounded_rectangle(box, radius=r, fill=fill or self.P.WHITE)
        return ImageDraw.Draw(base)

    def pill(self, d, x, cy, text, f, fg, bg, padx=24, padh=15) -> float:
        """胶囊标签，x 为左边缘，cy 为垂直中心。返回宽度。"""
        w = f.getlength(text)
        h = f.size + padh * 2
        d.rounded_rectangle((x, cy - h / 2, x + w + padx * 2, cy + h / 2),
                            radius=h / 2, fill=bg)
        d.text((x + padx, cy), text, font=f, fill=fg, anchor="lm")
        return w + padx * 2

    def para(self, d, text, f, fill, x, y, maxw, lh=None, max_lines=0) -> float:
        lh = lh or int(f.size * 1.6)
        lines = fit_lines(text, f, maxw, max_lines) if max_lines else wrap(text, f, maxw)
        for ln in lines:
            d.text((x, y), ln, font=f, fill=fill)
            y += lh
        return y

    def new_bg(self):
        base = Image.new("RGBA", (self.W, self.H), self.P.BG)
        ImageDraw.Draw(base).rectangle((0, 0, self.W, 14), fill=self.P.NAVY)
        return base

    def save(self, base, name: str) -> str:
        path = os.path.join(self.out_dir, _safe_name(name) + ".png")
        base.convert("RGB").save(path, quality=95)
        self.saved.append(path)
        return path

    # ------------------------------------------------ 页头
    def page_no(self, d, idx: int):
        d.text((self.W - 72, 84), "%02d / %02d" % (idx, self.total),
               font=font(26, True), fill=(178, 176, 170, 255), anchor="rm")

    def header(self, d, tag: str, title: str, sub: Optional[str] = None) -> float:
        """内容页统一页头。返回正文起始 y。"""
        self.pill(d, 72, 118, tag, font(26, True), self.P.WHITE, self.P.NAVY,
                  padx=22, padh=13)
        d.text((72, 186), title, font=font(60, True), fill=self.P.NAVY)
        y = 276
        if sub:
            d.text((72, y), sub, font=font(28, False), fill=self.P.INK2)
            y += 52
        d.rounded_rectangle((72, y, 148, y + 8), radius=4, fill=self.P.ORANGE)
        return y + 44

    def banner(self, d, y: float, text: str, fill=None) -> float:
        """深色说明条。返回其下方内容起始 y。"""
        d.rounded_rectangle((72, y - 4, self.W - 72, y + 76), radius=24,
                            fill=fill or self.P.NAVY)
        d.text((120, y + 34), text, font=font(30, True), fill=self.P.WHITE, anchor="lm")
        return y + 106

    # ================================================ 版式
    def cover(self, *, tag: str, title_small: str, title_big: Sequence[str],
              sub1: str = "", sub2: str = "", stats: Sequence[Tuple[str, str, str]] = (),
              accent: str = "",
              footer: str = "个人整理 · 仅供参考", badge: str = "建议收藏") -> str:
        """封面。stats: [(数字, 单位, 说明), ...]，最多 3 个。"""
        W, H, P = self.W, self.H, self.P
        base = Image.new("RGBA", (W, H), P.NAVY)
        d = ImageDraw.Draw(base)
        for y in range(H):                       # 渐变
            t = y / H
            d.line([(0, y), (W, y)],
                   fill=(int(14 + 22 * t), int(36 + 40 * t), int(68 + 62 * t), 255))
        for box, color in [((W - 560, -420, W + 260, 400), (222, 84, 44, 150)),
                           ((-360, H - 520, 420, H + 260), (64, 130, 210, 130))]:
            g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(g).ellipse(box, fill=color)
            base.alpha_composite(g.filter(ImageFilter.GaussianBlur(145)))
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # 细网点
        od = ImageDraw.Draw(ov)
        for yy in range(80, H, 46):
            for xx in range(60, W, 46):
                od.ellipse((xx, yy, xx + 3, yy + 3), fill=(255, 255, 255, 16))
        base.alpha_composite(ov)
        d = ImageDraw.Draw(base)

        if tag:
            self.pill(d, 84, 152, tag[:18], font(28, True), P.NAVY,
                      (255, 255, 255, 235), padx=26, padh=16)
        y = 336
        if title_small:
            d.text((84, y), title_small, font=font(64, True), fill=(250, 214, 140, 255))
            y += 100
        for ln in list(title_big)[:2]:
            text_mixed(d, 84, y, ln, font(124, True), P.WHITE,
                       accent, (250, 214, 140, 255))     # 高光词染焦糖金
            y += 154
        d.rounded_rectangle((86, y + 24, 300, y + 40), radius=8, fill=P.ORANGE)
        y += 92
        if sub1:
            y = self.para(d, sub1, font(40, True), (255, 255, 255, 240), 86, y, 900,
                          lh=62, max_lines=2)
            y += 6
        if sub2:
            self.para(d, sub2, font(30, False), (208, 220, 238, 255), 86, y, 900,
                      lh=48, max_lines=2)

        if stats:
            bw, gap = 292, 30
            panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # 半透明必须独立图层合成
            pd = ImageDraw.Draw(panel)
            x = 84
            for _ in stats[:3]:
                pd.rounded_rectangle((x, 1090, x + bw, 1290), radius=26,
                                     fill=(255, 255, 255, 32),
                                     outline=(255, 255, 255, 78), width=2)
                x += bw + gap
            base.alpha_composite(panel)
            d = ImageDraw.Draw(base)
            x = 84
            for num, unit, label in list(stats)[:3]:
                d.text((x + 34, 1140), num, font=font(62, True), fill=P.WHITE, anchor="lm")
                d.text((x + 34 + font(62, True).getlength(num) + 10, 1152), unit,
                       font=font(28, True), fill=(250, 214, 140, 255), anchor="lm")
                d.text((x + 34, 1228), label, font=font(24, False),
                       fill=(206, 218, 236, 255), anchor="lm")
                x += bw + gap
        if footer:
            d.text((84, H - 88), footer, font=font(26, False), fill=(180, 196, 220, 255))
        if badge:
            d.text((W - 84, H - 88), badge, font=font(28, True),
                   fill=(250, 214, 140, 255), anchor="rm")
        return self.save(base, "01_封面")

    def rows_card(self, idx: int, *, tag: str, title: str, sub: str = "",
                  banner: str = "",
                  rows: Sequence[Tuple[str, str, str, bool]] = (),
                  name: str = "") -> str:
        """列表页。rows=[(名称, 数值胶囊, 说明, 是否重点), ...]"""
        base = self.new_bg()
        d = ImageDraw.Draw(base)
        self.page_no(d, idx)
        y = self.header(d, tag, title, sub or None)
        if banner:
            y = self.banner(d, y, banner)
        rh = 132
        for i, row in enumerate(rows):
            nm, cnt, ref, hot = (list(row) + ["", "", "", False])[:4]
            ry = y + i * rh
            if i:
                d.line([(104, ry), (self.W - 104, ry)], fill=self.P.LINE, width=2)
            d.text((104, ry + 30), str(nm)[:22], font=font(32, True), fill=self.P.NAVY)
            if cnt:
                pf = font(25, True)
                pw = pf.getlength(str(cnt)) + 40
                d.rounded_rectangle((self.W - 104 - pw, ry + 26, self.W - 104, ry + 74),
                                    radius=24, fill=(self.P.ORANGE if hot else self.P.PALE))
                d.text((self.W - 104 - pw / 2, ry + 50), str(cnt), font=pf,
                       fill=(self.P.WHITE if hot else self.P.NAVY), anchor="mm")
            if ref:
                self.para(d, str(ref), font(24, False), self.P.INK2, 104, ry + 86,
                          self.W - 104 - 104 - 200, lh=36, max_lines=1)
        return self.save(base, "%02d_%s" % (idx, name or title))

    def grid_table(self, base, d, top: float, headers: Sequence[str],
                   widths: Sequence[float], rows: Sequence[Sequence],
                   row_h: int = 92, header_h: int = 84) -> float:
        """数据表。rows 每项最后一个是 kind：none | hot | total。"""
        x0 = 72
        x1 = x0 + sum(widths)
        d.rounded_rectangle((x0, top, x1, top + header_h), radius=18, fill=self.P.NAVY2)
        d.rectangle((x0, top + header_h - 24, x1, top + header_h), fill=self.P.NAVY2)
        cx = x0
        for i, htxt in enumerate(headers):
            d.text((cx + widths[i] / 2, top + header_h / 2), str(htxt),
                   font=font(24, True), fill=self.P.WHITE, anchor="mm")
            cx += widths[i]
        for r, row in enumerate(rows):
            kind, vals = row[-1], list(row[:-1])
            ry = top + header_h + r * row_h
            bg = (238, 242, 249, 255) if kind == "total" else (
                (250, 249, 246, 255) if r % 2 else self.P.WHITE)
            d.rectangle((x0, ry, x1, ry + row_h), fill=bg)
            d.line([(x0, ry), (x1, ry)], fill=self.P.LINE, width=2)
            cx = x0
            for i, v in enumerate(vals):
                if i == 0:
                    d.text((cx + 22, ry + row_h / 2), str(v),
                           font=font(25, kind == "total"),
                           fill=(self.P.NAVY if kind == "total" else self.P.INK),
                           anchor="lm")
                elif i == len(vals) - 1:
                    col = self.P.ORANGE if kind == "hot" else (
                        self.P.NAVY if kind == "total" else self.P.INK)
                    d.text((cx + widths[i] - 22, ry + row_h / 2), str(v),
                           font=font(30, True), fill=col, anchor="rm")
                elif str(v) == "0":
                    d.text((cx + widths[i] / 2, ry + row_h / 2), str(v),
                           font=font(26, False), fill=self.P.MUTE, anchor="mm")
                else:
                    d.text((cx + widths[i] / 2, ry + row_h / 2), str(v),
                           font=font(26, False), fill=(120, 128, 140, 255), anchor="mm")
                cx += widths[i]
        end = top + header_h + len(rows) * row_h
        d.line([(x0, end), (x1, end)], fill=self.P.LINE, width=2)
        return end

    def table_page(self, idx: int, *, tag: str, title: str, sub: str = "",
                   banner: str = "", headers: Sequence[str] = (),
                   widths: Sequence[float] = (), rows: Sequence[Sequence] = (),
                   note: str = "", name: str = "") -> str:
        base = self.new_bg()
        d = ImageDraw.Draw(base)
        self.page_no(d, idx)
        y = self.header(d, tag, title, sub or None)
        top = self.banner(d, y, banner) if banner else y
        # 行高自适应：可用高度约 H-480，行多了自动压
        avail = self.H - top - 150
        n = max(1, len(rows))
        row_h = 92
        if 84 + n * row_h > avail:
            row_h = max(58, int((avail - 84) / n))
        end = self.grid_table(base, d, top, headers, widths, rows, row_h=row_h)
        if note:
            self.para(d, note, font(24, False), self.P.INK2, 72, end + 28,
                      self.W - 144, lh=38, max_lines=2)
        return self.save(base, "%02d_%s" % (idx, name or title))

    def bullets_page(self, idx: int, *, tag: str, title: str, sub: str = "",
                     banner: str = "",
                     items: Sequence[Tuple[str, str]] = (), name: str = "") -> str:
        """要点页。items=[(要点标题, 补充说明), ...]，最多 6 条。"""
        base = self.new_bg()
        d = ImageDraw.Draw(base)
        self.page_no(d, idx)
        y = self.header(d, tag, title, sub or None)
        if banner:
            y = self.banner(d, y, banner)
        items = list(items)[:6]
        top = y + 16
        bottom = self.H - 120
        rh = min(190, max(120, int((bottom - top) / max(1, len(items)))))
        for i, it in enumerate(items):
            head, desc = (list(it) + ["", ""])[:2]
            ry = top + i * rh
            box = (72, ry, self.W - 72, ry + rh - 22)
            self.card(base, box, r=24)
            d = ImageDraw.Draw(base)
            cx, cy = 128, ry + (rh - 22) / 2
            d.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), fill=self.P.NAVY)
            d.text((cx, cy), str(i + 1), font=font(30, True), fill=self.P.WHITE,
                   anchor="mm")
            d.text((cx + 58, ry + 34), str(head)[:24], font=font(34, True),
                   fill=self.P.NAVY)
            if desc:
                self.para(d, str(desc), font(25, False), self.P.INK2,
                          cx + 58, ry + 84, self.W - 72 - 60 - (cx + 58) + 72,
                          lh=38, max_lines=2)
        return self.save(base, "%02d_%s" % (idx, name or title))

    def quote_page(self, idx: int, *, tag: str, title: str, quote: str,
                   source: str = "", name: str = "") -> str:
        """金句页：一张大字引用。"""
        base = self.new_bg()
        d = ImageDraw.Draw(base)
        self.page_no(d, idx)
        y = self.header(d, tag, title)
        box = (72, y + 60, self.W - 72, y + 60 + 620)
        self.card(base, box, r=32, fill=self.P.NAVY)
        d = ImageDraw.Draw(base)
        d.text((128, y + 130), "“", font=font(160, True), fill=(250, 214, 140, 200))
        ty = y + 250
        for ln in fit_lines(quote, font(46, True), self.W - 260, 7):
            d.text((128, ty), ln, font=font(46, True), fill=self.P.WHITE)
            ty += 74
        if source:
            d.text((self.W - 128, box[3] - 70), "—— " + source, font=font(26, False),
                   fill=(180, 196, 220, 255), anchor="rm")
        return self.save(base, "%02d_%s" % (idx, name or title))

    def text_page(self, idx: int, *, tag: str, title: str, sub: str = "",
                  paras: Sequence[str] = (), name: str = "") -> str:
        """段落页：小标题 + 若干段正文，长文拆解用。"""
        base = self.new_bg()
        d = ImageDraw.Draw(base)
        self.page_no(d, idx)
        y = self.header(d, tag, title, sub or None)
        for p in list(paras)[:4]:
            y = self.para(d, str(p), font(28, False), self.P.INK, 72, y,
                          self.W - 144, lh=48, max_lines=4)
            y += 22
            if y > self.H - 140:
                break
        return self.save(base, "%02d_%s" % (idx, name or title))

    def end_page(self, idx: int, *, title: str, lines: Sequence[str] = (),
                 cta: str = "", name: str = "") -> str:
        """收尾页。"""
        base = Image.new("RGBA", (self.W, self.H), self.P.NAVY)
        d = ImageDraw.Draw(base)
        for y in range(self.H):
            t = y / self.H
            d.line([(0, y), (self.W, y)],
                   fill=(int(14 + 22 * t), int(36 + 40 * t), int(68 + 62 * t), 255))
        d.text((84, 420), title, font=font(72, True), fill=self.P.WHITE)
        d.rounded_rectangle((86, 540, 300, 556), radius=8, fill=self.P.ORANGE)
        y = 620
        for ln in list(lines)[:5]:
            d.text((84, y), "· " + str(ln)[:26], font=font(34, False),
                   fill=(214, 226, 244, 255))
            y += 68
        if cta:
            self.pill(d, 84, self.H - 240, cta[:24], font(32, True), self.P.NAVY,
                      (250, 214, 140, 255), padx=32, padh=20)
        return self.save(base, "%02d_%s" % (idx, name or title))


def _safe_name(name: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(name or "")).strip("_")
    return s[:48] or "page"
