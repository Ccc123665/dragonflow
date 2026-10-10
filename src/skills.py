"""Skill 模板引擎：模板库管理 + Prompt 组装 + 变量槽位池。

设计要点
  · 内置模板 builtin=True，默认锁定不可删除，但可以「停用」——停用后不出现在生成选项里
  · 用户上传 / 新建的模板 builtin=False，可编辑、可删除
  · 改动一律存到用户目录，不污染内置文件
  · 变量槽位池用于「结构级防同质化」——人设/语气/钩子/案例/CTA 随机组合，
    差异发生在结构层，而不是换几个措辞

模板有两种「形态」（kind 字段）：
  · prompt   —— 一次大模型调用产出结构化字段（默认，也是内置模板的形态）
  · pipeline —— 多步骤流程：抓取 / 出图 / 渲染视频等，由 src/pipelines/ 下的运行器执行
  · bundle   —— 上传的 Skill 包（含 SKILL.md 与附件目录），作为「方法论」注入到 prompt 形态里

导入支持以下形态（上传按钮可选文件 / 文件夹 / 压缩包）：
  1. DragonFlow 导出包： {"version":1, "skills":[{...}]}
  2. 裸列表：           [{...}, {...}]
  3. 单个模板对象：      {"name":"...", "platform":"xhs", "prompt":"..."}
  4. Markdown / 文本：  头部 --- name: xx / platform: xhs --- 之后整段作为 prompt
  5. 文件夹：            含 SKILL.md → 识别为 Skill 包；否则递归导入里面的模板文件
  6. 压缩包 .zip：       解包后按文件夹规则处理
"""
import copy
import json
import os
import random
import re
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import config
import store

_ORDER = ["persona", "audience", "hook", "tone", "case", "cta"]

# 字段别名 → 内部字段名，尽量把用户五花八门的写法收敛到统一结构
_FIELD_ALIAS = {
    "title": "title", "标题": "title",
    "body": "body", "content": "body", "正文": "body", "内容": "body",
    "topics": "topics", "tags": "topics", "话题": "topics", "标签": "topics",
    "cover": "cover", "封面": "cover", "封面文案": "cover",
    "image_hint": "image_hint", "images": "image_hint", "配图": "image_hint",
    "hook": "hook", "钩子": "hook", "开头钩子": "hook",
    "cta": "cta", "结尾": "cta", "结尾引导": "cta",
    "shot_hint": "shot_hint", "分镜": "shot_hint", "分镜提示": "shot_hint",
    "digest": "digest", "摘要": "digest",
}

_PLATFORM_ALIAS = {
    "小红书": "xhs", "xhs": "xhs", "xiaohongshu": "xhs", "red": "xhs",
    "抖音": "douyin", "douyin": "douyin", "dy": "douyin",
    "视频号": "sph", "sph": "sph", "channels": "sph", "wechat_channels": "sph",
    "公众号": "gzh", "gzh": "gzh", "mp": "gzh", "wechat": "gzh",
    "头条": "toutiao", "头条号": "toutiao", "toutiao": "toutiao", "tt": "toutiao",
}


# ---------------------------------------------------------------- 读取
def load_builtin() -> Dict[str, Any]:
    try:
        with open(config.SKILLS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"version": 1, "variables": {}, "skills": []}


def load_user() -> Dict[str, Any]:
    if not os.path.exists(config.SKILLS_USER_FILE):
        return {"skills": {}, "deleted": [], "disabled": []}
    try:
        with open(config.SKILLS_USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"skills": {}, "deleted": [], "disabled": []}
    data.setdefault("skills", {})
    data.setdefault("deleted", [])
    data.setdefault("disabled", [])
    return data


def save_user(data: Dict[str, Any]) -> None:
    store._write(config.SKILLS_USER_FILE, data)


