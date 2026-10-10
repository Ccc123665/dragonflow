"""素材库：归档、检索、复用已生成的内容。"""
import os
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

import bus as BUSMOD
import platforms as PF
import skills as SK
import store
import theme
from bus import BUS, Batch, DraftItem
from widgets.common import (
    ArtifactStrip, Badge, ClickableFrame, EmptyState, Pill, TagDot, open_dir, toast,
)
from widgets.dialogs import MessageDialog


class LibraryView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[Dict[str, Any]] = []
        self._cur: Dict[str, Any] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏
        bar = QWidget()
        bar.setObjectName("NavBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedHeight(56)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 0, 16, 0)
        bl.setSpacing(10)
        t = QLabel("素材库")
        t.setObjectName("H2")
        bl.addWidget(t)
        self.lb_count = Badge("0")
        bl.addWidget(self.lb_count)
        bl.addStretch(1)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索标题 / 选题")
        self.ed_search.setFixedWidth(230)
        self.ed_search.setFixedHeight(34)
        self.ed_search.textChanged.connect(self.reload)
        bl.addWidget(self.ed_search)

        self.cb_platform = QComboBox()
        self.cb_platform.addItem("全部平台", "")
        for p in PF.enabled_platforms():
            self.cb_platform.addItem(p["name"], p["key"])
        self.cb_platform.currentIndexChanged.connect(self.reload)
        bl.addWidget(self.cb_platform)
        root.addWidget(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        # 列表
        left = QWidget()
        left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(left, theme.BG_PAGE)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 14, 8, 14)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ll.addWidget(sc)
        self.list_box = QWidget()
        self.list_lay = QVBoxLayout(self.list_box)
        self.list_lay.setContentsMargins(0, 0, 4, 0)
        self.list_lay.setSpacing(8)
        sc.setWidget(self.list_box)
        split.addWidget(left)

        # 详情
        right = QWidget()
        right.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(right, theme.BG_CARD)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(20, 16, 20, 16)
        rl.setSpacing(10)

        self.lb_title = QLabel("选择左侧的一条素材")
        self.lb_title.setObjectName("H3")
        self.lb_title.setWordWrap(True)
        self.lb_meta = QLabel("")
        self.lb_meta.setObjectName("Muted")
        self.lb_meta.setWordWrap(True)
        rl.addWidget(self.lb_title)
        rl.addWidget(self.lb_meta)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_reuse = QPushButton("复用到发布工作台")
        self.btn_reuse.setObjectName("Primary")
        self.btn_reuse.setMinimumHeight(34)
        self.btn_reuse.clicked.connect(self._reuse)
        self.btn_reuse.setEnabled(False)
        self.btn_copy = QPushButton("复制全文")
        self.btn_copy.setObjectName("Soft")
        self.btn_copy.setMinimumHeight(34)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_copy.setEnabled(False)
        self.btn_del = QPushButton("删除")
        self.btn_del.setObjectName("Soft")
        self.btn_del.setMinimumHeight(34)
        self.btn_del.clicked.connect(self._delete)
        self.btn_del.setEnabled(False)
        row.addWidget(self.btn_reuse)
        row.addWidget(self.btn_copy)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        rl.addLayout(row)

        # 产出文件（图片 / 视频）。流水线生成的内容在这里能看到图，
        # 以前素材库只有一坨文字，配图在哪完全看不出来。
        self.art_box = QWidget()
        self.art_lay = QVBoxLayout(self.art_box)
        self.art_lay.setContentsMargins(0, 0, 0, 0)
        self.art_lay.setSpacing(6)
        self.art_box.setVisible(False)
        rl.addWidget(self.art_box)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("内容预览")
        rl.addWidget(self.preview, 1)
        split.addWidget(right)
        split.setSizes([430, 640])

        BUS.library_changed.connect(self.reload)
        self.reload()

    # ---------------------------------------------------------- 列表
    def reload(self):
        db = store.load_library()
        kw = self.ed_search.text().strip().lower()
        pk = self.cb_platform.currentData()
        items = db.get("items", [])
        if pk:
            items = [i for i in items if i.get("platform") == pk]
        if kw:
            items = [i for i in items
                     if kw in (i.get("title") or "").lower()
                     or kw in (i.get("topic") or "").lower()]
        self._items = items
        self.lb_count.setText(str(len(items)))

        theme.clear_layout(self.list_lay)
        if not items:
            if db.get("items"):
                es = EmptyState("没有匹配的素材", "换个关键词，或切换平台筛选", "folder")
            else:
                es = EmptyState("素材库是空的", "内容工坊生成的内容会自动归档到这里", "folder")
            self.list_lay.addStretch(1)
            self.list_lay.addWidget(es)
            self.list_lay.addStretch(2)
            return
        for item in items[:300]:
            self.list_lay.addWidget(self._row(item))
        self.list_lay.addStretch(1)

    def _row(self, item: Dict[str, Any]) -> QWidget:
        f = ClickableFrame(object_name="CardHover")
        f.setStyleSheet(f"""
            QFrame#CardHover {{ background:{theme.BG_CARD};border:1px solid {theme.LINE};
                           border-radius:{theme.R_CARD}px; }}
            QFrame#CardHover:hover {{ border:1px solid {theme.PRIMARY_SOFT}; background:#FCFDFF; }}
        """)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        pk = item.get("platform", "")
        lay.addWidget(TagDot(PF.short_of(pk), PF.color_of(pk)))

        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel((item.get("title") or "（无标题）")[:46])
        t.setStyleSheet(f"background:transparent;{theme.css_font(13.5, 600)}color:{theme.TEXT_1};")
        n_art = len([p for p in (item.get("artifacts") or []) if os.path.exists(p)])
        m = QLabel(f"{PF.name_of(pk)} · {item.get('created_at','')[:16]}"
                   + (f" · {item.get('topic','')[:18]}" if item.get("topic") else "")
                   + (f" · 含 {n_art} 个产出文件" if n_art else ""))
        m.setStyleSheet(f"background:transparent;{theme.css_font(11.5)}color:{theme.TEXT_3};")
        col.addWidget(t)
        col.addWidget(m)
        lay.addLayout(col, 1)

        f.clicked.connect(lambda i=item: self._select(i))
        return f

    def _select(self, item: Dict[str, Any]):
        self._cur = item
        self.lb_title.setText(item.get("title") or "（无标题）")
        pk = item.get("platform", "")
        skill = SK.get_skill(item.get("skill_id", "")) or {}
        self.lb_meta.setText(
            f"{PF.name_of(pk)} · {skill.get('name', '')} · {item.get('created_at', '')}"
        )
        content = item.get("content") or {}
        parts = []
        for k, v in content.items():
            if not v:
                continue
            if isinstance(v, list):
                # 只有话题加 #；旧数据里 image_hint 曾被误存成列表，别给它加
                if k == "topics":
                    v = " ".join(f"#{str(x).lstrip('#')}" for x in v)
                else:
                    v = " ".join(str(x) for x in v)
            parts.append(f"【{SK.field_label(k)}】\n{v}")
        self.preview.setPlainText("\n\n".join(parts))
        self._show_artifacts(item.get("artifacts") or [])
        for b in (self.btn_reuse, self.btn_copy, self.btn_del):
            b.setEnabled(True)

    def _show_artifacts(self, paths):
        theme.clear_layout(self.art_lay)
        files = [p for p in (paths or []) if p and os.path.exists(p)]
        if not files:
            self.art_box.setVisible(False)
            return

        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel("产出文件")
        t.setObjectName("FieldLabel")
        head.addWidget(t)
        head.addWidget(Badge(str(len(files))))
        head.addStretch(1)
        b = QPushButton("打开目录")
        b.setObjectName("Ghost")
        b.clicked.connect(lambda _=False, p=files[0]: open_dir(os.path.dirname(p)))
        head.addWidget(b)
        self.art_lay.addLayout(head)
        self.art_lay.addWidget(ArtifactStrip(files, height=176, limit=12, thumb=140))
        self.art_box.setVisible(True)

    # ---------------------------------------------------------- 动作
    def _reuse(self):
        if not self._cur:
            return
        pk = self._cur.get("platform", "")
        skill = SK.get_skill(self._cur.get("skill_id", "")) or {}
        item = DraftItem(pk, self._cur.get("skill_id", ""),
                         skill.get("name", ""), self._cur.get("content") or {},
                         self._cur.get("topic", ""))
        item.artifacts = list(self._cur.get("artifacts") or [])

        # 合并进当前批次，而不是整个替换。
        # 待发布列表里其他平台的内容不该因为复用了一条素材就消失；
        # 同平台的那条被这条替换（用户点复用就是想用这一条）。
        b = BUSMOD.batch()
        if b is None:
            b = Batch(item.topic)
            b.items = []
        replaced = False
        kept = []
        for it in b.items:
            if it.platform_key == pk:
                replaced = True
                continue
            kept.append(it)
        kept.append(item)
        b.items = kept
        BUSMOD.set_batch(b)
        BUS.goto_workbench.emit()

        n = len(item.artifacts)
        toast(self.window(),
              f"已把这条{PF.name_of(pk)}内容送进发布工作台"
              + (f"（含 {n} 个产出文件）" if n else "")
              + ("，同平台原内容已替换" if replaced else ""),
              "ok", 3200)

    def _copy(self):
        from PyQt6.QtWidgets import QApplication
        if not self._cur:
            return
        QApplication.clipboard().setText(self.preview.toPlainText())
        toast(self.window(), "已复制全文", "ok")

    def _delete(self):
        if not self._cur:
            return
        ok = MessageDialog.confirm(
            self.window(), "删除素材",
            f"确定删除「{self._cur.get('title') or '这条素材'}」吗？",
            kind="err", detail="删除后不可恢复。", ok_text="删除", cancel_text="取消")
        if not ok:
            return
        db = store.load_library()
        store.delete_library_item(db, self._cur["id"])
        self._cur = {}
        self.lb_title.setText("选择左侧的一条素材")
        self.lb_meta.setText("")
        self.preview.clear()
        for b in (self.btn_reuse, self.btn_copy, self.btn_del):
            b.setEnabled(False)
        self.reload()
        toast(self.window(), "已删除", "info")
