"""发布执行器：把内容注入各平台发布页，并按需触发提交。

与界面解耦——只依赖一个「按账号取浏览器页面」的回调，方便测试与替换。

适配脚本约定（assets/adapters/<platform>.js）：
    window.DragonFlow = {
        name: 'xhs',
        fill: function (payload) { ... return {ok, filled:[], missing:[], message} },
        submit: function () { ... return {ok, message} },
        ready: function () { return true | false }
    };
"""
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

import config
import store


# ---------------------------------------------------------------- 适配脚本
_adapter_cache: Dict[str, str] = {}


def _read_js(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    cached = _adapter_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            js = f.read()
        _adapter_cache[path] = (mtime, js)
        return js
    except Exception:
        return ""


def adapter_js(platform_key: str, adapter_file: str = "") -> str:
    """读取平台适配脚本，并前置注入公共库 _common.js。

    找不到平台脚本时返回空串（上层会走「复制到剪贴板」的兜底）。
    """
    fname = adapter_file or f"{platform_key}.js"
    body = _read_js(os.path.join(config.ADAPTERS_DIR, fname))
    if not body:
        return ""
    common = _read_js(os.path.join(config.ADAPTERS_DIR, "_common.js"))
    return f"{common}\n{body}"


def reload_adapters() -> None:
    _adapter_cache.clear()


def has_adapter(platform_key: str, adapter_file: str = "") -> bool:
    return bool(adapter_js(platform_key, adapter_file))


# ---------------------------------------------------------------- 脚本拼装
def _json_literal(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build_fill_script(platform_key: str, adapter_file: str,
                      payload: Dict[str, Any]) -> str:
    """拼出「注入适配脚本 + 调用 fill」的一整段 JS。"""
    js = adapter_js(platform_key, adapter_file)
    if not js:
        return ""
    return f"""
(function () {{
  try {{
    {js}
    if (!window.DragonFlow || typeof window.DragonFlow.fill !== 'function') {{
      return JSON.stringify({{ok:false, message:'适配脚本未正确加载'}});
    }}
    var r = window.DragonFlow.fill({_json_literal(payload)});
    return JSON.stringify(r || {{ok:false, message:'适配脚本无返回'}});
  }} catch (e) {{
    return JSON.stringify({{ok:false, message:'注入异常：' + (e && e.message ? e.message : e)}});
  }}
}})();
"""


def build_submit_script(platform_key: str, adapter_file: str) -> str:
    js = adapter_js(platform_key, adapter_file)
    if not js:
        return ""
    return f"""
(function () {{
  try {{
    {js}
    if (!window.DragonFlow || typeof window.DragonFlow.submit !== 'function') {{
      return JSON.stringify({{ok:false, message:'适配脚本未提供提交方法'}});
    }}
    var r = window.DragonFlow.submit();
    return JSON.stringify(r || {{ok:false, message:'适配脚本无返回'}});
  }} catch (e) {{
    return JSON.stringify({{ok:false, message:'提交异常：' + (e && e.message ? e.message : e)}});
  }}
}})();
"""


def build_probe_script(platform_key: str, adapter_file: str) -> str:
    js = adapter_js(platform_key, adapter_file)
    if not js:
        return ""
    return f"""
(function () {{
  try {{
    {js}
    if (!window.DragonFlow || typeof window.DragonFlow.ready !== 'function') {{
      return JSON.stringify({{ok:false, message:'适配脚本未提供 ready 方法'}});
    }}
    return JSON.stringify({{ok: !!window.DragonFlow.ready()}});
  }} catch (e) {{
    return JSON.stringify({{ok:false, message:'检测异常：' + (e && e.message ? e.message : e)}});
  }}
}})();
"""


def build_diagnose_script(platform_key: str, adapter_file: str) -> str:
    """让适配脚本把「页面上到底有什么」报回来。

    「填不上」的可能原因太多（没登录 / 停在视频页 / 表单还没渲染 / 页面改版），
    靠日志猜不如让用户点一下「诊断」，直接看到探针结果。
    """
    js = adapter_js(platform_key, adapter_file)
    if not js:
        return ""
    return f"""
(function () {{
  try {{
    {js}
    var out = {{url: location.href, host: location.host}};
    if (window.DragonFlow && typeof window.DragonFlow.diagnose === 'function') {{
      var d = window.DragonFlow.diagnose() || {{}};
      for (var k in d) {{ if (Object.prototype.hasOwnProperty.call(d, k)) out[k] = d[k]; }}
    }} else {{
      out.adapter = false;
    }}
    return JSON.stringify(out);
  }} catch (e) {{
    return JSON.stringify({{ok:false, message:'诊断异常：' + (e && e.message ? e.message : e)}});
  }}
}})();
"""


def diagnose(page, platform_key: str, adapter_file: str, callback=None) -> None:
    """对某个页面跑一次诊断，结果通过 callback(dict) 回传。"""
    script = build_diagnose_script(platform_key, adapter_file)
    if not script or page is None:
        if callback:
            callback({"ok": False, "message": "该平台没有适配脚本，无法诊断"})
        return
    page.runJavaScript(script, lambda res: callback(parse_result(res)) if callback else None)


def parse_result(raw: Any) -> Dict[str, Any]:
    """runJavaScript 的回调值是 Python 对象（Qt 会自动解 JSON 字符串）。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"ok": False, "message": raw[:200]}
    return {"ok": False, "message": "无返回"}


def payload_of(content: Dict[str, Any], topic: str = "") -> Dict[str, Any]:
    """把内容卡片整理成适配脚本要的 payload。"""
    p = {k: v for k, v in (content or {}).items()}
    p["_topic"] = topic
    return p


# ---------------------------------------------------------------- 执行队列
class PublishQueue(QObject):
    """按顺序对多个平台执行「填充」或「提交」。

    page_provider(account_id) -> QWebEnginePage | None
        由界面层提供，返回该账号当前已打开的发布页。
    """

    step = pyqtSignal(int, int, str)          # (当前序号, 总数, 描述)
    item_done = pyqtSignal(str, bool, str, dict)   # (record_id, ok, message, meta)
    all_done = pyqtSignal(bool)               # (是否全部成功)

    # 页面异步渲染的等待策略。
    # 为什么放在 Python 侧而不是脚本里：Qt 的 runJavaScript **不 await Promise**
    # （实测 Promise.resolve(...) 直接变成 {}），注入的脚本没法自己 sleep。
    # 所以适配脚本遇到「还没渲染好」就返回 retry:true，由这里延迟重跑同一项。
    MAX_RETRY = 8
    RETRY_DELAY_MS = 1500
    # 要传文件的项（upload_count>0）：编辑器要等**整批图上传完**才渲染，
    # 几十张图 12 秒远远不够（实测 26 张超时失败）——预算放宽到 60 秒。
    MAX_RETRY_UPLOAD = 40

    def __init__(self, page_provider: Callable[[str], Any], parent=None):
        super().__init__(parent)
        self._page_provider = page_provider
        self._items: List[Dict[str, Any]] = []
        self._idx = 0
        self._mode = "fill"
        self._interval = 0
        self._ok_count = 0
        self._running = False
        self._retry = 0

    # -- 对外 --
    def run(self, items: List[Dict[str, Any]], mode: str = "fill", interval: int = 0):
        """items: [{record_id, platform_key, platform_name, account_id, adapter, payload, topic}]"""
        self._items = list(items)
        self._idx = 0
        self._mode = mode
        self._interval = max(0, int(interval))
        self._ok_count = 0
        self._retry = 0
        self._running = True
        QTimer.singleShot(30, self._next)

    def stop(self):
        self._running = False

    def is_running(self) -> bool:
        return self._running

    # -- 内部 --
    def _next(self):
        if not self._running or self._idx >= len(self._items):
            self._finish()
            return
        item = self._items[self._idx]
        total = len(self._items)
        verb = "填充" if self._mode == "fill" else "发布"
        tail = f"（第 {self._retry + 1} 次尝试）" if self._retry else ""
        self.step.emit(self._idx + 1, total,
                       f"正在{verb}：{item.get('platform_name','')}{tail}")

        page = self._page_provider(item.get("account_id", ""))
        if page is None:
            self.item_done.emit(item["record_id"], False,
                                "没有找到该账号的发布页，请先打开", {})
            self._advance()
            return

        if self._mode == "fill":
            payload = dict(item.get("payload") or {})
            # 只在**第一次尝试**时告诉脚本「有 N 个文件要传」。
            # 重试时置 0：页面可能已经传过一遍了，再点一次上传控件会重复传图。
            payload["_upload_count"] = (
                int(item.get("upload_count") or 0) if self._retry == 0 else 0)
            # 「这个平台要先传素材才有编辑表单」——每次尝试都要带上：
            # 重试期间脚本仍需要知道该不该继续等页面渲染出来。
            payload["_want_upload"] = bool(item.get("want_upload"))
            script = build_fill_script(item.get("platform_key", ""),
                                       item.get("adapter", ""), payload)
        else:
            script = build_submit_script(item.get("platform_key", ""),
                                         item.get("adapter", ""))

        if not script:
            self.item_done.emit(item["record_id"], False,
                                "缺少该平台的适配脚本，已降级为手动粘贴", {})
            self._advance()
            return

        try:
            page.runJavaScript(script, lambda res, it=item: self._on_result(it, res))
        except Exception as e:
            self.item_done.emit(item["record_id"], False, f"执行失败：{e}", {})
            self._advance()

    def _on_result(self, item: Dict[str, Any], raw: Any):
        res = parse_result(raw)

        # 适配脚本说「还没就绪，稍后重跑」→ 延迟重试同一项，不推进序号
        if res.get("retry") and self._mode == "fill":
            # 要传文件的项给更长的预算：编辑器要等整批图传完才渲染
            budget = self.MAX_RETRY_UPLOAD \
                if int(item.get("upload_count") or 0) > 0 else self.MAX_RETRY
            self._retry += 1
            if self._retry <= budget:
                self.step.emit(
                    self._idx + 1, len(self._items),
                    f"{item.get('platform_name','')}："
                    f"{res.get('message') or '等待页面就绪…'}"
                    f"（{self._retry}/{budget}）")
                QTimer.singleShot(self.RETRY_DELAY_MS, self._next)
                return
            if budget == self.MAX_RETRY_UPLOAD:
                res = {"ok": False,
                       "message": f"图片上传/页面渲染较慢（已等约 "
                                  f"{int(budget * self.RETRY_DELAY_MS / 1000)} 秒）。"
                                  f"传完后会自动继续填充",
                       # ⚠ 必须带上 stage：工作台 _on_item_done 靠
                       # meta.stage ∈ (upload/wait/switch) 排「自动续跑」——
                       # 丢了它，上面那句「会自动继续填充」就是空头支票
                       # （v1.6·2 回归测试抓出来的）
                       "stage": res.get("stage", "")}
            else:
                res = {"ok": False,
                       "message": f"等待页面就绪超时（已重试 {budget} 次）："
                                  f"{res.get('message','')}"}

        ok = bool(res.get("ok"))
        msg = res.get("message") or ("完成" if ok else "未知原因失败")
        # manual = 「需要人工介入」，不是失败：页面要求手动选图 / 有验证码之类，
        # 脚本已经把能做的做了，用户处理完再点一次就行。界面要把它显示成
        # 「需人工」而不是「失败」，否则用户会以为程序坏了。
        meta = {"manual": bool(res.get("manual")), "stage": res.get("stage", "")}
        if ok:
            self._ok_count += 1
            missing = res.get("missing") or []
            if missing:
                msg = f"完成，但有 {len(missing)} 项需人工补：{'、'.join(str(m) for m in missing[:3])}"
        self.item_done.emit(item["record_id"], ok, msg, meta)
        self._advance()

    def _advance(self):
        self._idx += 1
        self._retry = 0
        delay = 60
        if self._interval and self._idx < len(self._items):
            delay = self._interval * 1000
        QTimer.singleShot(delay, self._next)

    def _finish(self):
        self._running = False
        self.all_done.emit(self._ok_count == len(self._items) and bool(self._items))


# ---------------------------------------------------------------- 兜底
def fallback_text(content: Dict[str, Any], skill_fields: List[str]) -> str:
    """填充失败时给人工粘贴用的纯文本。"""
    parts: List[str] = []
    for f in (skill_fields or list(content.keys())):
        v = content.get(f)
        if not v:
            continue
        if f in ("topics", "image_hint", "shot_hint"):
            continue
        parts.append(str(v))
    topics = content.get("topics")
    if topics:
        if isinstance(topics, list):
            parts.append(" ".join(f"#{t.lstrip('#')}" for t in topics))
        else:
            parts.append(str(topics))
    return "\n\n".join(parts).strip()


def save_fail_shot(account_name: str, platform_name: str) -> str:
    """失败截图占位——实际截图由界面层调用 view.grab() 后落盘。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe = "".join(c for c in f"{platform_name}_{account_name}" if c not in '\\/:*?"<>|')
    return config.shots_path(f"{ts}_{safe}.png")
