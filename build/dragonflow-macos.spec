# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller macOS 打包配置（生成 DragonFlow.app）。

工作目录必须为「项目根」（本文件所在目录的上一级，spec 用 cwd 定位源码）：
    python -m PyInstaller --noconfirm build/dragonflow-macos.spec

产物：dist/DragonFlow.app

与 Windows spec 的差异
  · macOS 用 BUNDLE 包成 .app：EXE 走 onedir（exclude_binaries=True）+ COLLECT + BUNDLE
  · 图标用 .icns（由 src/assets/app.png 现场生成，缺省则用系统默认图标）
  · 不开 UPX：macOS 上压缩会破坏代码签名 / Gatekeeper 校验
  · 额外补齐 QtWebEngineCore.framework 的资源与多语言包 —— macOS 上
    PyQt6-WebEngine 以 framework 形式分发，官方 hook 偶有漏收，缺了会白屏
  · 数据目录由 config.py 按平台分流（~/Library/Application Support/DragonFlow）

⚠️ PyInstaller 不能跨平台编译：本文件只能在 macOS 上执行。
"""
import os

block_cipher = None

ROOT = os.getcwd()
SRC = os.path.join(ROOT, "src")
ASSETS = os.path.join(SRC, "assets")
ICNS = os.path.join(ASSETS, "app.icns")
ICON = ICNS if os.path.exists(ICNS) else None

APP_NAME = "DragonFlow"
APP_VER = "1.7.0"


def _qt6_dir():
    """定位 PyQt6 自带的 Qt6 目录（收集 WebEngine framework 资源用）。"""
    try:
        import PyQt6
        return os.path.join(os.path.dirname(PyQt6.__file__), "Qt6")
    except Exception:
        return None


QT6 = _qt6_dir()


def _collect(src_dir, dest_dir, keep=None):
    """递归收集目录内文件，保持相对结构。"""
    out = []
    if not os.path.isdir(src_dir):
        return out
    for cur, _dirs, files in os.walk(src_dir):
        for fn in files:
            if keep is not None and not keep(fn):
                continue
            src = os.path.join(cur, fn)
            rel = os.path.relpath(src, src_dir)
            out.append((src, os.path.join(dest_dir, rel)))
    return out


extra_datas = []
if QT6 and os.path.isdir(QT6):
    # ---- macOS 专用：QtWebEngineCore.framework 的资源与多语言包 ----
    # PyInstaller 自带 hook 通常已处理，这里做一次补充收集；
    # 后面有按目标路径去重，重复条目不会进包。
    _FW = os.path.join(QT6, "lib", "QtWebEngineCore.framework")
    _FW_A = os.path.join(_FW, "Versions", "A")
    for _base in (_FW_A, _FW):
        if os.path.isdir(_base):
            extra_datas += _collect(
                os.path.join(_base, "Resources"),
                os.path.join("PyQt6", "Qt6", "lib", "QtWebEngineCore.framework",
                             "Versions", "A", "Resources"),
                keep=lambda fn: not fn.endswith(".debug.pak")
                and not fn.endswith(".debug.bin"),
            )
            break

    extra_datas += _collect(
        os.path.join(QT6, "translations", "qtwebengine_locales"),
        os.path.join("PyQt6", "Qt6", "translations", "qtwebengine_locales"),
    )


a = Analysis(
    [os.path.join(SRC, "main.py")],
    pathex=[SRC],
    binaries=[],
    datas=[(ASSETS, "assets")] + extra_datas,
    hiddenimports=[
        "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtNetwork",
        "PyQt6.QtWebChannel", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineCore",
        # 内容流水线
        "pipelines", "pipelines.base", "pipelines.kit_draw",
        "pipelines.gzh_to_xhs", "pipelines.xhs_video", "pipelines.multi_platform",
        "docx",
        "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont", "PIL.ImageFilter",
        "requests", "urllib3", "certifi", "idna", "charset_normalizer",
        "edge_tts", "aiohttp", "multidict", "yarl", "frozenlist", "aiosignal",
        "attrs",
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


# ---- 瘦身：剔除调试资源、末两段同名的重复错误条目、按目标路径去重 ----
def _is_garbage(dest: str) -> bool:
    low = dest.lower()
    if low.endswith((".debug.pak", ".debug.bin")):
        return True
    parts = low.replace("\\", "/").split("/")
    return len(parts) >= 2 and parts[-1] == parts[-2]


for _toc_name in ("datas", "binaries"):
    _seen = set()
    _clean = []
    for _d in getattr(a, _toc_name):
        _dest = _d[0]
        if _is_garbage(_dest) or _dest in _seen:
            continue
        _seen.add(_dest)
        _clean.append(_d)
    setattr(a, _toc_name, _clean)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=APP_NAME + ".app",
    icon=ICON,
    bundle_identifier="app.dragonflow.desktop",
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": APP_VER,
        "CFBundleVersion": APP_VER,
        "LSMinimumSystemVersion": "11.0",
        "NSAppleEventsUsageDescription": "用于在应用内浏览器中处理链接跳转",
        "NSCameraUsageDescription": "站内上传图片时可能需要调用摄像头",
        "NSMicrophoneUsageDescription": "站内录制视频时可能需要调用麦克风",
    },
)
