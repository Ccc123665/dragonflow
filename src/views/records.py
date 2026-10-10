"""发布记录：填充与发布的结果台账。"""
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import platforms as PF
import store
import theme
from bus import BUS
from widgets.common import Badge, EmptyState, Pill, toast
from widgets.dialogs import MessageDialog

STATUS_KIND = {
    "已发布": theme.SUCCESS,
    "已填充": theme.PRIMARY,
    "草稿": theme.TEXT_2,
    "待填充": theme.TEXT_3,
    "填充中": theme.WARNING,
    "发布中": theme.WARNING,
    "失败": theme.DANGER,
}

STATUS_BG = {
    "已发布": theme.SUCCESS_TINT,
    "已填充": theme.PRIMARY_TINT,
    "填充中": theme.WARNING_TINT,
    "发布中": theme.WARNING_TINT,
    "失败": theme.DANGER_TINT,
}


class RecordsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("NavBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setFixedHeight(56)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(20, 0, 16, 0)
        bl.setSpacing(10)
        t = QLabel("发布记录")
        t.setObjectName("H2")
        bl.addWidget(t)
        self.lb_count = Badge("0")
        bl.addWidget(self.lb_count)
        bl.addStretch(1)

        self.cb_platform = QComboBox()
        self.cb_platform.addItem("全部平台", "")
        for p in PF.enabled_platforms():
            self.cb_platform.addItem(p["name"], p["key"])
        self.cb_platform.currentIndexChanged.connect(self.reload)
        bl.addWidget(self.cb_platform)

        self.cb_status = QComboBox()
        for s in ("全部状态", "已发布", "已填充", "失败"):
            self.cb_status.addItem(s, "" if s == "全部状态" else s)
        self.cb_status.currentIndexChanged.connect(self.reload)
        bl.addWidget(self.cb_status)

        b_clear = QPushButton("清空记录")
        b_clear.setObjectName("Soft")
        b_clear.setMinimumHeight(34)
        b_clear.clicked.connect(self._clear)
        bl.addWidget(b_clear)
        root.addWidget(bar)

        body = QWidget()
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(body, theme.BG_PAGE)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(10)
        root.addWidget(body, 1)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["时间", "平台", "账号", "选题", "状态", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        # 状态列放的是自定义 Pill 控件（不是 QTableWidgetItem），
        # ResizeToContents 量不到宽度，会把标签挤成竖排 —— 这里固定宽度。
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(4, 96)
        self.table.setStyleSheet(
            f"QTableWidget{{background:{theme.BG_CARD};"
            f"border:1px solid {theme.LINE};border-radius:12px;"
            f"padding:4px;}}")
        lay.addWidget(self.table, 1)

        self.empty = EmptyState("还没有发布记录",
                                "在发布工作台执行填充或发布后，记录会出现在这里", "clock")
        lay.addWidget(self.empty)

        BUS.records_changed.connect(self.reload)
        self.reload()

    def reload(self):
        db = store.load_records()
        pk = self.cb_platform.currentData()
        st = self.cb_status.currentData()
        rows = db.get("records", [])
        if pk:
            rows = [r for r in rows if r.get("platform") == pk]
        if st:
            rows = [r for r in rows if r.get("status") == st]
        self.lb_count.setText(str(len(rows)))

        self.table.setRowCount(0)
        for r in rows[:500]:
            i = self.table.rowCount()
            self.table.insertRow(i)
            status = str(r.get("status", ""))
            vals = [
                r.get("created_at", "")[:19],
                r.get("platform_name") or PF.name_of(r.get("platform", "")),
                r.get("account_name", ""),
                r.get("topic", ""),
                status,
                r.get("message", ""),
            ]
            for c, v in enumerate(vals):
                if c == 4:
                    self.table.setCellWidget(i, c, self._status_pill(status))
                    continue
                item = QTableWidgetItem(str(v))
                if c in (0, 1, 2):
                    item.setForeground(QColor(theme.TEXT_3 if c == 0 else theme.TEXT_1))
                elif c == 5:
                    item.setForeground(QColor(theme.TEXT_3))
                self.table.setItem(i, c, item)
            self.table.setRowHeight(i, 40)
        self.table.setVisible(bool(rows))
        self.empty.setVisible(not rows)

    def _status_pill(self, status: str) -> QWidget:
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(0)
        lay.addWidget(Pill(status or "—",
                           STATUS_KIND.get(status, theme.TEXT_2),
                           STATUS_BG.get(status, theme.BG_INPUT)))
        lay.addStretch(1)
        return holder

    def _clear(self):
        ok = MessageDialog.confirm(
            self, "清空记录", "确定清空全部发布记录吗？",
            kind="err", detail="此操作不可撤销。", ok_text="清空", cancel_text="取消")
        if not ok:
            return
        db = store.load_records()
        db["records"] = []
        store.save_records(db)
        self.reload()
        toast(self.window(), "已清空发布记录", "info")
