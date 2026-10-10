"""应用内选图器：批次列表 + 缩略图网格，替代 Windows 系统文件对话框。

为什么自己做一个（v1.6 方案 B）：
  一键填充没有预置文件时，以前会弹系统 QFileDialog —— 用户面对的是
  「最近 / 此电脑」的空列表，根本不知道产出目录藏在 %APPDATA% 深处。
  这里直接把 output/ 下最近产出的批次列出来（按时间倒序），点开就是
  缩略图，「用这批」把文件直接交回上传控件 —— 用户全程不用会找文件夹。

对外 API：
    pick_media_files(parent, start_dir="") -> Optional[Tuple[List[str], str]]
        · 返回 None  = 选图器没开起来（没有任何可用批次）→ 调用方自行兜底
        · 返回 (files, dir) = 用户走完了选图流程；files 为空表示取消
"""
import os
from typing import List, Optional, Tuple

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QScrollArea, QVBoxLayout, QWidget,
)

import config
import icons
import theme
from widgets.dialogs import BaseDialog

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")
MEDIA_EXT = IMG_EXT + VIDEO_EXT

THUMB = 112          # 缩略图边长（px）
GRID_COLS = 3        # 每行缩略图数量（配合弹窗宽度）


# ================================================================ 批次扫描
def _media_files(d: str, exts: Optional[tuple] = None) -> List[str]:
    """目录下按文件名排序的媒体文件；exts 缺省为全部媒体扩展名。"""
    exts = tuple(exts) if exts else MEDIA_EXT
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names
            if n.lower().endswith(exts)]


def list_batches(base: str = "", max_depth: int = 3,
                 exts: Optional[tuple] = None, topic: str = "") -> List[dict]:
    """扫 base（默认产出根目录）下所有含媒体文件的子目录。

    exts 传扩展名元组可只认部分媒体（如只要图片：IMG_EXT）——
    给图文挂图时，纯视频批次列出来只会误导。

    topic 给了就把「与内容同题」的批次排最前（目录名按 PF.batch_match_score
    对上主题才算）—— output 下躺着多个选题的批次时，别的题的新批次
    不能排在本题的旧批次前面（真实踩坑：本题 8 张、别的题 26 张混挂）。

    返回批次列表：
        [{"dir": 目录, "mtime": 最新文件时间戳, "files": [文件...],
          "score": 匹配分, "matched": 是否同题}]（仅 topic 时带后两个字段）
    """
    base = base or config.OUTPUT_DIR
    if not os.path.isdir(base):
        return []
    exts = tuple(exts) if exts else MEDIA_EXT
    base_depth = base.rstrip(os.sep).count(os.sep)
    batches: List[dict] = []
    for root, dirs, files in os.walk(base):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
            continue
        hits = _media_files(root, exts)
        if not hits:
            continue
        try:
            m = max(os.path.getmtime(f) for f in hits)
        except OSError:
            continue
        batches.append({"dir": root, "mtime": m, "files": hits})
    if topic:
        import platforms as PF
        for b in batches:
            b["score"] = PF.batch_match_score(
                os.path.basename(b["dir"].rstrip(os.sep)), topic)
            b["matched"] = b["score"] >= PF.TOPIC_MATCH_MIN
        # 同题的排前面（同分内新→旧）；不同题的仍按时间新→旧
        batches.sort(key=lambda b: (b["matched"], b["score"], b["mtime"]),
                     reverse=True)
    else:
        batches.sort(key=lambda b: b["mtime"], reverse=True)
    return batches


def _batch_label(b: dict) -> str:
    """左侧列表条目：时间 + 目录名 + 张数（同题批次带标记）。"""
    import time
    ts = time.strftime("%m-%d %H:%M", time.localtime(b["mtime"]))
    leaf = os.path.basename(b["dir"].rstrip(os.sep)) or b["dir"]
    tag = "（匹配本题）" if b.get("matched") else ""
    return f"{ts} · {len(b['files'])} 个文件{tag}\n{leaf}"