def all_skills(include_disabled: bool = False) -> List[Dict[str, Any]]:
    """内置 + 用户修改 + 用户新增，合并后的完整列表。"""
    builtin = load_builtin()
    user = load_user()
    out: List[Dict[str, Any]] = []
    for s in builtin.get("skills", []):
        s = copy.deepcopy(s)
        ov = user["skills"].get(s["id"])
        if ov:
            s.update({k: v for k, v in ov.items() if k not in ("id", "builtin")})
        out.append(s)
    for sid, s in user["skills"].items():
        if s.get("builtin"):
            continue
        if sid in {x["id"] for x in out}:
            continue
        out.append(copy.deepcopy(s))
    deleted = set(user.get("deleted", []))
    out = [s for s in out if s["id"] not in deleted]
    if not include_disabled:
        disabled = set(user.get("disabled", []))
        out = [s for s in out if s["id"] not in disabled]
    return out


def get_skill(sid: str) -> Optional[Dict[str, Any]]:
    for s in all_skills():
        if s["id"] == sid:
            return s
    return None


# ---------------------------------------------------------------- 内容工坊的能力来源
# 工坊里列**「真能干活的」**能力 —— 也就是 `bundle`（上传的 Skill 包）
# 和 `pipeline`（多步骤流水线：抓网页 / 出图 / 渲染视频）。
#
# 为什么不列 `prompt`（单次模型调用型模板）：用户明确说
# 「只要 skill，不要其他内置」—— 那 6 个 prompt 模板是随软件发的基础样板，
# 只产文字、干不了抓取出图这类实事，不占工坊的位置。用户的定义是
# 「那三条流水线就算是我上传的 skill」。
#
# 这些能力仍然都在「设置 → 内容模板 Skill」里可查看 / 停用 / 编辑 / 恢复。
# 想再放开（比如把 prompt 模板也放回工坊），改这一个元组就行。
STUDIO_KINDS: Tuple[str, ...] = ("bundle", "pipeline")


def studio_skills(include_disabled: bool = False) -> List[Dict[str, Any]]:
    """内容工坊里可选的能力：只保留 STUDIO_KINDS 里的形态。

    筛选行（形态 / 平台）的选项也从这里算，所以工坊里出现的每个勾选框
    背后都至少有一条真能选的能力 —— 不会出现「勾了筛不出东西」的空选项。
    """
    return [s for s in all_skills(include_disabled=include_disabled)
            if kind_of(s) in STUDIO_KINDS]


def skills_of(platform_key: str) -> List[Dict[str, Any]]:
    """某平台可用的模板（停用的不算）。"""
    return [s for s in all_skills() if s.get("platform") == platform_key]


def upsert_skill(skill: Dict[str, Any]) -> None:
    """新增或修改一个模板。内置模板的修改也存到用户目录。"""
    user = load_user()
    skill = copy.deepcopy(skill)
    sid = skill.get("id") or store.new_id("sk_")
    skill["id"] = sid
    user["skills"][sid] = skill
    if sid in user.get("deleted", []):
        user["deleted"].remove(sid)
    if sid in user.get("disabled", []):
        user["disabled"].remove(sid)
    save_user(user)
    store.log(f"保存 Skill 模板：{skill.get('name')}")


def delete_skill(sid: str) -> None:
    """删除模板。内置模板允许删除（可用「恢复内置模板」找回）。"""
    user = load_user()
    pack = (user["skills"].get(sid) or {}).get("pack_dir", "")
    user["skills"].pop(sid, None)
    if sid not in user.get("deleted", []):
        user["deleted"].append(sid)
    if sid in user.get("disabled", []):
        user["disabled"].remove(sid)
    save_user(user)
    # 上传的 Skill 包连同附件一起删掉，别在磁盘上留垃圾
    if pack and os.path.isdir(pack) and os.path.normpath(pack).startswith(
            os.path.normpath(config.SKILLS_DIR)):
        shutil.rmtree(pack, ignore_errors=True)
    store.log(f"删除 Skill 模板：{sid}")


def set_disabled(sid: str, disabled: bool) -> None:
    """停用 / 启用一个模板。停用后不出现在生成选项里，但保留配置。"""
    user = load_user()
    cur = set(user.get("disabled", []))
    if disabled:
        cur.add(sid)
    else:
        cur.discard(sid)
    user["disabled"] = sorted(cur)
    save_user(user)


def is_disabled(sid: str) -> bool:
    return sid in set(load_user().get("disabled", []))


