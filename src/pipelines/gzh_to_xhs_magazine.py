# -*- coding: utf-8 -*-
"""Pipeline：公众号文章 → 小红书图文（暖橙奶油 · 杂志干货风）。

这是 gzh-to-xhs Skill 包（bundle）的专属运行器 —— 见 README「四·六」：
bundle 形态只做一次文本生成，抓取 / 出图 / 写文件这些动作不会真的发生；
要让它真干活，就给它配一条流水线（本文件）。

与内置 gzh_to_xhs 的关系
  · 抓原文 / 读配图 / 大纲 JSON / 文案生成 —— 完全复用 gzh_to_xhs（同一套方法论，
    kit_draw 本来就是从这份 skill 的 assets/template.py 移植的）
  · 出图 —— 换成 skill 自带设计规范（references/design.md）的暖橙奶油杂志风：
    - 奶油底 #FAF3E9 + 深棕墨 #2A2118 + 暖橙强调 #E8622B + 焦糖金 #C98A2E
    - 封面是杂志刊头版式（胶囊刊头条 + 焦糖金引题 + 大标题高光词 + 整块深棕墨数据卡），
      不是深蓝渐变
    - 投影一律暖棕 (72,54,38)，冷灰投影会毁掉奶油暖调
    - 表格：深棕墨表头 / 浅杏合计行 / 灰棕弱化值（0 或 —）
    - 收尾页：深棕墨大卡片 + 橙色圆形序号 + 奶油条目
"""
from __future__ import annotations

from typing import Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter

from . import gzh_to_xhs as G
from . import kit_draw as K
from .base import Ctx, register


class MagazinePalette:
    """暖橙奶油色板（gzh-to-xhs skill · references/design.md）。

    槽位名沿用 kit_draw.Palette（NAVY / PALE / WARM…），版式代码零改动即可换肤：
    这里的 NAVY 实际是深棕墨 —— kit_draw 里所有「主深色」都走这个槽位。
    """

    BG = (250, 243, 233, 255)      # 奶油底
    WHITE = (255, 255, 255, 255)
    NAVY = (42, 33, 24, 255)       # 深棕墨（主深色槽位）
    NAVY2 = (107, 74, 42, 255)     # 暖褐（表格表头槽位）
    ORANGE = (232, 98, 43, 255)    # 强调 暖橙
    GOLD = (201, 138, 46, 255)     # 点缀 焦糖金
    INK = (38, 31, 25, 255)        # 正文墨黑
    INK2 = (138, 123, 105, 255)    # 次要灰棕
    LINE = (232, 220, 200, 255)    # 分割线
    PALE = (245, 231, 211, 255)    # 浅杏（合计行槽位）
    WARM = (253, 247, 239, 255)    # 交替行
    MUTE = (206, 192, 172, 255)    # 弱化值（0 / —）


