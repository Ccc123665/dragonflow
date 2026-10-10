"""合规检测：三级违禁词库匹配。

定位是「辅助提醒 + 人工终审」，不承诺检测结果等同于平台审核通过。
"""
import json
import os
import re
from typing import Any, Dict, List, Tuple

import config
import store


def load_builtin() -> Dict[str, Any]:
    try:
        with open(config.FORBIDDEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"categories": [], "suggest": {}}


def load_user() -> Dict[str, Any]:
    if not os.path.exists(config.FORBIDDEN_USER_FILE):
        return {"extra": {}, "disabled": []}
    try:
        with open(config.FORBIDDEN_USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"extra": {}, "disabled": []}
    data.setdefault("extra", {})
    data.setdefault("disabled", [])
    return data


def save_user(data: Dict[str, Any]) -> None:
    store._write(config.FORBIDDEN_USER_FILE, data)


def all_categories() -> List[Dict[str, Any]]:
    """内置分类 + 用户追加的词 + 用户新增的分类，并剔除用户禁用/删掉的词。"""
    builtin = load_builtin()
    user = load_user()
    disabled = set(user.get("disabled", []))
    cats: List[Dict[str, Any]] = []
    for c in builtin.get("categories", []):
        c = dict(c)
        extra = user["extra"].get(c["key"], [])
        words = [w for w in c.get("words", []) if w not in disabled]
        c["words"] = list(dict.fromkeys(words + list(extra)))
        c["user_words"] = list(extra)
        cats.append(c)
    for key, val in user["extra"].items():
        if key in {c["key"] for c in cats}:
            continue
        cats.append({
            "key": key, "name": key, "level": "mid",
            "desc": "自定义词库",
            "words": [w for w in val if w not in disabled],
            "user_words": list(val),
        })
    return cats


def suggestions() -> Dict[str, str]:
    s = dict(load_builtin().get("suggest", {}))
    s.update(load_user().get("extra_suggest", {}) or {})
    return s


def add_words(cat_key: str, words: List[str]) -> None:
    user = load_user()
    cur = list(user["extra"].get(cat_key, []))
    for w in words:
        w = w.strip()
        if w and w not in cur:
            cur.append(w)
    user["extra"][cat_key] = cur
    save_user(user)
    store.log(f"词库新增 {len(words)} 词 → {cat_key}")


def remove_words(cat_key: str, words: List[str]) -> None:
    user = load_user()
    cur = list(user["extra"].get(cat_key, []))
    user["extra"][cat_key] = [w for w in cur if w not in words]
    save_user(user)


def add_category(key: str, name: str, words: List[str], level: str = "mid") -> None:
    user = load_user()
    user["extra"][key] = [w.strip() for w in words if w.strip()]
    save_user(user)


# ---------------------------------------------------------------- 检测
def check(text: str) -> List[Dict[str, Any]]:
    """返回命中列表：[{word, category, level, count, positions, suggest}]"""
    if not text:
        return []
    suggest = suggestions()
    hits: List[Dict[str, Any]] = []
    seen = set()
    for cat in all_categories():
        for w in cat.get("words", []):
            if not w or w in seen:
                continue
            if w in text:
                seen.add(w)
                hits.append({
                    "word": w,
                    "category": cat.get("name", ""),
                    "cat_key": cat.get("key", ""),
                    "level": cat.get("level", "mid"),
                    "count": text.count(w),
                    "suggest": suggest.get(w, ""),
                })
    order = {"high": 0, "mid": 1}
    hits.sort(key=lambda h: (order.get(h["level"], 2), -h["count"], -len(h["word"])))
    return hits


def check_content(content: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """按字段检测，返回 {字段名: [命中]}。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for k, v in (content or {}).items():
        if isinstance(v, str) and v:
            hits = check(v)
            if hits:
                out[k] = hits
    return out


def summarize(hits_by_field: Dict[str, List[Dict[str, Any]]]) -> Tuple[int, int]:
    """返回 (高风险数, 中风险数)。"""
    high = mid = 0
    for hits in hits_by_field.values():
        for h in hits:
            if h["level"] == "high":
                high += 1
            else:
                mid += 1
    return high, mid


def highlight_html(text: str, hits: List[Dict[str, Any]]) -> str:
    """把命中的词包成高亮 span，用于预览。"""
    if not text or not hits:
        return _escape(text or "")
    words = sorted({h["word"] for h in hits}, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(w) for w in words))
    level_map = {h["word"]: h["level"] for h in hits}
    out = []
    pos = 0
    for m in pattern.finditer(text):
        out.append(_escape(text[pos:m.start()]))
        lv = level_map.get(m.group(0), "mid")
        color = "#D9534F" if lv == "high" else "#D98A24"
        bg = "#FBECEB" if lv == "high" else "#FBF3E6"
        out.append(
            f'<span style="color:{color};background:{bg};border-radius:3px;'
            f'padding:0 2px;">{_escape(m.group(0))}</span>'
        )
        pos = m.end()
    out.append(_escape(text[pos:]))
    return "".join(out)


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace("\n", "<br>"))


def strip_words(text: str, hits: List[Dict[str, Any]], use_suggest: bool = True) -> str:
    """一键替换：优先用建议词，没有建议词就删掉。"""
    if not text or not hits:
        return text
    suggest = suggestions()
    for h in sorted(hits, key=lambda x: -len(x["word"])):
        w = h["word"]
        rep = suggest.get(w, "") if use_suggest else ""
        text = text.replace(w, rep)
    return text
