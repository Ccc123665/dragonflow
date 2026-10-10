# -*- coding: utf-8 -*-
"""Pipeline：公众号文章链接 → 小红书 3:4 干货图文（8 张图 + 可直接发布的文案）。

流程
  1. 抓原文：请求 mp.weixin.qq.com 页面，取出标题 / 公众号名 / 发布时间 / 正文 / 配图地址
  2. 让模型读原文，产出「8 页大纲 + 小红书文案」的结构化 JSON
  3. 用 kit_draw 逐页出图（1080×1440），落地到 output/gzh_to_xhs/<标题>/
  4. 文案回填到卡片，图片路径写进 image_hint，后续可直接进发布工作台

抓不到正文时（公众号有反爬，部分链接会返回「请在微信客户端打开」），
让用户直接把正文粘到第二个输入框即可，流程照常跑。
"""
from __future__ import annotations

import html as _html
import io
import json
import os
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from .base import Ctx, Input, Pipeline, register
from . import kit_draw as K

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

_BLOCK_END = {"p", "div", "section", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
              "tr", "blockquote", "figure"}
_DROP = {"script", "style", "noscript", "svg", "iframe"}


# ================================================================ 抓原文
_DIV_OPEN = re.compile(r"<div\b", re.I)
_DIV_CLOSE = re.compile(r"</div\s*>", re.I)

_CONTENT_SELECTORS = (
    r'<div[^>]*\bid\s*=\s*["\']js_content["\'][^>]*>',
    r'<div[^>]*\bclass\s*=\s*["\'][^"\']*\brich_media_content\b[^"\']*["\'][^>]*>',
)


def _extract_content_html(page: str) -> str:
    """从整页 HTML 里切出正文容器的内部 HTML（按 <div> 配对计数找收尾）。

    为什么不能整块正则：公众号的正文容器长这样 ——

        <div class="rich_media_content js_underline_content
                           autoTypeSetting24psection
                "
                id="js_content" style="visibility: hidden; opacity: 0; ">

    class 属性值里带换行，前面还套着十几个空 div，属性顺序也不固定。
    所以先定位起始标签，再数 <div>/</div> 找到配对的收尾。
    """
    m = None
    for pat in _CONTENT_SELECTORS:
        m = re.search(pat, page, re.I)
        if m:
            break
    if not m:
        return ""

    start = m.end()
    depth, i, end = 1, start, len(page)
    while depth > 0:
        nxt_open = _DIV_OPEN.search(page, i)
        nxt_close = _DIV_CLOSE.search(page, i)
        if nxt_close is None:                      # HTML 被截断，能拿多少拿多少
            end = len(page)
            break
        if nxt_open is not None and nxt_open.start() < nxt_close.start():
            depth += 1
            i = nxt_open.end()
        else:
            depth -= 1
            if depth == 0:
                end = nxt_close.start()
                break
            i = nxt_close.end()
    return page[start:end]


