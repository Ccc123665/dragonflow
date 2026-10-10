"""模型网关：多厂商适配 + 流式输出 + JSON 容错。

用标准库 urllib 直连（不经浏览器），因此完全不受同源策略限制。
API Key 只存本机配置文件，随请求直接发往模型厂商，不经任何第三方中转。
"""
import io
import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

# ---------------------------------------------------------------- 厂商预设
# 「模型」必须填**接口里的模型 ID**，不是官网/控制台上的显示名。
# 踩过的坑：显示名写的是 DeepSeek-V4.1-Flash，接口认的 ID 是 deepseek-flash，
# 直接填显示名会 400 invalid_request_error。
#
# vision_models：**能读图**的模型（2026-09 实测）。
# 注意 deepseek-v4-pro **不能**读图，而且是**静默丢弃** —— 不报错，
# prompt_tokens 不涨，然后回答「无法识别图片中的数字」。所以必须提前判断，
# 不能靠"发过去试试"。
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-flash",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "vision_models": ["deepseek-flash"],
        "reasoning": True,
        "help": "在 platform.deepseek.com 创建 API Key。"
                "模型填接口 ID（deepseek-flash / deepseek-v4-pro），"
                "不是网页上的显示名（DeepSeek-V4.1-Flash）。"
                "两个都是推理模型，思考过程会占用输出额度；"
                "其中只有 deepseek-flash 能读图。",
    },
    "zhipu": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "models": ["glm-4-plus", "glm-4-air", "glm-4-flash", "glm-4v-plus"],
        "vision_models": ["glm-4v-plus"],
        "help": "在 open.bigmodel.cn 创建 API Key。带 v 的是视觉模型（能读图）。",
    },
    "qwen": {
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-vl-max"],
        "vision_models": ["qwen-vl-max"],
        "help": "在 dashscope.aliyun.com 创建 API Key。带 vl 的是视觉模型（能读图）。",
    },
    "custom": {
        "name": "自定义（OpenAI 兼容）",
        "base_url": "",
        "model": "",
        "models": [],
        "vision_models": [],
        "help": "任何兼容 OpenAI /chat/completions 协议的服务，模型填它文档里给的 ID",
    },
}

PROVIDER_ORDER = ["deepseek", "zhipu", "qwen", "custom"]

# 自定义服务商没有预设时，按常见命名猜一把（只用来定默认值，不拦人）
_VISION_GUESS = re.compile(
    r"(?:^|[-_/])(?:vl|vision|4v|omni)(?:$|[-_/])|qwen-vl|glm-4v|gpt-4o|gpt-4\.1|claude|gemini", re.I)


def supports_vision(settings: dict) -> bool:
    """这个模型能不能读图。用于给「读配图」开关定默认值 + 提前给出警告。"""
    prov = PROVIDERS.get(settings.get("provider", ""), {})
    model = (settings.get("model") or "").strip()
    if not model:
        return False
    known = prov.get("vision_models") or []
    if known:
        return model in known
    if prov.get("models"):          # 有预设但没标视觉 → 认为读不了图
        return False
    return bool(_VISION_GUESS.search(model))


# ---------------------------------------------------------------- 错误信息
_MODEL_SUGGEST = re.compile(
    r"supported API model names? (?:are|is)\s+(.+?)(?:[,;.]?\s*but you passed|$)", re.I | re.S)

_MODEL_STOPWORDS = {"and", "or", "the", "but", "you", "passed", "supported",
                    "api", "model", "names", "name", "are", "is"}


def suggest_models(text: str) -> List[str]:
    """从「模型名不被支持」的报错里，把服务端真正认的模型 ID 抠出来。

    DeepSeek 的报错长这样：
      The supported API model names are deepseek-flash, deepseek-v4-pro,
      but you passed DeepSeek-V4.1-Flash.
    把这个列表抠出来，界面就能直接给出「改成哪个」的建议。
    """
    m = _MODEL_SUGGEST.search(text or "")
    if not m:
        return []
    out: List[str] = []
    for name in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]*", m.group(1)):
        if name.lower() in _MODEL_STOPWORDS or name in out:
            continue
        out.append(name)
    return out


