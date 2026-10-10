#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由 src/assets/app.png 生成 macOS 图标集（build/icon.iconset/）。

只在 macOS 上跑：生成后由 iconutil 合成 .icns：
    python make_icns.py
    iconutil -c icns build/icon.iconset -o src/assets/app.icns

项目根是自动向上找的（哪个目录里有 src/assets/app.png 就是根），
所以本脚本放在 `项目根/build/` 还是 `项目根/` 都能正常工作。

源图 256×256，放大到 1024 后按各档尺寸重采样（Lanczos）。
分辨率不是原生 1024，Retina 下会略软，但比系统默认图标强。
"""
import os
import sys

from PIL import Image

# (像素边长, 文件名) —— iconutil 认这套命名
SPECS = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]


def find_root(start: str) -> str:
    """从 start 逐级向上找含 src/assets/app.png 的目录。"""
    cur = os.path.abspath(start)
    for _ in range(6):
        if os.path.exists(os.path.join(cur, "src", "assets", "app.png")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(start)


def main() -> int:
    root = find_root(os.path.dirname(os.path.abspath(__file__)))
    src_png = os.path.join(root, "src", "assets", "app.png")
    out_dir = os.path.join(root, "build", "icon.iconset")

    if not os.path.exists(src_png):
        print(f"[x] 找不到源图：{src_png}", file=sys.stderr)
        return 1

    os.makedirs(out_dir, exist_ok=True)
    master = Image.open(src_png).convert("RGBA").resize((1024, 1024), Image.LANCZOS)
    for size, name in SPECS:
        master.resize((size, size), Image.LANCZOS).save(os.path.join(out_dir, name))

    print(f"[√] 图标集已生成：{out_dir}（{len(SPECS)} 档）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
