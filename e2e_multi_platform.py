# -*- coding: utf-8 -*-
"""multi_platform 流水线端到端实测（无 GUI，读正式设置里的模型配置）。

用法：
    df-python e2e_multi_platform.py [选题] [scope]
scope 缺省跑全部（图文+文章+视频）。
"""
import json
import os
import sys
import time
import traceback

SRC = r"J:/AI/AI全媒体矩阵内容分发平台/DragonFlow/src"
sys.path.insert(0, SRC)

import config  # noqa: E402

t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:6.1f}s][LOG] {m}", flush=True)


def prog(p, m=""):
    print(f"[{time.time() - t0:6.1f}s][{int(p * 100):3d}%] {m}", flush=True)


def main():
    settings_file = os.path.join(os.environ["APPDATA"], "DragonFlow", "settings.json")
    with open(settings_file, encoding="utf-8") as f:
        settings = json.load(f)
    print(f"模型：{settings.get('provider')} / {settings.get('model')}", flush=True)

    from pipelines.base import Ctx, get
    from pipelines import multi_platform  # noqa: F401  触发注册

    pipe = get("multi_platform")
    topic = sys.argv[1] if len(sys.argv) > 1 else "广东选调机考的科普，面向2027届应届生"
    scope = sys.argv[2] if len(sys.argv) > 2 else "全部（图文+文章+视频）"
    values = {
        "topic": topic,
        "scope": scope,
        "persona": "",
        "audience": "",
        "pages": "8",
        "voice": "女声 · 亲和",
        "bgm": "轻和声（无版权）",
        "extra": "",
    }
    out_dir = config.output_path("e2e_multi_platform")
    ctx = Ctx(settings, out_dir, log=log, progress=prog)
    res = pipe.run(values, ctx)

    print("==== RUN OK ====", flush=True)
    for k, v in res.items():
        if k == "_artifacts":
            print("artifacts:")
            for a in v:
                print("  -", a)
        else:
            s = str(v).replace("\n", " ⏎ ")
            print(f"{k}: {s[:160]}{'...' if len(s) > 160 else ''}")
    print(f"总耗时 {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        print(f"==== RUN FAILED: {e} ====", flush=True)
        sys.exit(1)
