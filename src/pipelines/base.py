"""Pipeline 协议：多步骤内容生产流程（抓取 → 生成 → 出图 / 渲染）。

和「prompt 型」模板的区别
  · prompt 型：一次大模型调用 → JSON 字段 → 直接显示在卡片里
  · pipeline 型：要抓网页、要下载图片、要用 PIL 出图、要调 ffmpeg 渲染视频，
    中间有真实的代码执行和文件产出，因此单独用 Python 模块描述

一个 pipeline 需要：
  · key / name / desc / platform / content_type —— 元信息，用于登记成模板
  · fields()   —— 产出哪些文本字段（用于卡片展示与后续填充）
  · inputs()   —— 需要用户填什么参数（链接、数量、风格…）
  · run()      —— 真正干活；通过 ctx 汇报进度、请求模型、拿到输出目录
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import config


# ---------------------------------------------------------------- 输入项
@dataclass
class Input:
    """pipeline 的一个用户输入项。"""

    key: str
    label: str
    kind: str = "text"           # text | textarea | choice | switch
    default: str = ""
    placeholder: str = ""
    help: str = ""
    choices: List[str] = field(default_factory=list)
    required: bool = True
    rows: int = 4                # textarea 专用


# ---------------------------------------------------------------- 运行上下文
class Ctx:
    """pipeline 运行期间的上下文：进度、日志、模型、输出目录、取消。"""

    def __init__(self, settings: Dict[str, Any], out_dir: str, *,
                 log=None, progress=None, cancelled=None):
        self.settings = dict(settings or {})
        self.out_dir = out_dir
        self._log = log or (lambda _m: None)
        self._progress = progress or (lambda _p, _m="": None)
        self._cancelled = cancelled or (lambda: False)
        self.artifacts: List[str] = []       # 产出的图片 / 视频路径
        os.makedirs(out_dir, exist_ok=True)

    # -- 对外 --
    def log(self, msg: str) -> None:
        self._log(str(msg))

    def progress(self, pct: float, msg: str = "") -> None:
        self._progress(max(0.0, min(1.0, float(pct))), str(msg))

    def stopped(self) -> bool:
        return bool(self._cancelled())

    def check(self) -> None:
        if self.stopped():
            raise InterruptedError("已停止")

    def add(self, path: str) -> str:
        if path and path not in self.artifacts:
            self.artifacts.append(path)
        return path

    def llm(self, system: str, user: str, *, max_tokens: Optional[int] = None,
            temperature: Optional[float] = None) -> str:
        import llm
        return llm.chat(self.settings, system, user,
                        max_tokens=max_tokens, temperature=temperature)

    def llm_json(self, system: str, user: str, *, max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> Optional[dict]:
        import llm
        raw = self.llm(system, user, max_tokens=max_tokens, temperature=temperature)
        return llm.extract_json(raw)

    # -- 视觉 --
    def supports_vision(self) -> bool:
        """当前模型能不能读图。

        必须提前判断，不能"发过去试试" —— 读不了图的模型是**静默丢弃**图片的
        （实测 deepseek-v4-pro：不报错，prompt_tokens 不涨，然后答「无法识别图片」）。
        """
        import llm
        return llm.supports_vision(self.settings)

    def llm_vision(self, system: str, user: str, images: List[Any], *,
                   max_tokens: Optional[int] = None,
                   temperature: Optional[float] = None) -> str:
        """带图问一次模型。images 里每项可以是路径 / bytes / PIL Image。"""
        import llm
        return llm.chat_vision(self.settings, system, user, list(images),
                               max_tokens=max_tokens, temperature=temperature)


# ---------------------------------------------------------------- 基类
class Pipeline:
    key: str = ""
    name: str = ""
    desc: str = ""
    note: str = ""              # 耗时 / 依赖之类的预期说明，显示在参数弹窗里
    platform: str = "xhs"
    content_type: str = "图文"
    icon: str = "sparkle"
    fields: List[str] = ["title", "body", "topics"]
    needs_llm: bool = True
    # 这个能力**产出什么**，用给人看的短标签。
    # 内容工坊的能力卡片要显示它，让用户选之前就知道会拿到什么。
    outputs: List[str] = []

    def inputs(self) -> List[Input]:
        return []

    def output_labels(self) -> List[str]:
        """产出标签。没声明就按 content_type 兜一个。"""
        return list(self.outputs or [self.content_type or "内容"])

    def run(self, values: Dict[str, str], ctx: Ctx) -> Dict[str, Any]:
        """返回 {字段: 文本}，可选 "_artifacts": [路径]。"""
        raise NotImplementedError

    # -- 便利方法 --
    def output_dir(self, tag: str) -> str:
        return config.output_path(self.key, _safe(tag) or "output")


def _safe(text: str) -> str:
    import re
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", str(text or "")).strip("_")
    return s[:40]


# ---------------------------------------------------------------- 注册表
_REGISTRY: Dict[str, Pipeline] = {}


def register(cls):
    """类装饰器：把一个 Pipeline 类登记进注册表。"""
    inst = cls()
    if not inst.key:
        raise ValueError(f"{cls.__name__} 缺少 key")
    _REGISTRY[inst.key] = inst
    return cls


def get(key: str) -> Optional[Pipeline]:
    return _REGISTRY.get(str(key or "").strip())


def all_pipelines() -> List[Pipeline]:
    return list(_REGISTRY.values())


def keys() -> List[str]:
    return list(_REGISTRY.keys())
