# -*- coding: utf-8 -*-
"""
小红书 3:4 图文 —— 通用模板（暖橙奶油 · 杂志干货风）
改：OUT 路径、各 make_* 函数里的文案，直接跑。
跑：<managed-python> assets/template.py
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1440
OUT = r"./图片"
os.makedirs(OUT, exist_ok=True)

FBD = r"C:\Windows\Fonts\msyhbd.ttc"
FRG = r"C:\Windows\Fonts\msyh.ttc"


def F(size, bold=True):
    try:
        return ImageFont.truetype(FBD if bold else FRG, size, index=0)
    except Exception:
        return ImageFont.truetype(FRG, size, index=0)


# 暖橙奶油色板
BG = (250, 243, 233, 255)      # 奶油底
CREAM = (250, 243, 233, 255)
WHITE = (255, 255, 255, 255)
DARK = (42, 33, 24, 255)       # 主色 深棕墨
BROWN = (107, 74, 42, 255)     # 暖褐
ORANGE = (232, 98, 43, 255)    # 强调 暖橙
GOLD = (201, 138, 46, 255)     # 点缀 焦糖金
INK = (38, 31, 25, 255)
INK2 = (138, 123, 105, 255)
LINE = (232, 220, 200, 255)
PALE = (245, 231, 211, 255)    # 浅杏
ALT = (253, 247, 239, 255)     # 交替行
MUTE = (206, 192, 172, 255)
ON_DARK = (198, 186, 168, 255)  # 深底上的次要字

# 向后兼容别名（老脚本里的 NAVY/WARM 继续能用）
NAVY = DARK
NAVY2 = BROWN
WARM = ALT
GOLDT = GOLD


# ---------------- 基础绘制 ----------------
def shadow(base, box, r=28, dy=10, blur=22, alpha=38):
    """暖棕投影，不要用冷灰/深蓝，会破坏奶油底暖调"""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (box[0], box[1] + dy, box[2], box[3] + dy), radius=r, fill=(72, 54, 38, alpha))
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def card(base, box, r=28, fill=WHITE):
    shadow(base, box, r=r)
    ImageDraw.Draw(base).rounded_rectangle(box, radius=r, fill=fill)
    return ImageDraw.Draw(base)


def wrap(text, font, maxw):
    lines = []
    for raw in text.split("\n"):
        cur = ""
        for ch in raw:
            if font.getlength(cur + ch) <= maxw:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def para(d, text, font, fill, x, y, maxw, lh=None):
    lh = lh or int(font.size * 1.6)
    for ln in wrap(text, font, maxw):
        d.text((x, y), ln, font=font, fill=fill)
        y += lh
    return y


def pill(d, x, cy, text, font, fg, bg, padx=24, padh=15):
    """胶囊标签，x 为左边缘，cy 为垂直中心。返回宽度。"""
    w = font.getlength(text)
    h = font.size + padh * 2
    d.rounded_rectangle((x, cy - h / 2, x + w + padx * 2, cy + h / 2), radius=h / 2, fill=bg)
    d.text((x + padx, cy), text, font=font, fill=fg, anchor="lm")
    return w + padx * 2


def text_mixed(d, x, y, text, font, base_fill, accent=None, accent_fill=ORANGE):
    """画一行字，并把 accent 子串换成强调色（封面标题的高光词）"""
    if not accent or accent not in text:
        d.text((x, y), text, font=font, fill=base_fill)
        return
    i = text.index(accent)
    left, mid, right = text[:i], text[i:i + len(accent)], text[i + len(accent):]
    if left:
        d.text((x, y), left, font=font, fill=base_fill)
        x += font.getlength(left)
    d.text((x, y), mid, font=font, fill=accent_fill)
    x += font.getlength(mid)
    if right:
        d.text((x, y), right, font=font, fill=base_fill)


def new_bg():
    base = Image.new("RGBA", (W, H), BG)
    ImageDraw.Draw(base).rectangle((0, 0, W, 14), fill=DARK)
    return base


def page_no(d, idx, total=8):
    d.text((W - 72, 84), "%02d / %02d" % (idx, total), font=F(26, True),
           fill=(196, 182, 162, 255), anchor="rm")


def header(d, tag, title, sub=None):
    """内容页统一页头。返回正文起始 y。"""
    pill(d, 72, 118, tag, F(26, True), CREAM, DARK, padx=22, padh=13)
    d.text((72, 186), title, font=F(60, True), fill=DARK)
    y = 276
    if sub:
        d.text((72, y), sub, font=F(28, False), fill=INK2)
        y += 52
    d.rounded_rectangle((72, y, 148, y + 8), radius=4, fill=ORANGE)
    return y + 44


def banner(d, y, text, fill=DARK):
    """内容页顶部的深色说明条。返回其下方内容起始 y。"""
    d.rounded_rectangle((72, y - 4, 1008, y + 76), radius=24, fill=fill)
    d.text((120, y + 34), text, font=F(30, True), fill=CREAM, anchor="lm")
    return y + 106


def grid_table(base, d, top, headers, widths, rows, row_h=92, header_h=84):
    """
    数据表页。rows: [(单元格..., kind)]，kind in none | hot | total
    首列左对齐、末列右对齐加粗、中间列居中；值为 0 / — 显示浅灰棕。
    行高与溢出：内容区可用高度约 960px（y 480→1440）。
      总高 = header_h + 行数 × row_h；≤8 行用 row_h 96，9-11 行压到 74，>11 行拆表。
    每行必须带 kind 字段——漏传会让最后一列静默不画（踩过）。
    """
    x0 = 72
    x1 = x0 + sum(widths)
    d.rounded_rectangle((x0, top, x1, top + header_h), radius=18, fill=DARK)
    d.rectangle((x0, top + header_h - 24, x1, top + header_h), fill=DARK)
    cx = x0
    for i, htxt in enumerate(headers):
        d.text((cx + widths[i] / 2, top + header_h / 2), htxt, font=F(24, True),
               fill=CREAM, anchor="mm")
        cx += widths[i]
    for r, row in enumerate(rows):
        kind, vals = row[-1], row[:-1]
        ry = top + header_h + r * row_h
        bg = PALE if kind == "total" else (ALT if r % 2 else WHITE)
        d.rectangle((x0, ry, x1, ry + row_h), fill=bg)
        d.line([(x0, ry), (x1, ry)], fill=LINE, width=2)
        cx = x0
        for i, v in enumerate(vals):
            if i == 0:
                d.text((cx + 22, ry + row_h / 2), v,
                       font=F(25, True if kind == "total" else False),
                       fill=(DARK if kind == "total" else INK), anchor="lm")
            elif i == len(vals) - 1:
                col = ORANGE if kind == "hot" else (DARK if kind == "total" else INK)
                d.text((cx + widths[i] - 22, ry + row_h / 2), v, font=F(30, True),
                       fill=col, anchor="rm")
            elif str(v) in ("0", "—"):
                d.text((cx + widths[i] / 2, ry + row_h / 2), v, font=F(26, False),
                       fill=MUTE, anchor="mm")
            else:
                d.text((cx + widths[i] / 2, ry + row_h / 2), v, font=F(26, False),
                       fill=(140, 124, 105, 255), anchor="mm")
            cx += widths[i]
    endy = top + header_h + len(rows) * row_h
    d.line([(x0, endy), (x1, endy)], fill=LINE, width=2)
    return endy


def table_page(idx, total, tag, title, sub, banner_text, headers, widths, rows, note=None):
    base = new_bg()
    d = ImageDraw.Draw(base)
    page_no(d, idx, total)
    y = header(d, tag, title, sub)
    top = banner(d, y, banner_text)
    end = grid_table(base, d, top, headers, widths, rows)
    if note:
        para(d, note, F(24, False), INK2, 72, end + 28, 900, lh=38)
    base.convert("RGB").save(os.path.join(OUT, "%02d_%s.png" % (idx, title)), quality=95)


def rows_card(idx, total, tag, title, sub, banner_text, rows):
    """列表页：banner 为顶部深色条，rows=[(名称, 数值pill, 说明, 是否重点), ...]"""
    base = new_bg()
    d = ImageDraw.Draw(base)
    page_no(d, idx, total)
    y = header(d, tag, title, sub)
    d.rounded_rectangle((72, y - 4, 1008, y + 76), radius=24, fill=DARK)
    d.text((120, y + 34), banner_text, font=F(30, True), fill=CREAM, anchor="lm")
    y += 106
    rh = 132
    for i, (name, cnt, ref, hot) in enumerate(rows):
        ry = y + i * rh
        if i:
            d.line([(104, ry), (976, ry)], fill=LINE, width=2)
        d.text((104, ry + 30), name, font=F(32, True), fill=DARK)
        pf = F(25, True)
        pw = pf.getlength(cnt) + 40
        d.rounded_rectangle((976 - pw, ry + 26, 976, ry + 74), radius=24,
                            fill=(ORANGE if hot else PALE))
        d.text((976 - pw / 2, ry + 50), cnt, font=pf,
               fill=(WHITE if hot else DARK), anchor="mm")
        d.text((104, ry + 86), ref, font=F(24, False), fill=INK2)
    base.convert("RGB").save(os.path.join(OUT, "%02d_%s.png" % (idx, title)), quality=95)


def cover(tag, lead, title1, title2, accent, sub1, sub2, stats,
          issue="NO.01 / 备考手册", note="个人整理 · 仅供参考"):
    """
    杂志刊头式封面（奶油底，不用渐变/光晕）
    stats: [(数字, 单位, 说明), ...] 写 3 个
    accent: title2 里要染成橙色的关键词
    """
    base = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(base)
    d.rectangle((0, 0, W, 14), fill=DARK)

    # 刊头条
    pill(d, 84, 110, tag, F(26, True), CREAM, DARK, padx=22, padh=13)
    d.text((996, 112), issue, font=F(24, False), fill=INK2, anchor="rm")
    d.line([(84, 196), (996, 196)], fill=LINE, width=2)

    # 引题 + 主标题
    d.text((84, 250), lead, font=F(64, True), fill=GOLD)
    d.text((84, 336), title1, font=F(124, True), fill=DARK)
    text_mixed(d, 84, 452, title2, F(124, True), DARK, accent, ORANGE)

    # 橙色短条 + 副标题
    d.rounded_rectangle((84, 640, 300, 648), radius=4, fill=ORANGE)
    para(d, sub1, F(40, True), INK, 84, 690, 900, lh=56)
    para(d, sub2, F(28, False), INK2, 84, 756, 900, lh=44)

    # 底部整块深棕墨数据卡（杂志感来自整块底色，不是三张小卡）
    box = (72, 880, 1008, 1200)
    shadow(base, box, r=36, alpha=48)
    d.rounded_rectangle(box, radius=36, fill=DARK)
    cw = (1008 - 72) / 3.0
    for i, (num, unit, label) in enumerate(stats):
        cx0 = 72 + i * cw
        cm = cx0 + cw / 2
        if i:
            d.line([(cx0, 928), (cx0, 1152)], fill=(74, 58, 42, 255), width=2)
        fn = F(72, True)
        nw = fn.getlength(num)
        tw = nw + (8 + F(26, True).getlength(unit) if unit else 0)
        sx = cm - tw / 2
        d.text((sx, 976), num, font=fn, fill=GOLD, anchor="lm")
        if unit:
            d.text((sx + nw + 8, 986), unit, font=F(26, True), fill=CREAM, anchor="lm")
        d.text((cm, 1060), label, font=F(24, False), fill=ON_DARK, anchor="mm")

    # 页脚
    d.text((84, 1266), note, font=F(26, False), fill=INK2)
    pf = F(26, True)
    pw = pf.getlength("建议收藏") + 44          # pill 的第一个参数是左边缘，右对齐要自己算
    pill(d, W - 84 - pw, 1266, "建议收藏", pf, WHITE, ORANGE, padx=22, padh=12)
    d.ellipse((84, 1300, 108, 1324), outline=ORANGE, width=4)   # 纯几何装饰
    base.convert("RGB").save(os.path.join(OUT, "01_封面.png"), quality=95)


if __name__ == "__main__":
    cover("2027 广东省考 · 提前看", "一文读懂",
          "公安专业", "科目考情全拆解", "全拆解",
          "考什么 · 考多少题 · 重点在哪",
          "卷子结构变了，别再按老思路复习",
          [("40", "题", "公安专业部分"), ("40", "分", "并入申论卷"),
           ("5", "大模块", "考点分布")])

    rows_card(2, 8, "模块 02", "法律基础知识及执法依据", "每年 20-30 题，是绝对大头",
              "题型：单选题 + 多选题 + 情景题（占分最高）",
              [("中国特色社会主义法治理论", "约 2 题", "习近平法治思想及有关法治的讲话", False),
               ("法学基础知识", "约 1 题", "法理学（近两年未考查）", True),
               ("宪法基础知识", "约 2 题", "宪法和宪法相关法", False)])

    table_page(3, 8, "逐年数据", "逐年题量总表（模块维度）", "2020-2026 每个模块到底考了几题",
               "单位：题 ｜ 2020-2023 单独成卷，2024 起并入申论卷",
               ["模块", "2020", "2021", "2022", "2023", "2024", "2025", "2026"],
               [280, 94, 94, 94, 94, 94, 94, 92],
               [("职业素养", "3", "9", "10", "5", "6", "4", "2", "none"),
                ("法律基础知识", "68", "61", "61", "66", "23", "21", "30", "hot"),
                ("公安基础知识", "10", "10", "7", "7", "0", "0", "0", "none"),
                ("基本能力", "11", "18", "15", "14", "11", "15", "7", "none"),
                ("警务技能", "8", "2", "3", "8", "0", "0", "0", "none"),
                ("合计", "100", "100", "96", "100", "40", "40", "39", "total")],
               note="原表标注：2022 年缺 4 题，2026 年缺 1 题。")
    print("done ->", OUT)
