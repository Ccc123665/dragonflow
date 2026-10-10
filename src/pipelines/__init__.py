"""Pipeline 注册表。

新增一条内容流水线，只要在本目录建一个模块、写一个 Pipeline 子类、
用 @register 装饰，再到 assets/skills.json 加一条 kind="pipeline" 的模板即可。
"""
from .base import Ctx, Input, Pipeline, all_pipelines, get, keys, register

# 触发注册：import 即注册
from . import gzh_to_xhs     # noqa: E402,F401
from . import gzh_to_xhs_magazine  # noqa: E402,F401  ← 依赖 gzh_to_xhs，排它后面
from . import xhs_video      # noqa: E402,F401
from . import multi_platform # noqa: E402,F401   ← 依赖 gzh_to_xhs / xhs_video
from . import gzh_to_both    # noqa: E402,F401   ← 依赖上面两条，必须排后面

__all__ = ["Ctx", "Input", "Pipeline", "register", "get",
           "all_pipelines", "keys"]