def clean_error(code: int, raw: str, reason: str = "") -> str:
    """把接口返回的 JSON 错误体整理成一句人话，别把整坨 JSON 甩给用户。"""
    msg = ""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            err = obj.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("msg") or ""
            elif isinstance(err, str):
                msg = err
            if not msg:
                msg = obj.get("message") or obj.get("msg") or ""
    except Exception:
        pass
    if not msg:
        msg = re.sub(r"\s+", " ", (raw or "")).strip()
    if not msg:
        msg = str(reason or "未知错误")

    msg = re.sub(r"\s*\(request_id:[^)]*\)", "", msg)          # 去掉 request_id
    msg = re.sub(r"\s*(?:,|，)?\s*\"?(?:param|code|type)\"?\s*:\s*[^,}]*", "", msg)
    msg = re.sub(r"\s+", " ", msg).strip().strip('",')

    hint = suggest_models(msg)
    if hint:
        msg += f"\n→ 把「模型」改成：{' 或 '.join(hint)}"
    return msg



# ---------------------------------------------------------------- JSON 容错
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Optional[dict]:
    """从模型输出里尽力抠出 JSON 对象。失败返回 None。"""
    if not text:
        return None
    text = text.strip()

    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # 退一步：截取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        chunk = text[start:end + 1]
        try:
            obj = json.loads(chunk)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
        # 再退一步：修掉常见的尾逗号
        fixed = re.sub(r",\s*([}\]])", r"\1", chunk)
        try:
            obj = json.loads(fixed)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def to_text(value) -> str:
    """把模型返回的任意字段值统一成可显示文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(to_text(v) for v in value if to_text(v))
    if isinstance(value, dict):
        return "\n".join(f"{k}：{to_text(v)}" for k, v in value.items() if to_text(v))
    return str(value).strip()


# ---------------------------------------------------------------- 推理模型
# 推理模型的「思考过程」也算输出 token。踩过的坑：max_tokens 给 1200 时，
# 三次调用里有一次思考把 1200 全吃掉、正文返回 0 字，另外两次 JSON 被截断。
# 所以这类模型要给足额度，并且要能识别「被截断」而不是把半截 JSON 当成功。
_REASONING_NAME = re.compile(
    r"(reasoner|reasoning|thinking|qwq|deepseek-flash|deepseek-v4-pro|-r1\b|o[134](?:-|$))",
    re.I)

REASONING_FLOOR = 6000          # 推理模型的最低输出额度（思考 + 正文）
MAX_OUTPUT_CEILING = 16000      # 与设置里「单次输出上限」的上限保持一致


def is_reasoning(settings: dict) -> bool:
    """判断是不是推理模型。判错也不会出错 —— 只是多给一点输出额度。"""
    if PROVIDERS.get(settings.get("provider", ""), {}).get("reasoning"):
        return True
    return bool(_REASONING_NAME.search(settings.get("model") or ""))


def effective_max_tokens(settings: dict) -> int:
    """真正发给接口的输出上限：推理模型至少给到 REASONING_FLOOR。"""
    want = int(settings.get("max_tokens", 3000) or 3000)
    if is_reasoning(settings):
        want = max(want, REASONING_FLOOR)
    return min(want, MAX_OUTPUT_CEILING)


def _usage_note(obj: dict) -> str:
    """把「思考用了多少 token」写成一句可读的说明，用于报错。"""
    usage = obj.get("usage") or {}
    rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    return f"（本次思考占用了 {rt} tokens）" if rt else ""


def empty_reason(settings: dict, obj: Optional[dict] = None) -> str:
    """模型返回空内容时，给出能直接照做的原因。"""
    if is_reasoning(settings):
        return ("模型把输出额度全用在「思考」上了，没留下正文"
                + (_usage_note(obj or {}) if obj else "")
                + f"。请到「设置」把「单次输出上限」调大（当前按 "
                f"{effective_max_tokens(settings)} 发出去），或者换 deepseek-v4-pro 之外的模型。")
    return "模型返回了空内容，请重试；若反复出现，换一个模型试试"


# ---------------------------------------------------------------- 请求体
def _text_messages(system: str, user: str) -> List[dict]:
    messages: List[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return messages


def _payload(settings: dict, messages: List[dict], stream: bool) -> dict:
    return {
        "model": settings.get("model") or "deepseek-flash",
        "messages": messages,
        "temperature": float(settings.get("temperature", 0.8)),
        "max_tokens": effective_max_tokens(settings),
        "stream": stream,
    }


def build_payload(settings: dict, system: str, user: str, stream: bool) -> dict:
    return _payload(settings, _text_messages(system, user), stream)


def _endpoint(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        raise ValueError("接口地址为空，请到「设置」里填写")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def models_endpoint(base_url: str) -> str:
    """从接口地址推出 GET /models 的地址。"""
    base = (base_url or "").rstrip("/")
    for tail in ("/chat/completions", "/completions"):
        if base.endswith(tail):
            base = base[: -len(tail)]
            break
    if not base:
        raise ValueError("接口地址为空，请到「设置」里填写")
    return base + "/models"


def list_models(settings: dict, timeout: int = 20) -> List[str]:
    """问服务端「你这个 Key 能用哪些模型」，返回模型 ID 列表。

    比让用户照着官网手抄 ID 靠谱得多 —— 官网写的是显示名，接口认的是 ID，
    两者经常不一致（DeepSeek-V4.1-Flash vs deepseek-flash）。
    """
    key = (settings.get("api_key") or "").strip()
    if not key:
        raise ValueError("还没有填 API Key，请到「设置」里填写")
    req = urllib.request.Request(
        models_endpoint(settings.get("base_url", "")),
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise ValueError(f"接口返回 {e.code}：{clean_error(e.code, raw, str(e.reason))}")
    except urllib.error.URLError as e:
        raise ValueError(f"网络连接失败：{e.reason}")

    data = obj.get("data") if isinstance(obj, dict) else None
    out: List[str] = []
    for m in (data or []):
        mid = m.get("id") if isinstance(m, dict) else (m if isinstance(m, str) else "")
        if mid and mid not in out:
            out.append(str(mid))
    return sorted(out)


# ---------------------------------------------------------------- 异步任务
class GenerateTask(QThread):
    """后台线程执行一次生成，流式回调增量文本。"""

    chunk = pyqtSignal(str)          # 增量文本
    done = pyqtSignal(str)           # 完整文本
    failed = pyqtSignal(str)         # 错误信息

    def __init__(self, settings: dict, system: str, user: str, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.system = system
        self.user = user
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            text, finish = self._stream()
            # 推理模型把额度耗光 → 翻倍重来一次，别把半截 JSON 交给上层
            if finish == "length" and not self._cancelled:
                bigger = min(effective_max_tokens(self.settings) * 2, MAX_OUTPUT_CEILING)
                text2, _ = self._stream(bigger)
                if len(text2) > len(text):
                    text = text2
            if not text.strip():
                raise ValueError(empty_reason(self.settings))
            if not self._cancelled:
                self.done.emit(text)
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(str(e))

    # -- 内部 --
    def _stream(self, max_tokens: Optional[int] = None) -> Tuple[str, str]:
        settings = dict(self.settings)
        if max_tokens:
            settings["max_tokens"] = int(max_tokens)
        key = (settings.get("api_key") or "").strip()
        if not key:
            raise ValueError("还没有填 API Key，请到「设置」里填写")

        url = _endpoint(settings.get("base_url", ""))
        body = json.dumps(build_payload(settings, self.system, self.user, True)).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        buf: List[str] = []
        finish = ""
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                for raw in resp:
                    if self._cancelled:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    choice = (obj.get("choices") or [{}])[0]
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
                    # 推理模型的思考增量走 reasoning_content，只取 content 才不会被污染
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if piece:
                        buf.append(piece)
                        self.chunk.emit(piece)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            raise ValueError(f"接口返回 {e.code}：{clean_error(e.code, detail, str(e.reason))}")
        except urllib.error.URLError as e:
            raise ValueError(f"网络连接失败：{e.reason}")

        return "".join(buf), finish


# ---------------------------------------------------------------- 视觉
# 公众号的配图经常是 1000×3700 的长图。整张等比缩到长边 1400 的话宽度只剩 380px，
# 表格里的字全糊成一团 —— 所以长图要**竖着切开送**，而不是一味缩小。
VISION_MAX_SIDE = 1400          # 每块的长边上限（再大纯浪费 token）
VISION_QUALITY = 82             # JPEG 质量
VISION_SLICE_RATIO = 2.4        # 长宽比超过它才切
VISION_SLICE_OVERLAP = 0.08     # 切片之间留点重叠，免得正好从表格中间断开


def _pil_of(src):
    from PIL import Image
    if hasattr(src, "size") and hasattr(src, "crop"):        # 已经是 PIL Image
        return src.convert("RGB")
    if isinstance(src, (bytes, bytearray, memoryview)):
        return Image.open(io.BytesIO(bytes(src))).convert("RGB")
    return Image.open(src).convert("RGB")


def _fit(im, max_side: int):
    from PIL import Image
    w, h = im.size
    if max(w, h) > max_side:
        k = max_side / float(max(w, h))
        im = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    return im


def image_slices(src, max_side: int = VISION_MAX_SIDE,
                 max_ratio: float = VISION_SLICE_RATIO,
                 overlap: float = VISION_SLICE_OVERLAP) -> List[Any]:
    """把一张图切成适合送模型的若干块（返回 PIL Image 列表）。"""
    try:
        im = _pil_of(src)
    except Exception:
        return []
    w, h = im.size
    if w <= 0 or h <= 0:
        return []
    if h <= w * max_ratio:
        return [_fit(im, max_side)]

    win = max(200, int(w * max_ratio))
    step = max(120, int(win * (1 - overlap)))
    out: List[Any] = []
    y = 0
    while y < h:
        out.append(_fit(im.crop((0, y, w, min(y + win, h))), max_side))
        if y + win >= h:
            break
        y += step
    return out


def encode_image(src, **kw) -> List[str]:
    """把一张图编码成若干 data URL（长图会切成多块）。"""
    import base64
    out: List[str] = []
    for im in image_slices(src, **kw):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=VISION_QUALITY)
        out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    return out


def _vision_messages(system: str, user: str, images: List[Any],
                     max_slices: int = 24) -> List[dict]:
    parts: List[dict] = [{"type": "text", "text": user}]
    used = 0
    for src in images:
        for url in encode_image(src):
            if used >= max_slices:
                break
            parts.append({"type": "image_url", "image_url": {"url": url}})
            used += 1
        if used >= max_slices:
            break
    messages: List[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": parts})
    return messages


def chat_vision(settings: dict, system: str, user: str, images: List[Any], *,
                max_tokens: Optional[int] = None, temperature: Optional[float] = None,
                timeout: int = 240) -> str:
    """带图问一次模型。images 里每项可以是路径 / bytes / PIL Image。

    注意：**读不了图的模型不会报错**，而是静默丢掉图片（实测 deepseek-v4-pro）。
    所以调用方要用 supports_vision() 提前判断，别指望这里能拦住。
    """
    s = dict(settings)
    if max_tokens:
        s["max_tokens"] = int(max_tokens)
    if temperature is not None:
        s["temperature"] = float(temperature)
    messages = _vision_messages(system, user, images)
    try:
        text, finish, obj = _post_chat(s, messages, timeout)
    except ValueError as e:
        msg = str(e)
        if re.search(r"image|vision|multimodal|content", msg, re.I):
            raise ValueError(
                f"{msg}\n→ 当前模型（{s.get('model')}）可能不支持图片输入，"
                f"换一个能读图的模型再试（deepseek-flash / qwen-vl-max / glm-4v-plus）")
        raise
    if finish == "length" and effective_max_tokens(s) < MAX_OUTPUT_CEILING:
        s2 = dict(s)
        s2["max_tokens"] = min(effective_max_tokens(s) * 2, MAX_OUTPUT_CEILING)
        text2, _, obj2 = _post_chat(s2, messages, timeout)
        if len(text2) > len(text):
            text, obj = text2, obj2
    if not text:
        raise ValueError(empty_reason(s, obj))
    return text


# ---------------------------------------------------------------- 同步调用
def _post_chat(s: dict, messages: List[dict], timeout: int) -> Tuple[str, str, dict]:
    """发一次非流式请求，返回 (正文, finish_reason, 原始响应)。"""
    key = (s.get("api_key") or "").strip()
    if not key:
        raise ValueError("还没有填 API Key，请到「设置」里填写")
    url = _endpoint(s.get("base_url", ""))
    body = json.dumps(_payload(s, messages, False)).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise ValueError(f"接口返回 {e.code}：{clean_error(e.code, detail, str(e.reason))}")
    except urllib.error.URLError as e:
        raise ValueError(f"网络连接失败：{e.reason}")
    choice = (obj.get("choices") or [{}])[0]
    msg = choice.get("message", {}) or {}
    return (msg.get("content") or "").strip(), (choice.get("finish_reason") or ""), obj


def chat(settings: dict, system: str, user: str, max_tokens: Optional[int] = None,
         temperature: Optional[float] = None, timeout: int = 240) -> str:
    """同步阻塞地问一次模型，返回完整文本。

    给 pipeline（抓取 / 出图 / 渲染这类多步骤流程）用 —— 它们本身已经跑在
    后台线程里，再套一层 QThread 反而更绕。GUI 单次生成仍走 GenerateTask（流式）。

    对推理模型做了两层兜底（思考过程会吃输出额度）：
      · 额度下限抬到 REASONING_FLOOR
      · 若 finish_reason == "length"（被截断），翻倍重来一次，取更长的那份
    """
    s = dict(settings)
    if max_tokens:
        s["max_tokens"] = int(max_tokens)
    if temperature is not None:
        s["temperature"] = float(temperature)

    messages = _text_messages(system, user)
    text, finish, obj = _post_chat(s, messages, timeout)
    if finish == "length" and effective_max_tokens(s) < MAX_OUTPUT_CEILING:
        s2 = dict(s)
        s2["max_tokens"] = min(effective_max_tokens(s) * 2, MAX_OUTPUT_CEILING)
        text2, _, obj2 = _post_chat(s2, messages, timeout)
        if len(text2) > len(text):
            text, obj = text2, obj2
    if not text:
        raise ValueError(empty_reason(s, obj))
    return text


class ListModelsTask(QThread):
    """拉取「这个 Key 能用哪些模型」。"""

    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)

    def run(self):
        try:
            self.done.emit(list_models(self.settings))
        except Exception as e:
            self.failed.emit(str(e))


class TestTask(QThread):
    """连通性测试：发一条最短的请求。"""

    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)

    def run(self):
        try:
            settings = dict(self.settings)
            # build_payload 内部会按模型类型给额度兜底（推理模型 ≥ REASONING_FLOOR），
            # 这里只是把「设置里的值」压小，让测试请求尽量短。
            settings["max_tokens"] = 512
            settings["temperature"] = 0.0
            url = _endpoint(settings.get("base_url", ""))
            key = (settings.get("api_key") or "").strip()
            if not key:
                raise ValueError("还没有填 API Key")
            body = json.dumps(build_payload(settings, "", "回复两个字：可用", False)).encode("utf-8")
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="replace"))
            msg = (obj.get("choices") or [{}])[0].get("message", {}) or {}
            text = (msg.get("content") or "").strip()
            if not text and msg.get("reasoning_content"):
                # 思考了但没轮到输出正文（额度被思考吃光）—— 连接本身是通的
                text = "连接正常（推理模型：本次只输出了思考过程，可把「单次输出上限」调大）"
            usage = obj.get("usage") or {}
            rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            if rt:
                text += f"（本次思考用了 {rt} tokens）"
            self.done.emit(text or "连接正常")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            self.failed.emit(f"接口返回 {e.code}：{clean_error(e.code, detail, str(e.reason))}")
        except Exception as e:
            self.failed.emit(str(e))