class _ContentParser(HTMLParser):
    """解析正文**片段**：块级标签当换行，收集图片地址，丢掉脚本样式。

    注意这里**不做深度计数**。老版本用「进入容器时的 depth」和「闭合时的 depth」
    比较来判断正文是否结束，但 HTMLParser 对 `<img ... />` 这类自闭合标签会依次调
    `handle_starttag` + `handle_endtag` —— 前者对 img 提前 return（不加深度），
    后者却老老实实把深度减 1。公众号正文里全是自闭合 `<img />`，深度被扣到 0，
    于是正文刚开始就被判定「已结束」，整篇文章只剩十几个换行符。
    现在改成先把正文片段切出来（见 _extract_content_html），再整体当正文解析。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.images: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "img":
            src = a.get("data-src") or a.get("src") or ""
            if src.startswith("http") and src not in self.images:
                self.images.append(src)
            return
        if tag in _DROP:
            self._skip += 1
            return
        if tag in _BLOCK_END:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        # 自闭合标签只算一次 starttag，绝不能再补一次 endtag（会重复扣 _skip）
        self.handle_starttag(tag, attrs)
        if tag in _DROP:
            self._skip = max(0, self._skip - 1)

    def handle_endtag(self, tag):
        if tag in _DROP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _BLOCK_END:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)

    # -- 结果 --
    def text(self) -> str:
        raw = "".join(self.parts)
        raw = raw.replace("\u200b", "").replace("\xa0", " ")
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.split("\n")]
        out: List[str] = []
        for ln in lines:
            if ln:
                out.append(ln)
            elif out and out[-1] != "":
                out.append("")
        return "\n".join(out).strip()


def _extract_meta(html: str, key: str) -> str:
    m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']*)'
                  % re.escape(key), html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']%s["\']'
                      % re.escape(key), html, re.I)
    return _html.unescape(m.group(1)).strip() if m else ""


# 页面特征 → 人话解释（按「先具体后笼统」的顺序匹配）
_DEAD_HINTS = (
    ("该内容已被发布者删除", "这篇文章已被作者删除。"),
    ("此内容因违规无法查看", "这篇文章因违规被下架，看不到了。"),
    ("该内容已被发布者删除或删除", "这篇文章已被作者删除。"),
    ("此账号已被屏蔽", "这个公众号已被屏蔽，文章无法访问。"),
    ("该公众号已迁移", "这个公众号已迁移，旧链接失效。"),
    ("系统繁忙，请稍后再试", "微信侧提示「系统繁忙」，稍等一会儿再试。"),
)

_MANUAL_HINT = "把正文直接粘到上面的「手动粘贴正文」框里，流程照样能跑完。"


def _diagnose(page: str) -> str:
    """抓不到正文时，按页面特征给出**能直接照做**的原因说明。"""
    if "参数错误" in page:
        return ("微信返回「参数错误」—— 这个地址不是有效的文章链接（多半是复制时被截断、"
                "或者链接已失效）。请在文章页右上角「…」→「复制链接」，重新取一次完整链接；"
                + _MANUAL_HINT)
    if "环境异常" in page or "去验证" in page:
        return ("公众号返回了「环境异常」验证页（短时间请求太多会被拦）。"
                "等几分钟再试，或者" + _MANUAL_HINT)
    for kw, msg in _DEAD_HINTS:
        if kw in page:
            return msg + _MANUAL_HINT
    if "请在微信客户端打开" in page or "weui-msg" in page:
        return ("这个链接要求在微信里打开（浏览器直开会被挡）。" + _MANUAL_HINT)
    return ("没能在页面里找到正文区域 —— 可能是链接不完整、文章已删除，"
            "或者公众号改了页面结构。" + _MANUAL_HINT)


def fetch_article(url: str, ctx: Optional[Ctx] = None) -> Dict[str, Any]:
    """抓一篇公众号文章，返回 {title, author, published_at, text, images}。"""
    import requests
    log = (ctx.log if ctx else (lambda _m: None))
    url = (url or "").strip()
    if not url:
        raise ValueError("没有填文章链接")
    if not url.startswith("http"):
        url = "https://" + url

    log(f"正在抓取：{url[:70]}…")
    resp = requests.get(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://mp.weixin.qq.com/",
    }, timeout=30)
    resp.encoding = resp.apparent_encoding or "utf-8"
    page = resp.text

    title = (_extract_meta(page, "og:title") or "").strip()
    title = re.sub(r"\s+", " ", title)[:80]
    author = ""
    m = re.search(r'id="js_name"[^>]*>(.*?)<', page, re.S)
    if m:
        author = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    if not author:
        author = _extract_meta(page, "og:description")[:30]

    published = ""
    m = re.search(r'var\s+ct\s*=\s*"(\d{9,11})"', page)
    if m:
        import datetime
        try:
            published = datetime.datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d")
        except Exception:
            published = ""
    if not published:
        m = re.search(r'id="publish_time"[^>]*>([^<]*)<', page)
        if m:
            published = m.group(1).strip()

    # ---- 正文：先切出容器，再整体解析 ----
    frag = _extract_content_html(page)
    if not frag:
        raise ValueError(_diagnose(page))

    p = _ContentParser()
    try:
        p.feed(frag)
    except Exception:
        pass

    text = p.text()
    if len(text) < 80:
        # 图文型文章：正文只有几行字，干货全在图里
        if p.images:
            raise ValueError(
                f"这篇文章的正文只有 {len(text)} 字，但有 {len(p.images)} 张配图 —— "
                "属于「内容全在图片里」的类型，纯文字抓取拿不到干货。"
                + _MANUAL_HINT)
        raise ValueError("正文区域是空的，可能是链接不完整或文章已被清空。" + _MANUAL_HINT)

    if len(text) < 300 and len(p.images) >= 2:
        log(f"注意：正文只有 {len(text)} 字但有 {len(p.images)} 张配图，"
            "关键数据可能藏在图里，产出内容可能偏薄")

    log(f"抓取成功：{len(text)} 字，{len(p.images)} 张原文配图")
    return {"title": title, "author": author, "published_at": published,
            "text": text, "images": p.images[:12], "url": url}


def _fetch_bytes(url: str, timeout: int = 25):
    """下一张配图的字节。失败返回 None（配图挂了不该拖垮整条流水线）。"""
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://mp.weixin.qq.com/"},
                         timeout=timeout)
        if r.status_code == 200 and len(r.content) > 4096:
            return r.content
    except Exception:
        pass
    return None


def _informative(data: bytes) -> bool:
    """值不值得送模型读：logo / 分割线 / 表情包一律跳过。

    公众号文章的干货图（题量统计表、竞争比排行、岗位表）都是大图，
    按尺寸 + 体积筛一遍能省掉一大半无效请求。
    """
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        w, h = im.size
    except Exception:
        return False
    return w >= 500 and h >= 200 and len(data) >= 12000


VISION_SYSTEM = (
    "你是资料整理员。用户给你的是公众号文章的配图，你要把图里的文字和数据**原样抄下来**。"
    "只输出图里真实存在的内容，一个字都不许概括、不许推测、不许补全、不许换算。"
    "看不清的字用「?」占位，不要凭上下文猜。"
)

VISION_PROMPT = """这是《{title}》的第 {i}/{n} 张配图。