def is_builtin(sid: str) -> bool:
    return any(s["id"] == sid for s in load_builtin().get("skills", []))


def reset_skill(sid: str) -> None:
    """把内置模板恢复为出厂内容。"""
    user = load_user()
    user["skills"].pop(sid, None)
    if sid in user.get("deleted", []):
        user["deleted"].remove(sid)
    if sid in user.get("disabled", []):
        user["disabled"].remove(sid)
    save_user(user)


def restore_builtins() -> int:
    """把被删掉 / 停用的内置模板全部恢复。"""
    user = load_user()
    builtin_ids = {s["id"] for s in load_builtin().get("skills", [])}
    user["deleted"] = [i for i in user.get("deleted", []) if i not in builtin_ids]
    user["disabled"] = [i for i in user.get("disabled", []) if i not in builtin_ids]
    save_user(user)
    return len(builtin_ids)


# ---------------------------------------------------------------- 变量槽位
def variable_pool() -> Dict[str, List[str]]:
    pool = load_builtin().get("variables", {})
    return {k: list(v) for k, v in pool.items()}


def pick_slots(seed: Optional[int] = None, avoid: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """随机抽一组变量组合，尽量避开上一次用过的值。"""
    rnd = random.Random(seed)
    pool = variable_pool()
    avoid = avoid or {}
    out: Dict[str, str] = {}
    for key in _ORDER:
        vals = pool.get(key) or []
        if not vals:
            out[key] = ""
            continue
        cands = [v for v in vals if v != avoid.get(key)] or vals
        out[key] = rnd.choice(cands)
    return out


# ---------------------------------------------------------------- Prompt 组装
def build_prompt(skill: Dict[str, Any], topic: str, persona: str = "",
                 extra: str = "", slots: Optional[Dict[str, str]] = None) -> tuple[str, str]:
    """返回 (system, user)。"""
    slots = slots or pick_slots()
    mapping = {
        "topic": topic.strip(),
        "persona": persona.strip() or slots.get("persona", ""),
        "audience": slots.get("audience", ""),
        "hook": slots.get("hook", ""),
        "tone": slots.get("tone", ""),
        "case": slots.get("case", ""),
        "cta": slots.get("cta", ""),
        "extra": extra.strip() or "无",
    }
    system = (skill.get("system") or "").strip()
    user = skill.get("prompt") or ""
    for k, v in mapping.items():
        user = user.replace("{" + k + "}", v)
    # 清掉模板里没被替换的占位符
    import re
    user = re.sub(r"\{[a-z_]+\}", "", user)
    return system, user


# ---------------------------------------------------------------- 导入
def _norm_fields(raw: Any) -> List[str]:
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()]
    if not isinstance(raw, list):
        return []
    out = []
    for f in raw:
        key = _FIELD_ALIAS.get(str(f).strip().lower(), _FIELD_ALIAS.get(str(f).strip(), ""))
        if key and key not in out:
            out.append(key)
    return out


def _norm_platform(raw: Any, default: str = "xhs") -> str:
    if not raw:
        return default
    key = _PLATFORM_ALIAS.get(str(raw).strip().lower(), _PLATFORM_ALIAS.get(str(raw).strip(), ""))
    return key or default


