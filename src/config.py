"""全局配置与路径常量。兼容开发态与 PyInstaller 冻结态。"""
import os
import sys

APP_NAME = "DragonFlow 一条龙"
APP_NAME_EN = "DragonFlow"
APP_SUBTITLE = "AI 全媒体内容智能分发平台"
APP_VERSION = "1.7.0"

MAX_ACCOUNTS_PER_PLATFORM = 20

# ---------------------------------------------------------------- 资源路径
_BASE = os.path.dirname(os.path.abspath(__file__))          # .../src
if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    _cands = [
        getattr(sys, "_MEIPASS", None),
        os.path.join(_exe_dir, "_internal"),
        _exe_dir,
    ]
    RESOURCE_BASE = next(
        (c for c in _cands if c and os.path.isdir(os.path.join(c, "assets"))),
        _cands[0],
    )
else:
    RESOURCE_BASE = _BASE

ASSETS_DIR = os.path.join(RESOURCE_BASE, "assets")
PLATFORMS_FILE = os.path.join(ASSETS_DIR, "platforms.json")
SKILLS_FILE = os.path.join(ASSETS_DIR, "skills.json")
FORBIDDEN_FILE = os.path.join(ASSETS_DIR, "forbidden_words.json")
ADAPTERS_DIR = os.path.join(ASSETS_DIR, "adapters")
APP_ICON = os.path.join(ASSETS_DIR, "app.ico")


# ---------------------------------------------------------------- 数据路径
def user_data_base() -> str:
    """跨平台用户数据根目录。"""
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    if os.name == "nt":
        return os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _data_dir() -> str:
    d = os.path.join(user_data_base(), APP_NAME_EN)
    os.makedirs(d, exist_ok=True)
    return d


DATA_DIR = _data_dir()
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SKILLS_USER_FILE = os.path.join(DATA_DIR, "skills_user.json")
PLATFORMS_USER_FILE = os.path.join(DATA_DIR, "platforms_user.json")   # 用户自定义平台
LIBRARY_FILE = os.path.join(DATA_DIR, "library.json")
RECORDS_FILE = os.path.join(DATA_DIR, "records.json")
FORBIDDEN_USER_FILE = os.path.join(DATA_DIR, "forbidden_user.json")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")     # 每账号一个浏览器 Profile
LIBRARY_DIR = os.path.join(DATA_DIR, "library")       # 素材文件
SKILLS_DIR = os.path.join(DATA_DIR, "skills")         # 上传的 Skill 包（含附件）
OUTPUT_DIR = os.path.join(DATA_DIR, "output")         # pipeline 产出的图片 / 视频
LOG_FILE = os.path.join(DATA_DIR, "dragonflow.log")
SHOTS_DIR = os.path.join(DATA_DIR, "fail-shots")      # 填充失败截图


def profile_path(aid: str) -> str:
    """某账号的独立浏览器配置目录（Cookie / 登录态 / 缓存）。

    不同账号目录互不相通 → 同设备多账号不串号。
    同一账号在本平台各后台之间共享 → 一次登录，全站互通。
    """
    p = os.path.join(PROFILES_DIR, aid)
    os.makedirs(p, exist_ok=True)
    return p


def library_path(*parts: str) -> str:
    p = os.path.join(LIBRARY_DIR, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def shots_path(name: str) -> str:
    os.makedirs(SHOTS_DIR, exist_ok=True)
    return os.path.join(SHOTS_DIR, name)


def skill_pack_dir(slug: str) -> str:
    """某个上传 Skill 包的解包目录。"""
    p = os.path.join(SKILLS_DIR, slug)
    os.makedirs(p, exist_ok=True)
    return p


def output_path(*parts: str) -> str:
    p = os.path.join(OUTPUT_DIR, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


# ---------------------------------------------------------------- 默认设置
DEFAULT_SETTINGS = {
    "provider": "deepseek",
    "api_key": "",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-flash",   # 接口 ID（不是官网显示的 DeepSeek-V4.1-Flash）；也支持读图
    "temperature": 0.8,
    "max_tokens": 3000,
    "publish_confirm": True,       # 一键发布前需人工确认
    "publish_interval": 8,         # 平台间发布间隔（秒）
    "daily_limit": 10,             # 单账号单日发布上限
    "hardware_accel": False,       # 默认软件渲染，兼容老机器
    "sidebar_width": 248,
}