class MagazineDeck(K.Deck):
    """暖橙奶油杂志风画布：换色板 + 暖棕投影 + 杂志刊头封面 / 收尾页。

    列表 / 表格 / 要点 / 段落页直接继承 kit_draw 版式（配色走上面的色板），
    只覆写有硬编码冷色或版式差异的部分。
    """

    def __init__(self, out_dir: str, **kwargs):
        # Deck.__init__ 的默认参数 pal=Palette（深蓝风）在定义时就绑死了，
        # 子类必须在这里把默认色板换成暖橙奶油 —— 否则版式对、颜色全错
        kwargs.setdefault("pal", MagazinePalette)
        super().__init__(out_dir, **kwargs)

    # ------------------------------------------------ 暖棕投影
    def _shadow(self, base, box, r=28, dy=10, blur=22, alpha=38):
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(
            (box[0], box[1] + dy, box[2], box[3] + dy), radius=r,
            fill=(72, 54, 38, alpha))          # 必须暖棕，冷灰会毁掉奶油底暖调
        base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))

    # ------------------------------------------------ 表格（暖色行底）
    def grid_table(self, base, d, top, headers, widths, rows,
                   row_h: int = 92, header_h: int = 84) -> float:
        x0 = 72
        x1 = x0 + sum(widths)
        d.rounded_rectangle((x0, top, x1, top + header_h), radius=18, fill=self.P.NAVY)
        d.rectangle((x0, top + header_h - 24, x1, top + header_h), fill=self.P.NAVY)
        cx = x0
        for i, htxt in enumerate(headers):
            d.text((cx + widths[i] / 2, top + header_h / 2), str(htxt),
                   font=K.font(24, True), fill=self.P.BG, anchor="mm")
            cx += widths[i]
        for r, row in enumerate(rows):
            kind, vals = row[-1], list(row[:-1])
            ry = top + header_h + r * row_h
            bg = self.P.PALE if kind == "total" else (
                self.P.WARM if r % 2 else self.P.WHITE)
            d.rectangle((x0, ry, x1, ry + row_h), fill=bg)
            d.line([(x0, ry), (x1, ry)], fill=self.P.LINE, width=2)
            cx = x0
            for i, v in enumerate(vals):
                if i == 0:
                    d.text((cx + 22, ry + row_h / 2), str(v),
                           font=K.font(25, kind == "total"),
                           fill=(self.P.NAVY if kind == "total" else self.P.INK),
                           anchor="lm")
                elif i == len(vals) - 1:
                    col = self.P.ORANGE if kind == "hot" else (
                        self.P.NAVY if kind == "total" else self.P.INK)
                    d.text((cx + widths[i] - 22, ry + row_h / 2), str(v),
                           font=K.font(30, True), fill=col, anchor="rm")
                elif str(v) in ("0", "—", "-"):
                    d.text((cx + widths[i] / 2, ry + row_h / 2), str(v),
                           font=K.font(26, False), fill=self.P.MUTE, anchor="mm")
                else:
                    d.text((cx + widths[i] / 2, ry + row_h / 2), str(v),
                           font=K.font(26, False), fill=(140, 124, 105, 255),
                           anchor="mm")
                cx += widths[i]
        end = top + header_h + len(rows) * row_h
        d.line([(x0, end), (x1, end)], fill=self.P.LINE, width=2)
        return end

    # ------------------------------------------------ 杂志刊头封面
    def cover(self, *, tag: str = "", title_small: str = "",
              title_big: Sequence[str] = (), sub1: str = "", sub2: str = "",
              stats: Sequence[Tuple[str, str, str]] = (), accent: str = "",
              footer: str = "个人整理 · 仅供参考", badge: str = "建议收藏",
              **_) -> str:
        """杂志刊头式封面（奶油底，无渐变 / 光晕 / 网点）。

        版式移植自 skill 的 assets/template.py：
        刊头条 → 引题 → 124px 大标题（高光词染暖橙）→ 橙条 → 副标题
        → 整块深棕墨数据卡（竖向细线三等分，不做三张小卡）→ 页脚。
        """
        W, H, P = self.W, self.H, self.P
        base = Image.new("RGBA", (W, H), P.BG)
        d = ImageDraw.Draw(base)
        d.rectangle((0, 0, W, 14), fill=P.NAVY)            # 顶部品牌条

        lines = [str(x).strip() for x in list(title_big)[:2] if str(x).strip()]
        if not lines:
            lines = ["内容拆解"]
        acc = str(accent or "").strip()
        if acc and acc not in lines[-1]:
            acc = ""                                       # 不是子串就不染，宁缺毋错

        # 刊头条：胶囊标签 + 刊号 + 细分割线
        if tag:
            self.pill(d, 84, 110, tag[:18], K.font(26, True), P.BG, P.NAVY,
                      padx=22, padh=13)
        d.text((W - 84, 112), "NO.01 / 干货手册", font=K.font(24, False),
               fill=P.INK2, anchor="rm")
        d.line([(84, 196), (W - 84, 196)], fill=P.LINE, width=2)

        # 引题（焦糖金）
        if title_small:
            d.text((84, 250), title_small[:10], font=K.font(64, True), fill=P.GOLD)

        # 主标题：第一行纯深棕墨，第二行带一个暖橙高光词
        d.text((84, 336), lines[0][:8], font=K.font(124, True), fill=P.NAVY)
        if len(lines) > 1:
            K.text_mixed(d, 84, 452, lines[1][:8], K.font(124, True), P.NAVY,
                         acc, P.ORANGE)

        # 橙色短条 + 副标题
        d.rounded_rectangle((84, 640, 300, 648), radius=4, fill=P.ORANGE)
        if sub1:
            self.para(d, sub1[:18], K.font(40, True), P.INK, 84, 690, 900, lh=56)
        if sub2:
            self.para(d, sub2[:30], K.font(28, False), P.INK2, 84, 756, 900, lh=44)

        # 底部整块深棕墨数据卡（杂志感来自整块底色，不是三张小卡）
        st = list(stats)[:3]
        if st:
            box = (72, 880, W - 72, 1200)
            self._shadow(base, box, r=36, alpha=48)
            d = ImageDraw.Draw(base)
            d.rounded_rectangle(box, radius=36, fill=P.NAVY)
            cw = (W - 144) / 3.0
            for i, item in enumerate(st):
                num, unit, label = (list(item) + ["", "", ""])[:3]
                cx0 = 72 + i * cw
                cm = cx0 + cw / 2
                if i:
                    d.line([(cx0, 928), (cx0, 1152)], fill=(74, 58, 42, 255), width=2)
                fn = K.font(72, True)
                nw = fn.getlength(str(num)[:6])
                uw = (8 + K.font(26, True).getlength(str(unit)[:4])) if unit else 0
                sx = cm - (nw + uw) / 2
                d.text((sx, 976), str(num)[:6], font=fn, fill=P.GOLD, anchor="lm")
                if unit:
                    d.text((sx + nw + 8, 986), str(unit)[:4], font=K.font(26, True),
                           fill=P.BG, anchor="lm")
                d.text((cm, 1060), str(label)[:8], font=K.font(24, False),
                       fill=(198, 186, 168, 255), anchor="mm")

        # 页脚：左注释 + 右暖橙胶囊
        if footer:
            d.text((84, 1266), footer, font=K.font(26, False), fill=P.INK2)
        if badge:
            bw = K.font(26, True).getlength(badge[:6]) + 44
            self.pill(d, W - 84 - bw, 1266, badge[:6], K.font(26, True),
                      (255, 255, 255, 255), P.ORANGE, padx=22, padh=12)
        d.ellipse((84, 1300, 108, 1324), outline=P.ORANGE, width=4)   # 纯几何装饰
        return self.save(base, "01_封面")

    # ------------------------------------------------ 金句页（暖色点缀）
    def quote_page(self, idx: int, *, tag: str = "", title: str = "",
                   quote: str = "", source: str = "", name: str = "", **_) -> str:
        base = self.new_bg()
        d = ImageDraw.Draw(base)
        self.page_no(d, idx)
        y = self.header(d, tag, title)
        box = (72, y + 60, self.W - 72, y + 60 + 620)
        self.card(base, box, r=32, fill=self.P.NAVY)
        d = ImageDraw.Draw(base)
        d.text((128, y + 130), "\u201c", font=K.font(160, True), fill=self.P.GOLD)
        ty = y + 250
        for ln in K.fit_lines(quote, K.font(46, True), self.W - 260, 7):
            d.text((128, ty), ln, font=K.font(46, True), fill=(255, 255, 255, 255))
            ty += 74
        if source:
            d.text((self.W - 128, box[3] - 70), "—— " + source, font=K.font(26, False),
                   fill=(198, 186, 168, 255), anchor="rm")
        return self.save(base, "%02d_%s" % (idx, name or title))

    # ------------------------------------------------ 收尾页（深卡 + 橙圆序号）
    def end_page(self, idx: int, *, title: str = "", lines: Sequence[str] = (),
                 cta: str = "", name: str = "", **_) -> str:
        W, H, P = self.W, self.H, self.P
        base = Image.new("RGBA", (W, H), P.BG)
        d = ImageDraw.Draw(base)
        d.rectangle((0, 0, W, 14), fill=P.NAVY)
        self.page_no(d, idx)

        d.text((84, 210), (title or "就到这里")[:12], font=K.font(64, True), fill=P.NAVY)
        d.rounded_rectangle((86, 316, 300, 324), radius=4, fill=P.ORANGE)

        rows = [str(x) for x in list(lines)[:5] if str(x).strip()]
        box = (72, 400, W - 72, 400 + 150 + 96 * max(1, len(rows)) + 40)
        box = (box[0], box[1], box[2], min(box[3], H - 260))
        self._shadow(base, box, r=36, alpha=44)
        d = ImageDraw.Draw(base)
        d.rounded_rectangle(box, radius=36, fill=P.NAVY)
        y = box[1] + 75
        for i, ln in enumerate(rows):
            cy = y + 22
            d.ellipse((128, cy - 26, 180, cy + 26), fill=P.ORANGE)
            d.text((154, cy), str(i + 1), font=K.font(28, True),
                   fill=(255, 255, 255, 255), anchor="mm")
            d.text((212, cy), ln[:26], font=K.font(34, False), fill=P.BG, anchor="lm")
            y += 96

        if cta:
            self.pill(d, 84, H - 170, cta[:16], K.font(32, True),
                      (255, 255, 255, 255), P.ORANGE, padx=32, padh=20)
        return self.save(base, "%02d_%s" % (idx, name or title))


@register
class GzhToXhsMagazine(G.GzhToXhs):
    """gzh-to-xhs Skill 包的运行器：抓取 / 大纲全复用，出图换暖橙杂志风。"""

    key = "gzh_to_xhs_magazine"
    name = "公众号转小红书图文 · 暖橙杂志风"
    desc = ("gzh-to-xhs Skill 包的流水线运行器：贴公众号链接 → 抓原文 → 读配图 → "
            "生成文案 → 出 8 张暖橙奶油杂志风 3:4 配图（skill 自带设计规范）")
    note = ("耗时约 60-150 秒（抓取 + 读配图 + 一次模型调用 + 逐张出图）。"
            "公众号有反爬，遇到「环境异常」改用「手动粘贴正文」；"
            "配图里常有表格数字，勾上「读原文配图」用视觉模型抽出来 —— "
            "需要当前模型能读图（deepseek-flash 可以，deepseek-v4-pro 不行）。")
    outputs = ["小红书文案", "8 张暖橙杂志风 1080×1440 配图"]
    deck_cls = MagazineDeck
