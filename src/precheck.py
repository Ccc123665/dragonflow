"""发布前体检：在点「一键填充」之前，把能自动查的问题一次查完。

和 compliance.py 的分工
  · compliance.py —— 词库匹配：广告法极限词、行业敏感词（内容是否合规）
  · precheck.py   —— 字段规则：长度、必填、话题数量、站外引流、排版（能不能发出去）

规则来自 assets/platforms.json 的 rules 字段，数值是经验参考值，
各平台规则会变，改 JSON 即可，不用动代码。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import platforms as PF

LEVELS = {"err": 3, "warn": 2, "info": 1}

_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_MULTI_PUNCT = re.compile(r"([，。！？；：、,.!?;:])\1{2,}")
_LONG_PARA = 180            # 单段超过这么多字就算「大段文字」
_TOPIC_SEPS = re.compile(r"[\s,，、#]+")


@dataclass
class Issue:
    level: str          # err | warn | info
    field: str
    message: str
    hint: str = ""

    @property
    def icon(self) -> str:
        return {"err": "✕", "warn": "!", "info": "i"}.get(self.level, "i")


# ---------------------------------------------------------------- 工具
def rules_of(platform_key: str) -> Dict[str, Any]:
    pf = PF.get(platform_key) or {}
    r = pf.get("rules")
    return r if isinstance(r, dict) else {}


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v)
    return str(v)


def _count(value: Any) -> int:
    """标签类字段按「个数」算，其余按字符数算。"""
    if isinstance(value, (list, tuple)):
        return len([x for x in value if str(x).strip()])
    s = _as_text(value).strip()
    if not s:
        return 0
    return len([x for x in _TOPIC_SEPS.split(s) if x.strip()])


def _len_of(value: Any) -> int:
    return len(_as_text(value).strip())


# ---------------------------------------------------------------- 主逻辑
def check(platform_key: str, content: Dict[str, Any],
          skill: Optional[Dict[str, Any]] = None,
          artifacts: Optional[List[str]] = None) -> List[Issue]:
    """对一个平台的一份内容做体检，返回问题清单（按严重程度排序）。"""
    out: List[Issue] = []
    rules = rules_of(platform_key)
    content = content or {}
    fields = list((skill or {}).get("fields") or content.keys())

    # ---- 1. 必填：模板声明的字段不能全空
    filled = [f for f in fields if _as_text(content.get(f)).strip()]
    if not filled:
        out.append(Issue("err", "", "这份内容还是空的", "先点「生成内容」或手动填一下"))
        return out
    for f in fields:
        if not _as_text(content.get(f)).strip():
            level = "err" if f in ("title", "body") else "warn"
            out.append(Issue(level, f, f"{PF.name_of(platform_key)}的「{_label(f, rules)}」是空的",
                             "空字段会填充失败，建议补上"))

    # ---- 2. 长度
    for f, rule in rules.items():
        if f in ("ban_phrases", "ban_links") or not isinstance(rule, dict):
            continue
        val = content.get(f)
        if val is None:
            continue
        text = _as_text(val).strip()
        if not text:
            continue
        if f in ("topics", "images"):
            n = _count(val) if f == "topics" else len(artifacts or [])
            if n == 0 and f == "images":
                continue
        else:
            n = _len_of(val)
        label = rule.get("label") or _label(f, rules)
        hi, lo = rule.get("max"), rule.get("min")
        if hi and n > hi:
            out.append(Issue("err", f, f"{label} {n} 字，超过 {hi} 字上限（超了会被截断）",
                             _trim_hint(text, hi)))
        elif lo and n < lo:
            out.append(Issue("warn", f, f"{label}只有 {n} 字，建议不少于 {lo} 字",
                             "太短容易被判定为低质量内容"))

    # ---- 3. 站外引流
    for phrase in (rules.get("ban_phrases") or []):
        for f in fields:
            text = _as_text(content.get(f))
            if phrase and phrase in text:
                out.append(Issue("warn", f,
                                 f"{PF.name_of(platform_key)}不建议出现「{phrase}」",
                                 "站外引流词容易被限流，建议改写成平台内说法"))
                break
    if rules.get("ban_links"):
        for f in fields:
            m = _URL.search(_as_text(content.get(f)))
            if m:
                out.append(Issue("warn", f, f"{_label(f, rules)}里有外链：{m.group(0)[:40]}",
                                 "多数平台会对外链限流，建议去掉"))
                break

    # ---- 4. 排版
    body = _as_text(content.get("body"))
    if body:
        if _MULTI_PUNCT.search(body):
            out.append(Issue("info", "body", "正文里有连续重复的标点",
                             "看起来像手滑，建议清理"))
        longest = max((len(p) for p in re.split(r"\n+", body)), default=0)
        if longest > _LONG_PARA:
            out.append(Issue("info", "body",
                             f"有一整段 {longest} 字没有换行",
                             "移动端阅读建议每段控制在 3 行以内"))

    # ---- 5. 话题标签
    topics = content.get("topics")
    if topics:
        items = ([str(x) for x in topics] if isinstance(topics, (list, tuple))
                 else [x for x in _TOPIC_SEPS.split(_as_text(topics)) if x.strip()])
        dup = {x for x in items if items.count(x) > 1}
        if dup:
            out.append(Issue("info", "topics",
                             "话题标签有重复：" + "、".join(list(dup)[:5]),
                             "去重后更干净"))
        bad = [x for x in items if x.startswith("#")]
        if bad:
            out.append(Issue("info", "topics",
                             "标签里带了 # 号：" + "、".join(bad[:3]),
                             "多数平台会自动加 #，填纯文字即可"))

    # ---- 6. 图片 / 视频产出
    if artifacts:
        n = len(artifacts)
        rule = rules.get("images") or {}
        hi = rule.get("max")
        if hi and n > hi:
            out.append(Issue("warn", "images",
                             f"产出 {n} 张图，超过 {PF.name_of(platform_key)}的 {hi} 张上限",
                             "建议拆成多条发布"))
    out.sort(key=lambda i: -LEVELS.get(i.level, 0))
    return out


def _label(field: str, rules: Dict[str, Any]) -> str:
    import skills as SK
    rule = rules.get(field)
    if isinstance(rule, dict) and rule.get("label"):
        return rule["label"]
    return SK.field_label(field)


def _trim_hint(text: str, limit: int) -> str:
    if len(text) <= limit:
        return ""
    return "建议砍掉：" + text[limit:limit + 30].replace("\n", " ") + "…"


# ---------------------------------------------------------------- 汇总
def summarize(issues: List[Issue]) -> Tuple[int, int, int]:
    e = sum(1 for i in issues if i.level == "err")
    w = sum(1 for i in issues if i.level == "warn")
    n = sum(1 for i in issues if i.level == "info")
    return e, w, n


def worst_level(issues: List[Issue]) -> str:
    if not issues:
        return "ok"
    e, w, _ = summarize(issues)
    if e:
        return "err"
    if w:
        return "warn"
    return "info"


def one_line(issues: List[Issue]) -> str:
    """给状态条用的一句话结论。"""
    if not issues:
        return "体检通过"
    e, w, n = summarize(issues)
    bits = []
    if e:
        bits.append(f"{e} 项必改")
    if w:
        bits.append(f"{w} 项建议改")
    if n:
        bits.append(f"{n} 项可优化")
    return "、".join(bits)


def format_text(issues: List[Issue], platform_key: str = "") -> str:
    if not issues:
        return f"{PF.name_of(platform_key)}：没有发现需要处理的问题。" if platform_key \
            else "没有发现需要处理的问题。"
    head = {"err": "【必改】", "warn": "【建议改】", "info": "【可优化】"}
    lines = []
    for lv in ("err", "warn", "info"):
        group = [i for i in issues if i.level == lv]
        if not group:
            continue
        lines.append(head[lv])
        for i in group:
            lines.append(f"  · {i.message}" + (f"　→ {i.hint}" if i.hint else ""))
    return "\n".join(lines)
