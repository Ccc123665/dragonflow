"""平台定义加载（内置 assets/platforms.json + 用户自定义）。

为什么要支持用户自定义平台：
  内置的 5 个平台是「开箱即用」的默认值，但每个人做的号不一样 ——
  有人做知乎、B站、百家号。硬编码在 assets 里改起来麻烦
  （打包后 assets 在 _internal 里，用户改不动），所以：
    · 内置平台：assets/platforms.json，只读，随程序走
    · 自定义平台：%APPDATA%/DragonFlow/platforms_user.json，可增删改

自定义平台没有适配脚本（adapters/xxx.js），发布时自动降级为
「复制到剪贴板 + 打开发布页」由人工粘贴 —— 这是既有兜底逻辑，不需要额外处理。
"""
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import config

_cache: Optional[List[Dict[str, Any]]] = None

# 自定义平台 key 前缀，用于区分内置 / 自定义
CUSTOM_PREFIX = "u_"

# 主题色候选（给自定义平台挑，不用用户填色值）
COLOR_CHOICES = [
    "#2C6BE8", "#E0443A", "#1C1C1E", "#2F9E68", "#3E9E4E",
    "#D9534F", "#7B5BD6", "#C97F1B", "#0FA3A3", "#5A6B7B",
]


# ---------------------------------------------------------------- 内置
def _load_builtin() -> List[Dict[str, Any]]:
    try:
        with open(config.PLATFORMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = []
        for p in data.get("platforms", []):
            p = dict(p)
            p["builtin"] = True
            out.append(p)
        return out
    except Exception:
        return []


# ---------------------------------------------------------------- 自定义
def load_custom() -> List[Dict[str, Any]]:
    if not os.path.exists(config.PLATFORMS_USER_FILE):
        return []
    try:
        with open(config.PLATFORMS_USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    out = []
    for p in data.get("platforms", []):
        if not isinstance(p, dict) or not p.get("key"):
            continue
        p = dict(p)
        p["builtin"] = False
        out.append(p)
    return out


def save_custom(items: List[Dict[str, Any]]) -> None:
    data = {"version": 1, "platforms": items}
    os.makedirs(os.path.dirname(config.PLATFORMS_USER_FILE), exist_ok=True)
    tmp = config.PLATFORMS_USER_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.PLATFORMS_USER_FILE)


def _slug(name: str) -> str:
    """把平台名转成可读的 key 片段（中文原样保留，只去掉危险字符）。"""
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", name or "").strip()
    return s[:12] or "platform"


def make_key(name: str) -> str:
    """生成唯一 key：u_<名字片段>_<短随机>。"""
    existing = {p["key"] for p in load_custom()}
    while True:
        key = f"{CUSTOM_PREFIX}{_slug(name)}_{uuid.uuid4().hex[:4]}"
        if key not in existing:
            return key


def add_custom(name: str, short: str = "", color: str = "",
               login_url: str = "", publish_url: str = "",
               home_url: str = "", content_types: Optional[List[str]] = None,
               draft_only: bool = False) -> Dict[str, Any]:
    """新增一个自定义平台，返回平台定义。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("平台名称不能为空")
    if not (publish_url or login_url or home_url).strip():
        raise ValueError("至少要填一个网址（建议填发布页）")
    for p in all_platforms():
        if p["name"] == name:
            raise ValueError(f"已经有一个叫「{name}」的平台了")

    item = {
        "key": make_key(name),
        "name": name,
        "short": (short or name[:1]).strip()[:2],
        "color": (color or COLOR_CHOICES[0]).strip(),
        "login_url": login_url.strip(),
        "home_url": (home_url or publish_url or login_url).strip(),
        "publish_url": (publish_url or login_url or home_url).strip(),
        "content_types": list(content_types or ["图文"]),
        "adapter": "",                 # 自定义平台没有适配脚本 → 走剪贴板兜底
        "submit_confirm": True,
        "draft_only": bool(draft_only),
        "enabled": True,
        "order": 100 + len(load_custom()),
    }
    items = load_custom()
    items.append(item)
    save_custom(items)
    reload()
    return item


def update_custom(key: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    items = load_custom()
    hit = None
    for p in items:
        if p["key"] == key:
            hit = p
            break
    if hit is None:
        raise ValueError("该平台不是自定义平台，不能修改")
    allowed = {"name", "short", "color", "login_url", "home_url",
               "publish_url", "content_types", "enabled", "draft_only"}
    for k, v in fields.items():
        if k in allowed:
            hit[k] = v
    save_custom(items)
    reload()
    return hit


def delete_custom(key: str) -> bool:
    """删除自定义平台。已存在的账号不会自动删除（保留台账，避免误删数据）。"""
    items = load_custom()
    left = [p for p in items if p["key"] != key]
    if len(left) == len(items):
        return False
    save_custom(left)
    reload()
    return True


def is_custom(key: str) -> bool:
    return bool(key) and key.startswith(CUSTOM_PREFIX)


# ---------------------------------------------------------------- 读取
def all_platforms() -> List[Dict[str, Any]]:
    global _cache
    if _cache is None:
        merged = _load_builtin() + load_custom()
        _cache = sorted(merged, key=lambda p: p.get("order", 99))
    return _cache


def reload() -> None:
    global _cache
    _cache = None


def get(key: str) -> Optional[Dict[str, Any]]:
    for p in all_platforms():
        if p["key"] == key:
            return p
    # 兜底：自定义平台被删了但账号还在 → 给一个能用的最小定义
    if key:
        return {"key": key, "name": key, "short": "?", "color": "#8A8F98",
                "login_url": "", "home_url": "", "publish_url": "",
                "adapter": "", "enabled": True}
    return None


def name_of(key: str) -> str:
    p = get(key)
    return p["name"] if p else key


def color_of(key: str) -> str:
    p = get(key)
    return p.get("color", "#8A8F98") if p else "#8A8F98"


def short_of(key: str) -> str:
    p = get(key)
    return p.get("short", "?") if p else "?"


def enabled_platforms() -> List[Dict[str, Any]]:
    return [p for p in all_platforms() if p.get("enabled", True)]


def has_adapter(key: str) -> bool:
    """是否有可用的自动填充脚本（自定义平台没有，走剪贴板兜底）。"""
    p = get(key) or {}
    return bool(p.get("adapter"))


def publish_url_for(key: str, content: Optional[Dict[str, Any]] = None) -> str:
    """按内容挑发布页地址。

    小红书这类平台的「图文 / 视频」是**两个不同的 URL**（`target=image` / `target=video`），
    而不是同一页上的两个 tab。直接导航到对的那个 URL，可以省掉
    「点 tab → 等 React 渲染编辑器 → 再填」这一整段不确定性
    （而且 Qt 的 runJavaScript 不 await Promise，脚本没法自己等）。
    """
    p = get(key) or {}
    content = content or {}
    if content.get("video_path") or content.get("video"):
        v = p.get("publish_url_video")
        if v:
            return v
    return p.get("publish_url", "")


_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".avi")
_MEDIA_EXT = _IMG_EXT + _VIDEO_EXT


def _path_of(field_value: Any) -> str:
    """从字段文本里解析出本地路径，返回**目录**。

    认两种写法（流水线各写一种，历史上只认第一种，导致视频自动上传
    解析不出文件 —— 顺手修掉）：
      · 「已出图 8 张，目录：J:/…/output/xxx」        → 直接是目录
      · 「分镜脚本\n\n视频文件：J:/…/xxx.mp4\n时长：…」→ 是文件，取所在目录

    不能整个字段当路径用 —— 那是成句的说明文字，得先认标记。
    """
    if not field_value:
        return ""
    text = field_value if isinstance(field_value, str) else str(field_value)
    for pat in (r"目录[:：]\s*(\S+)", r"视频文件[:：]\s*(\S+)"):
        m = re.search(pat, text)
        if not m:
            continue
        cand = m.group(1).strip().strip('"\'')
        if os.path.isfile(cand):
            return os.path.dirname(cand)
        if os.path.isdir(cand):
            return cand
    # 退化：取最后一行当路径（手工粘贴目录的场景）
    cand = text.splitlines()[-1].strip().strip('"\'') if text else ""
    return cand if os.path.isdir(cand) else ""


def _dir_of(field_value: Any) -> str:
    """旧名字，等价于 _path_of（兼容既有调用与测试）。"""
    return _path_of(field_value)


def media_dir_of(artifacts=None, content=None, platform_key: str = "") -> str:
    """这份内容对应的**本地媒体目录**（给「打开文件夹」和文件对话框定位用）。

    优先级：
      1. artifacts（真实产出文件）所在目录 —— 最可靠
      2. 平台声明的 upload_dir_field（小红书是 image_hint）解析出的目录
      3. shot_hint 里「视频文件：」所在目录（视频类产出）
    """
    for p in (artifacts or []):
        d = os.path.dirname(p) if os.path.isfile(p) else p
        if d and os.path.isdir(d):
            return d
    content = content or {}
    order = []
    p = get(platform_key) if platform_key else None
    if p and p.get("upload_dir_field"):
        order.append(p["upload_dir_field"])
    order += ["image_hint", "shot_hint"]
    for f in order:
        d = _path_of(content.get(f))
        if d:
            return d
    return ""


# ---------------------------------------------------------------- 批次 × 主题匹配
# 批次目录名 = _safe(标题)（非字母/数字/汉字统一换成 _，截 40 字），
# 所以按「非字词字符」把标题和目录名切成片段，片段能跨下划线对上。
_TOPIC_SPLIT_RE = re.compile(
    r"[\s\-_—–·、，。！？!?,:：;；|()\[\]【】「」《》~～+*/\\\"'“”<>=%&#@^$]+")
# 目录名与主题至少要拿到这个匹配分才算「同一题」（一个 2 字片段命中 = 2 分起）
TOPIC_MATCH_MIN = 2


def _topic_keywords(text: str) -> List[str]:
    """把标题 / 目录名拆成匹配用的关键词片段（≥2 字符，去重保序）。"""
    if not text:
        return []
    seen, out = set(), []
    for p in _TOPIC_SPLIT_RE.split(str(text)):
        if len(p) >= 2 and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def batch_match_score(dirname: str, topic: str) -> int:
    """批次目录名与内容主题的匹配分（0 = 不是同一题）。

    双向匹配 —— 目录名是标题的 _safe 化，常被截断到 40 字 / 改写：
      · 正向：主题的片段出现在目录名里（权重 ×2，主信号）
      · 反向：目录名的片段出现在主题里（标题被截短时靠这条兜住）
    """
    dirname, topic = str(dirname or ""), str(topic or "")
    if not dirname or not topic:
        return 0
    score = 0
    for k in _topic_keywords(topic):
        if k in dirname:
            score += len(k) * 2
    for f in _topic_keywords(dirname):
        if f in topic:
            score += len(f)
    return score


def _media_dirs(base: str, max_depth: int, exts: tuple) -> List[dict]:
    """base 下所有含指定扩展名文件的子目录 [{dir, mtime}]（含 base 本身）。"""
    base = base or config.OUTPUT_DIR
    out: List[dict] = []
    if not os.path.isdir(base):
        return out
    base_depth = base.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(base):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
            continue
        hits = [f for f in files if f.lower().endswith(exts)]
        if not hits:
            continue
        try:
            m = max(os.path.getmtime(os.path.join(root, f)) for f in hits)
        except OSError:
            continue
        out.append({"dir": root, "mtime": m})
    return out


def _pick_dir(cands: List[dict], topic: str = "") -> str:
    """从候选目录里挑一个：有主题时优先「同题批次」，否则取最新。

    为什么不能只按时间挑（真实踩坑）：output 下同时躺着多个选题的批次，
    上一题 26 张的批次比本题 8 张的批次晚生成几分钟 —— 按时间挑就把
    别的题的图挂到本题上（用户：「这条素材只有 8 张图，26 张是之前
    其他批次，混在一起了」）。目录名 = _safe(标题)，按名字对上才算数；
    都对不上（手工建的目录 / 标题被改得面目全非）才退回最新。
    """
    if not cands:
        return ""
    if topic:
        scored = [(batch_match_score(os.path.basename(c["dir"].rstrip(os.sep)),
                                     topic), c) for c in cands]
        scored.sort(key=lambda t: (t[0], t[1]["mtime"]), reverse=True)
        if scored and scored[0][0] >= TOPIC_MATCH_MIN:
            return scored[0][1]["dir"]
    return max(cands, key=lambda c: c["mtime"])["dir"]


def latest_media_dir(base: str = "", max_depth: int = 3, topic: str = "") -> str:
    """base 下最近修改的含媒体子目录（给「选配图」弹窗兜底定位）。

    场景：内容没挂 artifacts、hint 里也没目录 —— 但用户刚跑过流水线，
    output 下最新的那个批次就是他要的图。把文件对话框直接定位过去，
    别让他从「此电脑」一层层点进隐藏目录。

    topic 给了就先按题名匹配批次（同题优先，同分内取最新），
    没有匹配的才退回「最新」—— 防止别的选题的批次串题。
    """
    return _pick_dir(_media_dirs(base, max_depth, _IMG_EXT + _VIDEO_EXT), topic)


def latest_image_dir(base: str = "", max_depth: int = 3, topic: str = "") -> str:
    """base 下最近修改的含**图片**子目录（topic 给了就先按题名匹配）。

    与 latest_media_dir 的区别：视频批次（xhs_video 产出，目录里只有 mp4）
    不算。真实踩过的坑：视频批次比图片批次晚 3 分钟，「自动挂图」拿
    latest_media_dir 只会拿到一批视频 —— 挂到图文上白跑一趟，
    整个自动挂图流程被顶掉。

    topic 匹配规则同 latest_media_dir：同题批次优先于「新」——
    本题 8 张的旧批次，也优先于别的题 26 张的新批次。
    """
    return _pick_dir(_media_dirs(base, max_depth, _IMG_EXT), topic)


def open_in_explorer(path: str) -> bool:
    """在系统文件管理器里打开 path（文件则打开所在目录）。"""
    d = path if os.path.isdir(path) else os.path.dirname(path or "")
    if not d or not os.path.isdir(d):
        return False
    try:
        import subprocess
        import sys
        if sys.platform == "win32":
            os.startfile(d)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])
        return True
    except Exception:
        return False


def needs_upload(key: str) -> bool:
    """这个平台的发布页是不是「必须先上传素材，才会出现编辑表单」。

    小红书图文页就是这样：**不上传图片，页面上压根没有标题 / 正文编辑框**。
    以前适配脚本靠「有没有文件可传」（upload_files 非空）判断要不要点上传，
    于是内容里没配图时一步都不点，永远停在「没有找到正文编辑器」。

    现在改成由平台声明这件事，与「这次有没有文件可传」无关 ——
    没文件就点开上传对话框让用户自己选，选完编辑框自然出现。
    """
    return bool((get(key) or {}).get("upload_dir_field"))


def max_images(key: str) -> int:
    """平台单篇图片上限（rules.images.max，小红书 18）。0 = 不限。

    为什么上传前要截断：26 张整批塞给页面的 input[type=file]，
    小红书可能**整批拒收**（实测真机：页面停在空上传态，一张都没传），
    而不是只多出来的 8 张 —— 必须在喂给页面前就砍到上限内。
    """
    r = (get(key) or {}).get("rules") or {}
    try:
        return int((r.get("images") or {}).get("max") or 0)
    except (TypeError, ValueError):
        return 0


def _cap_images(key: str, files: List[str]) -> List[str]:
    """按平台单篇上限截断图片（保留前 N 张；非图片文件原样保留）。"""
    mx = max_images(key)
    if not files or not mx:
        return files
    imgs = [f for f in files if f.lower().endswith(_IMG_EXT)]
    if not imgs or len(imgs) <= mx:
        return files
    keep = set(imgs[:mx])
    return [f for f in files if (f in keep)
            or not f.lower().endswith(_IMG_EXT)]


def upload_files(key: str, content: Optional[Dict[str, Any]] = None,
                 artifacts: Optional[List[str]] = None) -> List[str]:
    """这次发布要传给页面上传控件的文件。

    优先级：
      1. **产出文件**（`artifacts`）—— 流水线真的生成了这些文件，路径最可靠
      2. 从 `image_hint` 里解析出的目录 —— 手工把目录贴进来的场景

    平台没声明 `upload_dir_field` 就一律返回空（宁可不传，也不要瞎点上传控件）。
    图片超过平台单篇上限（小红书 18 张）时自动取前 N 张。
    """
    p = get(key) or {}
    if not p.get("upload_dir_field"):
        return []
    out = [f for f in (artifacts or [])
           if f and os.path.exists(f) and f.lower().endswith(_MEDIA_EXT)]
    if not out:
        out = local_images(key, content) or local_videos(key, content)
    return _cap_images(key, out)


def local_images(key: str, content: Optional[Dict[str, Any]]) -> List[str]:
    """列出这份内容对应的本地配图（用于半自动上传）。

    只认平台声明的 `upload_dir_field`（小红书是 image_hint），
    且**必须是真实存在的目录** —— 宁可返回空，也不要瞎猜路径去点上传控件。
    """
    p = get(key) or {}
    content = content or {}
    field = p.get("upload_dir_field")
    if not field:
        return []
    d = _dir_of(content.get(field))
    if not d:
        return []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names
            if n.lower().endswith(_IMG_EXT)]


def local_videos(key: str, content: Optional[Dict[str, Any]]) -> List[str]:
    p = get(key) or {}
    content = content or {}
    field = p.get("upload_dir_field")
    if not field:
        return []
    d = _dir_of(content.get(field))
    if not d:
        return []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names
            if n.lower().endswith(_VIDEO_EXT)]
