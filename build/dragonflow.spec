# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（单文件 EXE）。

构建（必须在项目根目录执行，spec 用 cwd 定位）：
    python -m PyInstaller --noconfirm build/dragonflow.spec

注意：不要加 --clean。清理上千文件在受限环境下会触发删除拦截导致构建失败，
      需要重来时先把 build/dragonflow 与 dist/DragonFlow 改名即可。

注意：ffmpeg 不要手动往 binaries= 里塞 —— pyinstaller-hooks-contrib 自带的
      imageio_ffmpeg 钩子会把整个 binaries/ 目录当 datas 收进去；手动再收一份
      会在 PKG 里生成「同名文件被当目录」的嵌套条目
      （imageio_ffmpeg/binaries/ffmpeg-….exe/ffmpeg-….exe），
      单文件 EXE 解压时必然报 Failed to extract，整个应用打不开。
"""
import os

block_cipher = None

ROOT = os.getcwd()
SRC = os.path.join(ROOT, "src")


a = Analysis(
    [os.path.join(SRC, "main.py")],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(SRC, "assets"), "assets"),
    ],
    hiddenimports=[
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebChannel",
        "PyQt6.QtNetwork",
        # 内容流水线
        "pipelines", "pipelines.base", "pipelines.kit_draw",
        "pipelines.gzh_to_xhs", "pipelines.xhs_video",
        "pipelines.multi_platform", "docx",
        "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.ImageFilter",
        "requests", "urllib3", "certifi", "idna", "charset_normalizer",
        "edge_tts", "aiohttp", "multidict", "yarl", "frozenlist", "aiosignal",
        "async_timeout", "attrs",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc_data", "test",
        "PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.Qt3DCore",
        "PyQt6.QtMultimedia", "PyQt6.QtBluetooth", "PyQt6.QtDesigner",
        # 只要 imageio-ffmpeg，不要整个 imageio（体积差一个量级）
        "imageio", "matplotlib", "numpy", "scipy", "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 剔除调试包与重复条目，避免体积虚胖
_clean_datas = []
_seen = set()
for d in a.datas:
    dest = d[0]
    if dest.endswith(".debug.pak"):
        continue
    if dest in _seen:
        continue
    _seen.add(dest)
    _clean_datas.append(d)
a.datas = _clean_datas

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DragonFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # exe 文件本身的图标（任务栏 / 资源管理器里显示的那个）
    icon=os.path.join(SRC, "assets", "app.ico"),
)