def normalize_skill(obj: Dict[str, Any], fallback_platform: str = "xhs") -> Optional[Dict[str, Any]]:
    """把各种写法的模板对象收敛成内部结构。"""
    if not isinstance(obj, dict):
        return None
    # 兼容把内容包在 skill / template 字段里的写法
    for k in ("skill", "template", "data"):
        if isinstance(obj.get(k), dict) and not obj.get("prompt"):
            obj = {**obj, **obj[k]}

    name = str(obj.get("name") or obj.get("title") or obj.get("id") or "").strip()
    prompt = obj.get("prompt") or obj.get("template") or obj.get("user_prompt") or ""
    if not isinstance(prompt, str):
        prompt = str(prompt)
    if not name and not prompt.strip():
        return None
    if not name:
        name = prompt.strip().split("\n")[0][:20] or "未命名模板"

    fields = _norm_fields(obj.get("fields") or obj.get("output_fields")) or \
        ["title", "body", "topics"]

    limits = obj.get("limits") if isinstance(obj.get("limits"), dict) else {}
    limits = {k: int(v) for k, v in limits.items() if str(v).isdigit()}

    return {
        "id": str(obj.get("id") or "").strip() or store.new_id("sk_"),
        "name": name[:40],
        "platform": _norm_platform(obj.get("platform"), fallback_platform),
        "content_type": str(obj.get("content_type") or obj.get("type") or "图文")[:20],
        "desc": str(obj.get("desc") or obj.get("description") or obj.get("说明") or "")[:200],
        "fields": fields,
        "limits": limits,
        "system": str(obj.get("system") or obj.get("system_prompt") or "").strip(),
        "prompt": prompt.strip(),
        "kind": _norm_kind(obj.get("kind"), obj.get("pipeline")),
        "pipeline": str(obj.get("pipeline") or "").strip(),
        "pack_dir": str(obj.get("pack_dir") or "").strip(),
        "builtin": False,
        "locked": False,
    }


def _norm_kind(kind: Any, pipeline: Any = None) -> str:
    """把各种写法收敛到 prompt / pipeline / bundle。"""
    k = str(kind or "").strip().lower()
    if k in ("pipeline", "flow", "工作流", "流程"):
        return "pipeline"
    if k in ("bundle", "pack", "包", "skill包"):
        return "bundle"
    if k in ("prompt", "template", "模板", ""):
        return "pipeline" if str(pipeline or "").strip() else "prompt"
    return "prompt"


def kind_of(skill: Dict[str, Any]) -> str:
    """读一个模板的形态，老数据没有 kind 字段时按 prompt 处理。"""
    if not skill:
        return "prompt"
    return skill.get("kind") or ("pipeline" if skill.get("pipeline") else "prompt")


def is_pipeline(skill: Dict[str, Any]) -> bool:
    return kind_of(skill) == "pipeline"


# ---------------------------------------------------------------- 输入 / 输出
# 「这个能力要什么、产出什么」—— 内容工坊照着它渲染表单和卡片。
# 有了这个声明，工坊就不需要「先勾平台、再挑模板、再填选题」那套猜测式界面了：
# 直接把能力摆出来，用户看得到「输入什么 → 输出什么」，选完填完就能跑。
def inputs_of(skill: Dict[str, Any]) -> List[Any]:
    """这个模板需要用户填什么。

    pipeline 型：由运行器自己声明（`Pipeline.inputs()`）—— 链接 / 文案 / 页数…
    prompt / bundle 型：固定三件套 —— 选题、账号人设、补充要求。
    """
    if not skill:
        return []
    from pipelines.base import Input
    if is_pipeline(skill):
        pipe = pipe_of(skill)
        return list(pipe.inputs()) if pipe else []
    return [
        Input("topic", "选题", "textarea", required=True, rows=3,
              placeholder="要写什么，例如：省考行测数量关系怎么提速"),
        Input("persona", "账号人设", "text", required=False,
              placeholder="不指定就由 AI 按平台惯例自由发挥"),
        Input("extra", "补充要求", "textarea", required=False, rows=2,
              placeholder="例如：重点讲做题顺序，控制在 800 字内"),
    ]


def outputs_of(skill: Dict[str, Any]) -> List[str]:
    """这个模板产出什么（给人看的短标签，显示在能力卡片上）。"""
    if not skill:
        return []
    if is_pipeline(skill):
        pipe = pipe_of(skill)
        if pipe:
            return pipe.output_labels()
    labels = [field_label(f) for f in (skill.get("fields") or [])]
    return ["、".join(labels[:3])] if labels else ["文案"]


def pipe_of(skill: Dict[str, Any]):
    try:
        import pipelines as _PIPE
        return _PIPE.get(str(skill.get("pipeline") or ""))
    except Exception:
        return None


def can_run(skill: Dict[str, Any]) -> bool:
    """这个模板现在能不能真的跑起来（有没有 err 级问题）。"""
    return not any(i.get("level") == "err" for i in check_skill(skill))


