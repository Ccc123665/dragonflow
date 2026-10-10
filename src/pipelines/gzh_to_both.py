"""公众号链接 → 小红书图文 + 竖屏短视频（一条链接，两种产出）。

用户的原话：「合起来，输入链接，同时出视频和图文」。

实现上就是把 `gzh_to_xhs` 和 `xhs_video` 串起来：
    抓链接 → 生成文案 → 出 8 张配图 → 拿**同一份文案**拆分镜 → 渲染短视频

为什么做成**一条** pipeline，而不是让用户在工坊里勾两个能力：
    「文案转竖屏短视频」要的输入是「文案」，而用户手上只有一条链接。
    中间那份文案如果靠用户手动复制粘贴，这条链就断了 —— 那就不是「一次输入」。

耗时上这两步是叠加的：抓取 + 出图约 60-150 秒，渲染视频约成片时长的 4 倍。
中途可以点「停止」，两步都会中断。
"""
from typing import Any, Dict, List

from pipelines.base import Ctx, Input, Pipeline, register
from pipelines.gzh_to_xhs import GzhToXhs
from pipelines.xhs_video import VOICES, XhsVideo


@register
class GzhToBoth(Pipeline):
    key = "gzh_to_both"
    name = "公众号链接转图文 + 短视频"
    desc = "贴一个公众号链接，一次产出小红书图文（文案 + 配图）和一条 9:16 竖屏短视频"
    note = ("耗时是两条流水线之和：抓取 + 出图约 60-150 秒，"
            "渲染视频约为成片时长的 4 倍。建议先拿一篇短文试一次。\n"
            "公众号有反爬，遇到「环境异常」改用「手动粘贴正文」。\n"
            "「读原文配图」需要当前模型能读图（deepseek-flash 可以，deepseek-v4-pro 不行）。")
    platform = "xhs"
    content_type = "图文 + 视频"
    icon = "sparkle"
    # 两份产出都摆进来：图文那半边 + 视频那半边
    fields = ["title", "body", "topics", "cover", "image_hint", "shot_hint"]
    outputs = ["小红书文案", "8 张 1080×1440 配图", "9:16 竖屏短视频（mp4）"]

    def inputs(self) -> List[Input]:
        # 图文那半边的输入（补充要求统一放在最后，所以这里先摘掉）
        base = [i for i in GzhToXhs().inputs() if i.key != "extra"]
        # 视频那半边的输入，去掉三个：
        #   title / body —— 由抓取那一步产生，不该让用户填第二遍
        #   extra        —— 两边共用一个补充要求
        video = [i for i in XhsVideo().inputs()
                 if i.key not in ("title", "body", "extra")]
        return base + video + [
            Input("extra", "补充要求", "textarea", required=False, rows=2,
                  placeholder="例如：面向在职备考的上班族，语气轻松一点",
                  help="这一条会同时用于文案生成和分镜生成"),
        ]

    def run(self, values: Dict[str, str], ctx: Ctx) -> Dict[str, Any]:
        # ---- 第一步：抓链接 → 文案 → 出图（复用 gzh_to_xhs 的全部逻辑）
        ctx.progress(0.02, "第一步：抓取原文并生成文案")
        res = GzhToXhs().run(values, ctx) or {}
        ctx.check()

        body = (res.get("body") or "").strip()
        if not body:
            raise ValueError("图文那一步没有产出正文，短视频没法继续")

        # ---- 第二步：拿**同一份**文案去拆分镜、渲染视频
        ctx.progress(0.6, "第二步：用同一份文案拆分镜、渲染短视频")
        v = dict(values)
        v["title"] = res.get("title") or ""
        v["body"] = body
        vres = XhsVideo().run(v, ctx) or {}

        out: Dict[str, Any] = dict(res)
        out["shot_hint"] = vres.get("shot_hint") or ""
        # 标题以图文那一步的为准：两边如果各写一个，用户会不知道该用哪个
        out["_artifacts"] = list(ctx.artifacts)
        return out
