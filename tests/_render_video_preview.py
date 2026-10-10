# -*- coding: utf-8 -*-
"""临时脚本：渲染视频五场景 × 两主题的静态预览帧（p=0.9 全元素出现）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image  # noqa: E402
from pipelines.xhs_video import VIDEO_THEMES, _bg, _draw_scene  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "_video_preview")
os.makedirs(OUT, exist_ok=True)

SCENES = [
    ("cover", dict(type="cover", tag="考情速览",
                   title="2026国考报名全攻略",
                   sub="招录 3.97 万人 · 10月15日截止")),
    ("points", dict(type="points", title="三个关键点",
                    items=["全程电脑作答", "行测申论连考", "输入法只有三种"])),
    ("stats", dict(type="stats", title="报名数据一览",
                   stats=[["2046", "人", "中央机关招录规模"],
                          ["77:1", "", "平均竞争比"],
                          ["182万+", "", "报名总人数"]])),
    ("text", dict(type="text", title="温馨提示",
                  text="报名截止时间为10月15日18:00，逾期不再补报，考生请合理安排时间。")),
    ("end", dict(type="end", title="关注我",
                 cta="每天分享公考干货")),
]

for theme_key in VIDEO_THEMES:
    th = VIDEO_THEMES[theme_key]
    for i, (name, scene) in enumerate(SCENES):
        bg = _bg(i, th=th)
        img = _draw_scene(bg, scene, 0.9, th=th)
        path = os.path.join(OUT, f"{theme_key}_{name}.png")
        img.save(path)
        print("saved", path)