# ---------------------------------------------------------------- 可用性自检
# 「这个模板能不能真的干活」—— 用户上传的 skill 必须过这一关。
# 最糟的体验是：装上了、界面上也选得到，一点生成却报「缺少运行器」，
# 或者只得到一段缺了动作的文本，还不知道为什么。
_ACTION_HINTS = (
    "抓取", "爬取", "下载", "截图", "渲染", "出图", "生成图片", "配图生成",
    "合成", "剪辑", "编码", "ffmpeg", "上传文件", "扫码登录", "访问链接",
    "读取本地", "写入文件", "调用接口", "打开网页", "驱动浏览器",
)


def check_skill(skill: Dict[str, Any]) -> List[Dict[str, str]]:
    """检查一个模板能不能真的跑起来。返回问题列表（空列表 = 没问题）。

    分三档：
      err  —— 点生成必然失败，必须修
      warn —— 能跑，但产出可能不如预期
      info —— 提示性说明，不用改
    """
    if not skill:
        return [{"level": "err", "text": "模板是空的"}]

    out: List[Dict[str, str]] = []
    kind = kind_of(skill)

    # ---- 平台 ----
    try:
        import platforms as _PF
        pk = str(skill.get("platform") or "")
        if pk and not _PF.get(pk):
            out.append({"level": "warn",
                        "text": f"平台「{pk}」不在平台列表里，生成的内容进不了发布工作台"})
    except Exception:
        pass

    # ---- 输出字段 ----
    if not skill.get("fields"):
        out.append({"level": "warn",
                    "text": "没声明输出字段，将按 title / body / topics 兜底"})

    # ---- pipeline 形态：必须有运行器 ----
    if kind == "pipeline":
        pname = str(skill.get("pipeline") or "").strip()
        if not pname:
            out.append({"level": "err",
                        "text": "标了 pipeline 形态，但没写运行器名字"})
            return out
        try:
            import pipelines as _PIPE
            if _PIPE.get(pname) is None:
                out.append({"level": "err",
                            "text": f"找不到运行器 src/pipelines/{pname}.py —— "
                                    f"这个模板点生成会直接失败"})
        except Exception as e:
            out.append({"level": "err", "text": f"加载运行器失败：{e}"})
        return out

    # ---- prompt / bundle 形态：靠一次模型调用 ----
    prompt = str(skill.get("prompt") or "").strip()
    if not prompt:
        out.append({"level": "err",
                    "text": "没有生成指令（prompt 为空），点生成会直接失败"})
    elif len(prompt) < 30:
        out.append({"level": "warn",
                    "text": f"生成指令只有 {len(prompt)} 字，产出可能很泛"})
    elif "{" not in prompt:
        out.append({"level": "info",
                    "text": "生成指令里没有 {topic} 这类占位符，选题不会被传进去"})

    # 关键一条：内容里描述了「要动手」的步骤，但这种形态只能做文本生成
    body = f"{skill.get('system') or ''}\n{prompt}"
    hit = [k for k in _ACTION_HINTS if k in body]
    if hit:
        out.append({"level": "warn",
                    "text": "这个模板描述了需要实际执行的动作（"
                            + "、".join(hit[:5]) + "…），但 prompt / bundle 形态"
                              "只做一次文本生成，那些动作不会真的发生。"
                              "要让它真干活，得给它配一个 pipeline 运行器"
                              "（见 README「四·六」）"})

    if kind == "bundle":
        out.append({"level": "info",
                    "text": "Skill 包形态：SKILL.md 正文会作为方法论注入，"
                            "包里的附件保留在磁盘上，但不会被执行"})
    return out


def audit_all() -> List[tuple]:
    """自检全部模板（含停用的），只返回有问题的：[(skill, [issue, ...]), ...]"""
    out = []
    for s in all_skills(include_disabled=True):
        iss = check_skill(s)
        if iss:
            out.append((s, iss))
    return out


def issue_counts(issues) -> tuple:
    """统计 (err, warn, info)。"""
    e = w = i = 0
    for x in issues or []:
        lv = x.get("level") if isinstance(x, dict) else None
        if lv == "err":
            e += 1
        elif lv == "warn":
            w += 1
        else:
            i += 1
    return e, w, i