把图里的文字和数据原样抄出来，要求：
1. 数字、比例、日期、分数线、岗位名、专业名、人数 —— 一个都不许改，不许四舍五入
2. 表格逐行输出，写成「项目 | 数值」的形式
3. 不要写「这张图展示了…」这类废话，直接给内容
4. 如果这张图没有任何文字信息（纯装饰图、logo、分割线），只回四个字：无文字信息"""


def read_article_images(urls: List[str], title: str, ctx: Ctx,
                        *, limit: int = 12, workers: int = 3) -> str:
    """下载并逐张读原文配图，返回拼好的文字（读不到就返回空串）。

    为什么必须做这一步：公众号的核心数据经常**只存在于图片里**
    （题量统计表、竞争比排行、岗位表）。纯文字抓取会整批漏掉，
    产出的图文看着像模像样，其实最关键的数字全没了。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    ctx.check()
    ctx.progress(0.08, "下载原文配图")
    got = [(u, _fetch_bytes(u)) for u in urls[: limit * 2]]
    got = [(u, b) for u, b in got if b]
    useful = [(u, b) for u, b in got if _informative(b)][:limit]

    if not useful:
        ctx.log(f"原文配图 {len(got)} 张，没有值得读的图表（都是小图 / 装饰图）")
        return ""

    ctx.log(f"原文配图 {len(got)} 张，其中 {len(useful)} 张含图表，开始逐张读取…")

    results: List[str] = [""] * len(useful)
    errors: List[str] = []
    done = 0

    def one(i: int, data: bytes) -> str:
        return ctx.llm_vision(
            VISION_SYSTEM,
            VISION_PROMPT.format(title=title or "（无标题）", i=i + 1, n=len(useful)),
            [data], max_tokens=2000, temperature=0.1)

    ex = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futs = {ex.submit(one, i, b): i for i, (_u, b) in enumerate(useful)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = (fut.result() or "").strip()
            except Exception as e:
                errors.append(f"第 {i + 1} 张：{str(e)[:70]}")
            done += 1
            ctx.progress(0.08 + 0.17 * done / len(useful), f"读配图 {done}/{len(useful)}")
            if ctx.stopped():
                break
    finally:
        ex.shutdown(wait=False)

    if errors:
        ctx.log("有配图没读成功（已跳过）：" + "；".join(errors[:3]))

    chunks: List[str] = []
    for i, t in enumerate(results):
        if not t or "无文字信息" in t[:20]:
            continue
        chunks.append(f"— 配图 {i + 1} —\n{t}")
    if not chunks:
        ctx.log("配图里没读到可用文字")
        return ""

    ctx.log(f"配图读取完成：{len(chunks)} 张有内容，共 {sum(len(c) for c in chunks)} 字")
    return "\n\n".join(chunks)


# ================================================================ 大纲生成
SYSTEM = (
    "你是一位小红书教育/考公考编赛道的图文编辑，擅长把一篇长文章拆成 7-9 张竖版干货图。"
    "你只输出 JSON，不要任何解释文字。你的文案绝不使用「包过」「保过」「押题」「最」「第一」"
    "「100%」等违规承诺词与广告法极限词，也不承诺任何考试结果。"
)

PROMPT = """把下面这篇文章改造成一篇小红书图文笔记。

【原文标题】{title}
【原文正文】
{body}

【补充要求】{extra}

注意：正文里如果出现「【原文配图里的内容】」这一段，说明它是从配图里抄录出来的表格数据，
**这些数字往往是全篇最硬的干货，优先级高于正文描述**。用它们时：
- 数字必须原样引用，不许换算、不许四舍五入、不许四舍五入后取整
- 看不清的地方标了「?」，那就整条不要用，别猜
- 优先把「竞争比 / 招录人数 / 分数线 / 岗位名」这类数字放进封面和表格页

请输出一个 JSON 对象，结构如下（不要加注释，不要用 markdown 代码块以外的文字）：

{{
  "title": "小红书标题，不超过 20 字，带钩子但不夸张",
  "body": "正文，500-900 字，短句分段，用 3-4 个 emoji 小标题，口语化，结尾一句互动引导",
  "topics": "6-10 个话题标签，空格分隔，不带 # 号",
  "cover": "封面文案，不超过 12 字",
  "image_hint": "一句话说明这组图的整体风格",
  "pages": [ ... 共 {pages} 页 ... ]
}}

pages 里每一项必须从下面 7 种里选一种，并严格按其字段填：

1) 封面（必须且只能是第 1 页，type=cover）
   {{"type":"cover","tag":"左上角小标签≤8字","title_small":"小标题≤10字",
     "title_big":["大标题第一行≤7字","大标题第二行≤7字"],
     "accent":"大标题第二行里要染成强调色的关键词，必须是第二行的连续子串、2-4字，没有就传空字符串",
     "sub1":"副标题≤18字","sub2":"补充说明≤22字",
     "stats":[["数字","单位","说明≤6字"],["数字","单位","说明≤6字"],["数字","单位","说明≤6字"]]}}
   stats 最多 3 组，必须是原文里真实出现的数字；原文没有数字就传 []。

2) 列表页 {{"type":"rows","tag":"≤8字","title":"≤12字","sub":"≤20字","banner":"顶部说明条≤28字",
   "rows":[["名称≤16字","数值胶囊≤6字","说明≤22字",false]]}}
   rows 3-6 条，第四项是布尔值，true 表示这行是重点（会用橙色高亮）。

3) 表格页 {{"type":"table","tag":"≤8字","title":"≤12字","sub":"≤20字","banner":"单位说明≤28字",
   "headers":["列名"],"rows":[["第一列","第二列","…","none"]]}}
   headers 2-7 列；rows 每行最后一项是 "none" | "hot" | "total"（合计行用 total）。

4) 要点页 {{"type":"bullets","tag":"≤8字","title":"≤12字","sub":"≤20字","banner":"≤28字",
   "items":[["要点标题≤14字","补充说明≤30字"]]}} items 3-6 条。

5) 金句页 {{"type":"quote","tag":"≤8字","title":"≤12字","quote":"≤60字的金句","source":"出处≤10字"}}

6) 段落页 {{"type":"text","tag":"≤8字","title":"≤12字","sub":"≤20字",
   "paras":["段落1 ≤90字","段落2 ≤90字"]}} paras 最多 4 段。

7) 收尾页（必须是最后一页，type=end）
   {{"type":"end","title":"≤10字","lines":["要点≤16字"],"cta":"行动号召≤16字"}}

硬性要求：
- pages 数量正好 {pages} 页，第 1 页 cover、最后一页 end，中间至少 2 页是 rows / table（有数据的页更好）。
- 所有数字、名称、结论必须来自原文，不许编造。
- 每页文字都按上面的字数上限来，超了会被裁掉。
- 全文简体中文。
"""


def _clip(v: Any, n: int, default: str = "") -> str:
    s = str(v if v is not None else default).strip()
    return s[:n]


def _as_list(v: Any) -> List[Any]:
    return list(v) if isinstance(v, (list, tuple)) else []


# ================================================================ 出图
def render_pages(pages: List[dict], out_dir: str, ctx: Ctx,
                 deck_cls=None) -> List[str]:
    """逐页出图。deck_cls 为画布类（None = kit_draw.Deck 深蓝风），
    子类流水线可以换肤（如 gzh_to_xhs_magazine 的暖橙杂志风）。"""
    total = max(1, len(pages))
    deck = (deck_cls or K.Deck)(out_dir, total=total)
    made: List[str] = []
    for i, pg in enumerate(pages, start=1):
        ctx.check()
        t = str((pg or {}).get("type") or "").strip().lower()
        pg = pg or {}
        try:
            if t == "cover":
                path = deck.cover(
                    tag=_clip(pg.get("tag"), 18),
                    title_small=_clip(pg.get("title_small"), 12),
                    title_big=[_clip(x, 8) for x in _as_list(pg.get("title_big"))[:2]] or ["　"],
                    accent=_clip(pg.get("accent"), 6),
                    sub1=_clip(pg.get("sub1"), 24),
                    sub2=_clip(pg.get("sub2"), 30),
                    stats=[(_clip(s[0], 6), _clip(s[1], 4), _clip(s[2], 8))
                           for s in _as_list(pg.get("stats"))[:3] if _as_list(s)],
                )
            elif t == "table":
                headers = [_clip(h, 10) for h in _as_list(pg.get("headers"))[:7]]
                rows = [list(r) for r in _as_list(pg.get("rows"))[:12]]
                widths = _auto_widths(headers)
                rows = [_pad_row(r, len(headers)) for r in rows]
                path = deck.table_page(
                    i, tag=_clip(pg.get("tag"), 10), title=_clip(pg.get("title"), 14),
                    sub=_clip(pg.get("sub"), 22), banner=_clip(pg.get("banner"), 30),
                    headers=headers, widths=widths, rows=rows,
                    note=_clip(pg.get("note"), 60))
            elif t == "bullets":
                path = deck.bullets_page(
                    i, tag=_clip(pg.get("tag"), 10), title=_clip(pg.get("title"), 14),
                    sub=_clip(pg.get("sub"), 22), banner=_clip(pg.get("banner"), 30),
                    items=[(_clip(x[0], 16), _clip(x[1], 34))
                           for x in _as_list(pg.get("items"))[:6] if _as_list(x)])
            elif t == "quote":
                path = deck.quote_page(
                    i, tag=_clip(pg.get("tag"), 10), title=_clip(pg.get("title"), 14),
                    quote=_clip(pg.get("quote"), 70), source=_clip(pg.get("source"), 12))
            elif t == "text":
                path = deck.text_page(
                    i, tag=_clip(pg.get("tag"), 10), title=_clip(pg.get("title"), 14),
                    sub=_clip(pg.get("sub"), 22),
                    paras=[_clip(x, 100) for x in _as_list(pg.get("paras"))[:4]])
            elif t == "end":
                path = deck.end_page(
                    i, title=_clip(pg.get("title"), 12),
                    lines=[_clip(x, 18) for x in _as_list(pg.get("lines"))[:5]],
                    cta=_clip(pg.get("cta"), 18))
            else:                                   # rows 及未知类型兜底
                path = deck.rows_card(
                    i, tag=_clip(pg.get("tag"), 10), title=_clip(pg.get("title"), 14),
                    sub=_clip(pg.get("sub"), 22), banner=_clip(pg.get("banner"), 30),
                    rows=[(_clip(r[0], 18), _clip(r[1], 8), _clip(r[2], 24),
                           bool(r[3]) if len(r) > 3 else False)
                          for r in _as_list(pg.get("rows"))[:6] if _as_list(r)])
        except Exception as e:                      # 单页失败不拖垮整组
            ctx.log(f"第 {i} 页出图失败（{t}）：{e}")
            continue
        made.append(path)
        ctx.add(path)
        ctx.progress(0.55 + 0.4 * i / total, f"出图 {i}/{total}")
    return made


def _auto_widths(headers: List[str]) -> List[float]:
    """表格列宽：首列宽、末列窄，其余均分，总宽固定 936。"""
    n = len(headers) or 1
    total = 936.0
    if n == 1:
        return [total]
    if n == 2:
        return [total * 0.62, total * 0.38]
    first = 260.0
    last = 120.0
    mid = (total - first - last) / (n - 2)
    if mid < 70:
        first, last = 200.0, 90.0
        mid = (total - first - last) / (n - 2)
    return [first] + [mid] * (n - 2) + [last]


def _pad_row(row: List[Any], n: int) -> List[Any]:
    r = list(row)
    kind = "none"
    if r and str(r[-1]).lower() in ("none", "hot", "total"):
        kind = str(r.pop()).lower()
    r = [str(x) for x in r][:n]
    while len(r) < n:
        r.append("")
    return r + [kind]


# ================================================================ Pipeline
@register
class GzhToXhs(Pipeline):
    key = "gzh_to_xhs"
    name = "公众号链接转小红书图文"
    desc = "贴一个公众号文章链接，自动抓原文、生成文案并出 8 张 1080×1440 竖版配图"
    note = ("耗时约 60-150 秒（抓取 + 读配图 + 一次模型调用 + 逐张出图）。"
            "公众号有反爬，遇到「环境异常」改用「手动粘贴正文」；"
            "配图里常有表格数字，勾上「读原文配图」用视觉模型抽出来 —— "
            "需要当前模型能读图（deepseek-flash 可以，deepseek-v4-pro 不行）。")
    platform = "xhs"
    content_type = "图文"
    icon = "sparkle"
    fields = ["title", "body", "topics", "cover", "image_hint"]
    outputs = ["小红书文案", "8 张 1080×1440 竖版配图"]
    # 出图画布类。子类流水线可换肤（None = kit_draw.Deck 深蓝渐变风）
    deck_cls = None

    def inputs(self) -> List[Input]:
        return [
            Input("url", "公众号文章链接", "text", required=False,
                  placeholder="https://mp.weixin.qq.com/s/xxxxxxxx",
                  help="要从文章页「…」→「复制链接」取完整链接，别用手打或转发的短链"),
            Input("text", "手动粘贴正文", "textarea", required=False, rows=6,
                  placeholder="（可选）把文章正文整段粘进来，绕过抓取",
                  help="抓取失败时用这个 —— 正文里有数据表格的，建议连表格文字一起粘进来"),
            Input("read_images", "读原文配图（表格/数据图）", "switch", default="1",
                  help="用视觉模型把配图里的表格、竞争比、岗位表抄成文字，并入正文。"
                       "文章正文很短但配图很多时，这一步是干货的主要来源"),
            Input("pages", "出图页数", "choice", default="8",
                  choices=["6", "8", "10", "12"], required=False,
                  help="含封面和收尾页"),
            Input("extra", "补充要求", "textarea", required=False, rows=2,
                  placeholder="例如：面向在职备考的上班族，语气轻松一点"),
        ]

    def run(self, values: Dict[str, str], ctx: Ctx) -> Dict[str, Any]:
        url = (values.get("url") or "").strip()
        manual = (values.get("text") or "").strip()
        pages_n = int(values.get("pages") or 8)
        extra = (values.get("extra") or "").strip() or "无"
        want_images = bool(values.get("read_images"))

        ctx.progress(0.02, "准备中")
        if manual and len(manual) >= 60:
            art = {"title": (manual.splitlines()[0] or "")[:80] if manual else "",
                   "author": "", "published_at": "", "text": manual,
                   "images": [], "url": url}
            ctx.log("使用手动粘贴的正文")
        else:
            art = fetch_article(url, ctx)

        body = art["text"]

        # ---- 读配图：公众号的核心数据经常只在图里 ----
        if want_images and art.get("images"):
            if ctx.supports_vision():
                try:
                    shot_text = read_article_images(art["images"], art.get("title", ""), ctx)
                    if shot_text:
                        body = (body + "\n\n【原文配图里的内容（由视觉模型抄录，数字未做改动）】\n"
                                + shot_text)
                except InterruptedError:
                    raise
                except Exception as e:
                    ctx.log(f"读配图失败，改用纯文字继续：{str(e)[:80]}")
            else:
                ctx.log("当前模型不支持读图，已跳过配图 —— 换 deepseek-flash / "
                        "qwen-vl-max / glm-4v-plus 才能读图")
        elif want_images:
            ctx.log("原文没有可用配图")

        if len(body) > 12000:                       # 控制 token，掐头去尾留主干
            body = body[:8000] + "\n……（中略）……\n" + body[-3000:]

        ctx.progress(0.30, "生成图文大纲")
        raw = ctx.llm(SYSTEM, PROMPT.format(title=art.get("title") or "（无标题）",
                                            body=body, extra=extra, pages=pages_n),
                      max_tokens=8000, temperature=0.7)
        data = _json_of(raw)
        if not data:
            raise ValueError("模型没有返回可解析的 JSON，请重试或换一个模型")

        pages = _normalize_pages(data.get("pages"), pages_n)
        if not pages:
            raise ValueError("模型返回的大纲里没有可用页面")

        out_dir = self.output_dir(art.get("title") or "公众号图文")
        ctx.progress(0.5, f"开始出图（共 {len(pages)} 页）")
        made = render_pages(pages, out_dir, ctx, deck_cls=self.deck_cls)

        if values.get("_download_images") and art.get("images"):
            _download(art["images"], out_dir, ctx)

        hint = _clip(data.get("image_hint"), 200)
        ctx.progress(1.0, f"完成，共 {len(made)} 张图")
        ctx.log(f"图片已输出到 {out_dir}")
        return {
            "title": _clip(data.get("title"), 60) or art.get("title", "")[:60],
            "body": str(data.get("body") or "").strip(),
            "topics": _clip(data.get("topics"), 200),
            "cover": _clip(data.get("cover"), 30),
            "image_hint": (hint + f"\n已出图 {len(made)} 张，目录：{out_dir}").strip(),
            "_artifacts": made,
            "_out_dir": out_dir,
        }


def _json_of(raw: str) -> Optional[dict]:
    import llm
    obj = llm.extract_json(raw)
    if obj:
        return obj
    m = re.search(r"\{.*\}", raw or "", re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _normalize_pages(pages: Any, want: int) -> List[dict]:
    out = [p for p in _as_list(pages) if isinstance(p, dict)]
    if not out:
        return []
    if str(out[0].get("type", "")).lower() != "cover":
        out.insert(0, {"type": "cover", "tag": "", "title_small": "",
                       "title_big": ["内容拆解", ""], "sub1": "", "sub2": "", "stats": []})
    if str(out[-1].get("type", "")).lower() != "end":
        out.append({"type": "end", "title": "就到这里", "lines": [],
                    "cta": "收藏慢慢看"})
    return out[:max(3, want)]


def _download(urls: List[str], out_dir: str, ctx: Ctx) -> List[str]:
    import requests
    d = os.path.join(out_dir, "原文配图")
    os.makedirs(d, exist_ok=True)
    got: List[str] = []
    for i, u in enumerate(urls[:12], start=1):
        ctx.check()
        try:
            r = requests.get(u, headers={"User-Agent": UA, "Referer": "https://mp.weixin.qq.com/"},
                             timeout=20)
            if r.status_code != 200 or len(r.content) < 2048:
                continue
            ext = os.path.splitext(urllib.parse.urlparse(u).path)[1] or ".jpg"
            p = os.path.join(d, f"{i:02d}{ext}")
            with open(p, "wb") as f:
                f.write(r.content)
            got.append(p)
            ctx.add(p)
        except Exception:
            continue
    ctx.log(f"已下载原文配图 {len(got)} 张")
    return got
