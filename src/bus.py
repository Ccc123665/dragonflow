"""跨面板通信总线与当前草稿会话。"""
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal


class Bus(QObject):
    # 账号数据变动
    accounts_changed = pyqtSignal()
    # 草稿批次更新（内容工坊生成完成）
    draft_changed = pyqtSignal()
    # 请求打开发布工作台
    goto_workbench = pyqtSignal()
    # 发布记录有更新
    records_changed = pyqtSignal()
    # 设置变更
    settings_changed = pyqtSignal()
    # 素材库变更
    library_changed = pyqtSignal()
    # 跳到设置页（可带要打开的 tab key）。内容工坊的「管理 / 上传能力」用它，
    # 免得工坊去摸主窗口的内部结构。
    goto_settings = pyqtSignal(str)


BUS = Bus()


class DraftItem:
    """一个平台的一份内容草稿。"""

    def __init__(self, platform_key: str, skill_id: str, skill_name: str,
                 content: Dict[str, Any], topic: str = "", slots: Optional[Dict] = None):
        self.platform_key = platform_key
        self.skill_id = skill_id
        self.skill_name = skill_name
        self.content: Dict[str, Any] = dict(content or {})
        self.topic = topic
        self.slots = dict(slots or {})
        self.account_id = ""          # 目标账号，由发布工作台指定
        self.enabled = True           # 是否参与一键发布
        self.status = "待填充"
        self.message = ""
        # 流水线产出的图片 / 视频（本地绝对路径）。
        # 发布时用它去预置上传控件 —— 没有它，「一键填充」就只能填文字。
        self.artifacts: List[str] = []
        # 矩阵差异化：同一份内容发给同平台的多个账号时，可以给某个账号一份
        # 改写过的版本（换标题 / 换开头 / 换话题），避免被判重复搬运。
        # 结构：{account_id: {field: value}}
        self.variants: Dict[str, Dict[str, Any]] = {}

    def content_for(self, account_id: str) -> Dict[str, Any]:
        """取某个账号该用的内容：有差异化版本就用它，否则用原文。"""
        v = self.variants.get(account_id or "")
        return dict(v) if v else dict(self.content)

    def has_variant(self, account_id: str) -> bool:
        return bool(self.variants.get(account_id or ""))

    def text(self) -> str:
        from publisher import fallback_text
        parts = []
        for k in ("title", "digest", "hook", "body", "cta"):
            v = self.content.get(k)
            if v:
                parts.append(str(v))
        t = self.content.get("topics")
        if t:
            if isinstance(t, list):
                parts.append(" ".join(f"#{str(x).lstrip('#')}" for x in t))
            else:
                parts.append(str(t))
        return "\n\n".join(parts).strip()

    def all_text(self) -> str:
        parts = []
        for v in self.content.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, list):
                parts.append(" ".join(str(x) for x in v))
        return "\n".join(parts)


class Batch:
    def __init__(self, topic: str):
        self.topic = topic
        self.items: List[DraftItem] = []
        self.created_at = ""


CURRENT: Optional[Batch] = None


def set_batch(batch: Optional[Batch]) -> None:
    global CURRENT
    CURRENT = batch
    BUS.draft_changed.emit()


def batch() -> Optional[Batch]:
    return CURRENT


def find_item(platform_key: str) -> Optional[DraftItem]:
    if not CURRENT:
        return None
    for it in CURRENT.items:
        if it.platform_key == platform_key:
            return it
    return None