# ---------------------------------------------------------------- 目录 / 压缩包
SKILL_FILE_EXTS = (".json", ".md", ".markdown", ".txt")
_SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "__MACOSX", ".venv", "venv"}


def _slug(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", str(text or "").strip()).strip("-")
    return (s or "skill")[:48].lower()


def _parse_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """拆出 --- 头部（YAML 简化版：key: value）与正文。"""
    meta: Dict[str, Any] = {}
    s = text.lstrip("\ufeff \t\r\n")
    if s.startswith("---"):
        parts = s.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line and not line.lstrip().startswith("#"):
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip().strip('"').strip("'")
            return meta, parts[2].strip()
    return meta, text.strip()


def _walk_skill_files(root: str) -> List[str]:
    """递归收集目录下的模板文件，跳过缓存 / 版本控制目录。"""
    out: List[str] = []
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in SKILL_FILE_EXTS:
                out.append(os.path.join(cur, f))
    return out


def _import_pack(src_dir: str, user: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """把一个「Skill 包」目录（含 SKILL.md）搬进 data/skills/ 并登记成模板。

    包内文件全部保留，方便后续查看附件；SKILL.md 的正文作为方法论注入。
    """
    md_path = ""
    for cand in ("SKILL.md", "skill.md", "SKILL.markdown", "README.md"):
        p = os.path.join(src_dir, cand)
        if os.path.isfile(p):
            md_path = p
            break
    if not md_path:
        return None, "目录里没有 SKILL.md"

    with open(md_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    meta, body = _parse_front_matter(raw)

    name = str(meta.get("name") or os.path.basename(os.path.normpath(src_dir)) or "Skill 包")
    sid = "pack_" + _slug(name)
    dest = config.skill_pack_dir(_slug(name))
    # 同 id 重复上传：先清掉旧目录，保证内容是最新的
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
    for entry in os.listdir(src_dir):
        s_path = os.path.join(src_dir, entry)
        d_path = os.path.join(dest, entry)
        try:
            if os.path.isdir(s_path):
                shutil.copytree(s_path, d_path, dirs_exist_ok=True)
            else:
                shutil.copy2(s_path, d_path)
        except Exception:
            pass

    desc = str(meta.get("description") or meta.get("summary") or "").strip()
    if not desc:
        for line in body.splitlines():
            t = line.strip().lstrip("#").strip()
            if t and not t.startswith("---"):
                desc = t[:200]
                break

    # 正文里有「输出 / 产出 / 交付」段落的话，取它作为生成指令，比整篇方法论更贴题
    prompt = _extract_prompt_from_body(body) or _DEFAULT_BUNDLE_PROMPT

    # front matter 里声明了 kind: pipeline + pipeline: xxx 的包，
    # 导入时直接登记成流水线形态 —— SKILL.md 描述「要动手」的 skill
    # 必须这样才真的能干活（见 README「四·六」）。
    # 没声明就维持 bundle：正文作为方法论注入，包里的附件保留但不执行。
    # ⚠ 默认必须显式给 "bundle"：_norm_kind(None) 会收敛成 "prompt"，
    # 而 STUDIO_KINDS 只认 bundle/pipeline —— 那样用户整包导入的 Skill
    # 永远进不了内容工坊（回归抓出：注释说 bundle、实现给 prompt）。
    kind = _norm_kind(meta.get("kind") or "bundle", meta.get("pipeline"))

    skill = {
        "id": sid,
        "name": name[:40],
        "platform": _norm_platform(meta.get("platform")),
        "content_type": str(meta.get("content_type") or "图文")[:20],
        "desc": desc[:200],
        "fields": _norm_fields(meta.get("fields")) or ["title", "body", "topics"],
        "limits": {},
        "system": body[:6000],
        "prompt": prompt,
        "kind": kind,
        "pipeline": str(meta.get("pipeline") or "").strip(),
        "pack_dir": dest,
        "builtin": False,
        "locked": False,
    }
    user["skills"][sid] = skill
    return skill, ""


_DEFAULT_BUNDLE_PROMPT = (
    "请严格按上面给出的方法论，围绕选题「{topic}」产出一套内容。\n\n"
    "【账号人设】{persona}\n【目标人群】{audience}\n【开头方式】{hook}\n"
    "【语气】{tone}\n【素材角度】{case}\n【结尾引导】{cta}\n【补充要求】{extra}\n\n"
    "只输出一个 JSON 对象，字段：{fields}。"
)


def _extract_prompt_from_body(body: str) -> str:
    """从 SKILL.md 正文里捞一段适合当生成指令的文本。"""
    lines = body.splitlines()
    keys = ("输出", "产出", "交付", "格式", "要求")
    start = -1
    for i, ln in enumerate(lines):
        t = ln.strip()
        if t.startswith("#") and any(k in t for k in keys):
            start = i + 1
            break
    if start < 0:
        return ""
    chunk: List[str] = []
    for ln in lines[start:]:
        if ln.strip().startswith("#") and chunk:
            break
        chunk.append(ln)
    text = "\n".join(chunk).strip()
    if len(text) < 20:
        return ""
    if "{topic}" not in text:
        text = "围绕选题「{topic}」，" + text
    if "{extra}" not in text:
        text += "\n\n【补充要求】{extra}"
    return text[:4000]


def _parse_markdown(text: str, filename: str) -> Optional[Dict[str, Any]]:
    """解析 Markdown / 文本模板。

    支持可选头部：
        ---
        name: 小红书爆款笔记
        platform: 小红书
        fields: title,body,topics
        ---
        正文 Prompt ...
    """
    meta, body = _parse_front_matter(text)
    meta.setdefault("name", os.path.splitext(os.path.basename(filename))[0])
    meta["prompt"] = body
    return normalize_skill(meta)


def _read_skill_file(path: str) -> Tuple[List[Dict[str, Any]], str]:
    """读一个文件，返回 (模板列表, 错误信息)。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".markdown", ".txt"):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            s = _parse_markdown(f.read(), path)
        return ([s] if s else []), "" if s else "内容为空"

    if ext != ".json":
        return [], "只支持 .json / .md / .txt"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items: Any = data
    if isinstance(data, dict):
        if isinstance(data.get("skills"), list):
            items = data["skills"]
        elif isinstance(data.get("templates"), list):
            items = data["templates"]
        else:
            items = [data]
    if not isinstance(items, list):
        return [], "文件结构无法识别"

    out = []
    for it in items:
        s = normalize_skill(it)
        if s:
            out.append(s)
    return out, "" if out else "没有解析出任何模板"


# ---------------------------------------------------------------- 压缩包
def _safe_extract_zip(path: str, dest: str) -> int:
    """解包 zip 到 dest，拒绝绝对路径与 .. 穿越，返回解出的文件数。"""
    n = 0
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if name.startswith("/") or ".." in parts:
                continue
            target = os.path.join(dest, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n += 1
    return n


def _import_dir(root: str, user: Dict[str, Any]) -> Tuple[int, List[str]]:
    """导入一个目录：含 SKILL.md 当 Skill 包处理，否则递归导入里面的模板文件。"""
    msgs: List[str] = []
    n = 0

    # 顶层或任意一层有 SKILL.md，就按 Skill 包处理（取最外层那个）
    pack_root = ""
    for cand_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        lower = {f.lower() for f in files}
        if {"skill.md", "skill.markdown", "readme.md"} & lower:
            pack_root = cand_root
            break
    if pack_root:
        skill, err = _import_pack(pack_root, user)
        if skill:
            return 1, msgs
        msgs.append(f"{os.path.basename(root)}：{err}")

    inner = _walk_skill_files(root)
    if not inner:
        msgs.append(f"{os.path.basename(root)}：目录里没有可导入的 .json / .md / .txt")
        return n, msgs
    for path in inner:
        try:
            skills, err = _read_skill_file(path)
        except Exception as e:
            msgs.append(f"{os.path.relpath(path, root)}：{e}")
            continue
        if err:
            msgs.append(f"{os.path.relpath(path, root)}：{err}")
            continue
        for s in skills:
            user["skills"][s["id"]] = s
            n += 1
    return n, msgs


def import_files(paths: List[str]) -> Tuple[int, List[str]]:
    """批量导入模板：文件 / 文件夹 / .zip 压缩包都能收，返回 (成功数量, 提示信息列表)。"""
    if not paths:
        return 0, []
    user = load_user()
    msgs: List[str] = []
    n = 0
    new_ids: List[str] = []
    for path in paths:
        if not os.path.exists(path):
            msgs.append(f"{os.path.basename(path)}：路径不存在")
            continue

        if os.path.isdir(path):
            sub_n, sub_msgs = _import_dir(path, user)
            n += sub_n
            msgs.extend(sub_msgs)
            continue

        if os.path.splitext(path)[1].lower() == ".zip":
            tmp = tempfile.mkdtemp(prefix="df_skill_")
            try:
                got = _safe_extract_zip(path, tmp)
                if not got:
                    msgs.append(f"{os.path.basename(path)}：压缩包里没有文件")
                    continue
                sub_n, sub_msgs = _import_dir(tmp, user)
                n += sub_n
                msgs.extend(sub_msgs)
            except zipfile.BadZipFile:
                msgs.append(f"{os.path.basename(path)}：不是有效的 zip 压缩包")
            except Exception as e:
                msgs.append(f"{os.path.basename(path)}：{e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            continue

        try:
            skills, err = _read_skill_file(path)
        except Exception as e:
            msgs.append(f"{os.path.basename(path)}：{e}")
            continue
        if err:
            msgs.append(f"{os.path.basename(path)}：{err}")
            continue
        for s in skills:
            user["skills"][s["id"]] = s
            new_ids.append(s["id"])
            n += 1

    for sid, s in list(user["skills"].items()):
        if sid in user.get("deleted", []):
            user["deleted"].remove(sid)
        if sid in user.get("disabled", []):
            user["disabled"].remove(sid)
    save_user(user)
    store.log(f"上传 Skill 模板 {n} 个")

    # 导入完立刻自检一遍。用户以为装上了、实际一点就跑不动，
    # 是最糟的体验 —— 所以把「不可用 / 要注意」当场说清楚。
    for sid in new_ids:
        s = user["skills"].get(sid) or {}
        nm = s.get("name") or sid
        for iss in check_skill(s):
            if iss["level"] == "err":
                msgs.append(f"「{nm}」不可用：{iss['text']}")
            elif iss["level"] == "warn":
                msgs.append(f"「{nm}」要注意：{iss['text']}")
    return n, msgs


def import_skills(path: str) -> int:
    """兼容旧调用：导入单个文件。"""
    n, _ = import_files([path])
    return n


# ---------------------------------------------------------------- 导出
def export_skills(path: str, ids: Optional[List[str]] = None) -> str:
    skills = all_skills()
    if ids:
        skills = [s for s in skills if s["id"] in ids]
    payload = {"version": 1, "type": "dragonflow-skills", "skills": skills}
    store._write(path, payload)
    return path


# ---------------------------------------------------------------- 字段工具
def field_label(key: str) -> str:
    return {
        "title": "标题",
        "body": "正文",
        "topics": "话题标签",
        "cover": "封面文案",
        "image_hint": "配图建议",
        "hook": "开头钩子",
        "cta": "结尾引导",
        "shot_hint": "分镜提示",
        "digest": "摘要",
    }.get(key, key)


def normalize_result(raw: dict, skill: Dict[str, Any]) -> Dict[str, Any]:
    """把模型输出规范成 {field: text} 结构，缺失字段补空。"""
    from llm import to_text
    fields = skill.get("fields") or ["title", "body", "topics"]
    out: Dict[str, Any] = {}
    for f in fields:
        out[f] = to_text(raw.get(f, ""))
    # 保留模型多给的字段，便于排查
    for k, v in raw.items():
        if k not in out:
            out[k] = to_text(v)
    return out


def char_count(content: Dict[str, Any]) -> int:
    total = 0
    for k, v in content.items():
        if isinstance(v, str):
            total += len(v)
    return total