# ================================================================ 缩略图
class Thumb(QFrame):
    """一块缩略图：点一下切换选中。选中 = 主色描边 + 右上角对勾。

    图片用 QImageReader 按 THUMB 尺寸解码（不整张读进内存再缩），
    批次里几十张 1080×1440 的大图也不会卡。
    """

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.checked = True
        self.setFixedSize(THUMB + 12, THUMB + 34)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 2)
        lay.setSpacing(2)

        self.pic = QLabel()
        self.pic.setFixedSize(THUMB, THUMB)
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.pic)

        self.lb_name = QLabel(os.path.basename(path))
        self.lb_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lb_name.setStyleSheet(
            f"background:transparent;{theme.css_font(10.5, 400)}"
            f"color:{theme.TEXT_3};")
        self.lb_name.setFixedWidth(THUMB)
        lay.addWidget(self.lb_name)

        self._badge = QLabel(self.pic)
        self._badge.setFixedSize(20, 20)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(
            f"background:{theme.PRIMARY};border-radius:10px;")
        # 用矢量对勾，不用「✓」字符 —— 自定字体可能缺这个字形（实测渲染成口口）
        self._badge.setPixmap(icons.pixmap("check", "#FFFFFF", 11, 2.6))
        self._badge.move(THUMB - 26, 6)   # 右上角对勾

        if path.lower().endswith(VIDEO_EXT):
            self.pic.setText("视频")
            self.pic.setStyleSheet(
                f"background:{theme.BG_SUNK};border-radius:8px;"
                f"{theme.css_font(13, 600)}color:{theme.TEXT_3};")
        else:
            reader = QImageReader(path)
            # 按原比例缩到 THUMB 以内 —— 直接 setScaledSize(方形) 会拉变形
            src = reader.size()
            if src.isValid():
                reader.setScaledSize(src.scaled(
                    THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio))
            pm = reader.read()
            if pm.isNull():
                self.pic.setText("预览失败")
                self.pic.setStyleSheet(
                    f"background:{theme.BG_SUNK};border-radius:8px;"
                    f"{theme.css_font(12, 400)}color:{theme.TEXT_4};")
            else:
                self.pic.setPixmap(QPixmap.fromImage(pm))
        self.set_checked(True)

    def set_checked(self, on: bool) -> None:
        self.checked = bool(on)
        self._badge.setVisible(self.checked)
        border = f"2px solid {theme.PRIMARY}" if self.checked \
            else f"1px solid {theme.LINE}"
        if self.pic.pixmap() and not self.pic.pixmap().isNull():
            self.pic.setStyleSheet(
                f"background:{theme.BG_SUNK};border:{border};border-radius:8px;")
        else:
            # 占位块（视频 / 预览失败）只换边框色，保留文字样式
            color = theme.PRIMARY if self.checked else theme.LINE
            self.pic.setStyleSheet(
                f"background:{theme.BG_SUNK};border:{border};border-radius:8px;"
                f"{theme.css_font(13, 600) if self.path.lower().endswith(VIDEO_EXT) else theme.css_font(12, 400)}"
                f"color:{theme.TEXT_3 if self.checked else theme.TEXT_4};")

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self.set_checked(not self.checked)
        super().mouseReleaseEvent(ev)


