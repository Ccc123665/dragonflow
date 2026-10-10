"""本地数据层：账号台账 / 素材库 / 发布记录 / 设置。

纯本地 JSON 文件读写，无任何网络行为。写入走临时文件 + 原子替换，避免半截文件。
"""
import datetime
import json
import os
import shutil
import uuid
from typing import Any, Dict, List, Optional

import config


# ---------------------------------------------------------------- 基础工具
def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _read(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            shutil.copy(path, path + ".corrupt." + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
        except Exception:
            pass
        return default


def _write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    shutil.move(tmp, path)


# ================================================================ 账号台账
ACCOUNT_STATUS = ["正常", "限流", "封禁预警", "停用"]


def load_accounts() -> Dict[str, Any]:
    db = _read(config.ACCOUNTS_FILE, {"version": 1, "accounts": []})
    db.setdefault("accounts", [])
    return db


def save_accounts(db: Dict[str, Any]) -> None:
    _write(config.ACCOUNTS_FILE, db)


def list_accounts(db: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return (db or load_accounts())["accounts"]


def accounts_of(db: Dict[str, Any], platform: str) -> List[Dict[str, Any]]:
    return [a for a in db["accounts"] if a.get("platform") == platform]


def get_account(db: Dict[str, Any], aid: str) -> Optional[Dict[str, Any]]:
    for a in db["accounts"]:
        if a["id"] == aid:
            return a
    return None


def add_account(db: Dict[str, Any], platform: str, name: str, **fields) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("账号名称不能为空")
    if len(accounts_of(db, platform)) >= config.MAX_ACCOUNTS_PER_PLATFORM:
        raise ValueError(f"该平台账号数量已达上限 {config.MAX_ACCOUNTS_PER_PLATFORM}")
    acc = {
        "id": new_id("acc_"),
        "platform": platform,
        "name": name,
        "nickname": fields.get("nickname", ""),
        "group": fields.get("group", ""),
        "persona": fields.get("persona", ""),
        "owner": fields.get("owner", ""),
        "status": fields.get("status", "正常"),
        "logged_in": False,
        "note": fields.get("note", ""),
        "created_at": now(),
        "updated_at": now(),
    }
    db["accounts"].append(acc)
    save_accounts(db)
    return acc


def update_account(db: Dict[str, Any], aid: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    acc = get_account(db, aid)
    if not acc:
        raise ValueError("账号不存在")
    allowed = {"name", "nickname", "group", "persona", "owner", "status", "note", "logged_in"}
    for k, v in fields.items():
        if k in allowed:
            acc[k] = v
    acc["updated_at"] = now()
    save_accounts(db)
    return acc


def delete_account(db: Dict[str, Any], aid: str) -> None:
    db["accounts"] = [a for a in db["accounts"] if a["id"] != aid]
    save_accounts(db)


def clear_profile(aid: str) -> bool:
    """清除某账号的浏览器数据（Cookie / 登录态 / 缓存）。"""
    d = os.path.join(config.PROFILES_DIR, aid)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def groups_of(db: Dict[str, Any]) -> List[str]:
    return sorted({a.get("group", "") for a in db["accounts"] if a.get("group")})


# ================================================================ 素材库
def load_library() -> Dict[str, Any]:
    db = _read(config.LIBRARY_FILE, {"version": 1, "items": []})
    db.setdefault("items", [])
    return db


def save_library(db: Dict[str, Any]) -> None:
    _write(config.LIBRARY_FILE, db)


def add_library_item(db: Dict[str, Any], **fields) -> Dict[str, Any]:
    item = {
        "id": new_id("lib_"),
        "title": fields.get("title", ""),
        "topic": fields.get("topic", ""),
        "platform": fields.get("platform", ""),
        "skill_id": fields.get("skill_id", ""),
        "content": fields.get("content", {}),
        # 流水线产出的图片 / 视频。必须存下来：
        # 以前只存 content（纯文字），于是「素材库里只有文案没有图」，
        # 复用到工作台也带不上配图。
        "artifacts": list(fields.get("artifacts") or []),
        "tags": fields.get("tags", []),
        "favorite": False,
        "created_at": now(),
    }
    db["items"].insert(0, item)
    save_library(db)
    return item


def delete_library_item(db: Dict[str, Any], iid: str) -> None:
    db["items"] = [i for i in db["items"] if i["id"] != iid]
    save_library(db)


# ================================================================ 发布记录
def load_records() -> Dict[str, Any]:
    db = _read(config.RECORDS_FILE, {"version": 1, "records": []})
    db.setdefault("records", [])
    return db


def save_records(db: Dict[str, Any]) -> None:
    _write(config.RECORDS_FILE, db)


def add_record(db: Dict[str, Any], **fields) -> Dict[str, Any]:
    rec = {
        "id": new_id("rec_"),
        "topic": fields.get("topic", ""),
        "platform": fields.get("platform", ""),
        "platform_name": fields.get("platform_name", ""),
        "account_id": fields.get("account_id", ""),
        "account_name": fields.get("account_name", ""),
        "status": fields.get("status", "待填充"),   # 待填充 | 已填充 | 已发布 | 失败 | 草稿
        "message": fields.get("message", ""),
        "shot": fields.get("shot", ""),
        "created_at": now(),
    }
    db["records"].insert(0, rec)
    save_records(db)
    return rec


def update_record(db: Dict[str, Any], rid: str, fields: Dict[str, Any]) -> None:
    for r in db["records"]:
        if r["id"] == rid:
            r.update(fields)
            break
    save_records(db)


def count_today(db: Dict[str, Any], account_id: str) -> int:
    t = today()
    return len([r for r in db["records"]
                if r.get("account_id") == account_id
                and r.get("status") in ("已发布", "已填充")
                and r.get("created_at", "").startswith(t)])


# ================================================================ 设置
def load_settings() -> Dict[str, Any]:
    s = dict(config.DEFAULT_SETTINGS)
    s.update(_read(config.SETTINGS_FILE, {}))
    return s


def save_settings(s: Dict[str, Any]) -> None:
    _write(config.SETTINGS_FILE, s)


# ================================================================ 备份 / 导入导出
def export_all(dst_path: str) -> str:
    payload = {
        "version": 1,
        "exported_at": now(),
        "accounts": load_accounts(),
        "skills_user": _read(config.SKILLS_USER_FILE, {}),
        "forbidden_user": _read(config.FORBIDDEN_USER_FILE, {}),
        "settings": {k: v for k, v in load_settings().items() if k != "api_key"},
    }
    _write(dst_path, payload)
    return dst_path


def import_all(src_path: str, include_settings: bool = True) -> Dict[str, Any]:
    data = _read(src_path, None)
    if not data:
        raise ValueError("文件读取失败或不是有效的配置包")
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    for path in (config.ACCOUNTS_FILE, config.SKILLS_USER_FILE,
                 config.FORBIDDEN_USER_FILE, config.SETTINGS_FILE):
        if os.path.exists(path):
            shutil.copy(path, f"{path}.bak.{ts}")
    if "accounts" in data:
        save_accounts(data["accounts"])
    if data.get("skills_user"):
        _write(config.SKILLS_USER_FILE, data["skills_user"])
    if data.get("forbidden_user"):
        _write(config.FORBIDDEN_USER_FILE, data["forbidden_user"])
    if include_settings and data.get("settings"):
        s = load_settings()
        s.update(data["settings"])
        save_settings(s)
    return data


def backup_now() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(config.DATA_DIR, f"backup_{ts}.json")
    return export_all(dst)


# ================================================================ 操作日志
def log(msg: str) -> None:
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        line = f"[{now()}] {msg}\n"
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def read_log(tail: int = 300) -> List[str]:
    if not os.path.exists(config.LOG_FILE):
        return []
    try:
        with open(config.LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-tail:]
    except Exception:
        return []