# ================================================================ 选图器
class MediaPickerDialog(BaseDialog):
    """左侧批次列表（按时间倒序）+ 右侧缩略图网格。"""

    def __init__(self, parent=None, batches: Optional[List[dict]] = None,
                 start_dir: str = ""):
        super().__init__(parent, "选择要上传的素材",
                         subtitle="左侧是最近产出的批次（新→旧）；点缩略图可剔除个别图",
                         width=620)
        self._batches = list(batches or [])
        self._thumbs: List[Thumb] = []
        self.selected_files: List[str] = []
        self.selected_dir = ""

        row = QHBoxLayout()
        row.setSpacing(12)

        # ---------------- 左：批次列表
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        cap = QLabel("最近产出批次")
        cap.setObjectName("FieldLabel")
        left_col.addWidget(cap)
        self.lst = QListWidget()
        self.lst.setFixedWidth(196)
        self.lst.setIconSize(QSize(1, 1))
        self.lst.currentRowChanged.connect(self._on_batch)
        left_col.addWidget(self.lst, 1)
        row.addLayout(left_col)

        # ---------------- 右：缩略图网格
        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        self.lb_grid_cap = QLabel("")
        self.lb_grid_cap.setObjectName("FieldLabel")
        right_col.addWidget(self.lb_grid_cap)

        self.grid_host = QWidget()
        self.grid_lay = QGridLayout(self.grid_host)
        self.grid_lay.setContentsMargins(0, 0, 0, 0)
        self.grid_lay.setSpacing(6)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.grid_host)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setMinimumHeight(THUMB * 2 + 80)
        theme.paint_bg(self.scroll, "#FFFFFF")
        theme.paint_bg(self.scroll.viewport(), "#FFFFFF")
        right_col.addWidget(self.scroll, 1)
        row.addLayout(right_col, 1)

        self.body.addLayout(row)

        # ---------------- 底部按钮
        self.btn_open_dir = self.add_button("打开文件夹", "Soft", self._open_dir)
        self.add_stretch()
        self.add_button("取消", "Soft", self.reject)
        self.btn_use = self.add_button("用这批", "Primary", self._use, default=True)

        # ---------------- 填充数据
        for b in self._batches:
            QListWidgetItem(_batch_label(b), self.lst)
        # 优先定位 start_dir 对应批次，否则选最新
        first = 0
        if start_dir:
            for i, b in enumerate(self._batches):
                if os.path.normpath(b["dir"]) == os.path.normpath(start_dir):
                    first = i
                    break
        if self._batches:
            self.lst.setCurrentRow(first)
        else:
            self.lb_grid_cap.setText("没有找到任何已产出的素材批次")
            self.btn_use.setEnabled(False)

    # ------------------------------------------------------------ 批次切换
    def _on_batch(self, idx: int) -> None:
        # 清空旧网格
        theme.clear_layout(self.grid_lay)
        self._thumbs = []
        if not (0 <= idx < len(self._batches)):
            return
        b = self._batches[idx]
        self.selected_dir = b["dir"]
        self.lb_grid_cap.setText(
            f"{os.path.basename(b['dir'].rstrip(os.sep)) or b['dir']}")
        for i, p in enumerate(b["files"]):
            t = Thumb(p)
            self._thumbs.append(t)
            self.grid_lay.addWidget(t, i // GRID_COLS, i % GRID_COLS)
        self.grid_lay.setRowStretch(len(b["files"]) // GRID_COLS + 1, 1)
        self._update_use_text()

    def _update_use_text(self) -> None:
        n = len(self.checked_files())
        self.btn_use.setText(f"用这批（{n} 个）")

    # ------------------------------------------------------------ 选中状态
    def checked_files(self) -> List[str]:
        return [t.path for t in self._thumbs if t.checked]

    # ------------------------------------------------------------ 底部动作
    def _open_dir(self) -> None:
        import platforms as PF
        if self.selected_dir:
            PF.open_in_explorer(self.selected_dir)

    def _use(self) -> None:
        self.selected_files = self.checked_files()
        self.accept()


# ================================================================ 快捷入口
def pick_media_files(parent=None, start_dir: str = "", images_only: bool = False,
                     topic: str = "") -> Optional[Tuple[List[str], str]]:
    """弹应用内选图器。返回值约定见模块 docstring。

    images_only=True：只列含图片的批次（给图文挂图用 —— 纯视频批次
    列出来只会误导）；start_dir 里没有图片时也会被忽略，退回全量扫描。

    topic 给了就**始终全量扫描并按题排前**（不再只列 start_dir 一批）——
    建议目录也可能定位到别的题的批次，用户得能看到并换到本题批次。
    """
    exts = IMG_EXT if images_only else None
    batches: List[dict] = []
    if not topic and start_dir and os.path.isdir(start_dir):
        files = _media_files(start_dir, exts)
        if files:
            batches = [{"dir": start_dir,
                        "mtime": max((os.path.getmtime(f) for f in files),
                                     default=0.0),
                        "files": files}]
    if not batches:
        batches = list_batches(exts=exts, topic=topic)
    if not batches:
        return None
    dlg = MediaPickerDialog(parent, batches, start_dir)
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    if ok:
        return dlg.selected_files, dlg.selected_dir
    return [], dlg.selected_dir   # 取消：files 空，但 dir 非空表示选图器开过
