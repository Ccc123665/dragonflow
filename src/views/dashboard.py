"""数据看板：只用本机的发布记录和素材库做统计，不联网、不上报。

口径说明（避免误读）
  · 数据源是 records.json（每次点「一键填充 / 一键发布」都会写一条）和 library.json
  · 「填充」和「发布」分开统计 —— 本工具只做页面填充，最终是否点提交由人决定，
    所以「已填充」不等于「已发布」，看板上两者分开列
  · 公众号只保存草稿，记录里会以「已填充」呈现
"""
from __future__ import annotations

import datetime
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Tuple

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

import icons
import platforms as PF
import store
import theme
from bus import BUS
from widgets.common import Card, EmptyState, Pill

DONE = ("已发布", "已填充")
FAIL = ("失败",)

STATUS_COLOR = {
    "已发布": theme.SUCCESS,
    "已填充": theme.PRIMARY,
    "失败": theme.DANGER,
    "填充中": theme.WARNING,
    "发布中": theme.WARNING,
    "待填充": theme.TEXT_3,
}


# ================================================================ 统计
def _parse(ts: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(ts[:10], "%Y-%m-%d").date()
    except Exception:
        return datetime.date(1970, 1, 1)


def compute(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    today = datetime.date.today()
    d = {
        "total": len(records),
        "today_pub": 0, "today_fill": 0,
        "d7_pub": 0, "d30_pub": 0,
        "ok": 0, "fail": 0, "pending": 0,
        "by_day": OrderedDict(),
        "by_platform": Counter(),
        "by_account": Counter(),
        "by_status": Counter(),
        "streak": 0,
    }
    days = [today - datetime.timedelta(days=i) for i in range(13, -1, -1)]
    for day in days:
        d["by_day"][day.isoformat()] = 0

    pub_days = set()
    for r in records:
        st = r.get("status", "")
        day = _parse(r.get("created_at", ""))
        d["by_status"][st] += 1
        if st in DONE:
            d["ok"] += 1
            pub_days.add(day)
            if day == today:
                # 「填充」和「发布」分开计 —— 本工具只做页面填充，
                # 最终是否点提交由人决定，两者混在一起会误导
                if st == "已发布":
                    d["today_pub"] += 1
                else:
                    d["today_fill"] += 1
            if (today - day).days < 7:
                d["d7_pub"] += 1
            if (today - day).days < 30:
                d["d30_pub"] += 1
            key = day.isoformat()
            if key in d["by_day"]:
                d["by_day"][key] += 1
            d["by_platform"][r.get("platform_name") or PF.name_of(r.get("platform", ""))] += 1
            d["by_account"][r.get("account_name") or "（未指定账号）"] += 1
        elif st in FAIL:
            d["fail"] += 1
        else:
            d["pending"] += 1

    # 连续发布天数（从今天往前数）
    n = 0
    cur = today
    while cur in pub_days:
        n += 1
        cur -= datetime.timedelta(days=1)
    d["streak"] = n
    d["rate"] = (d["ok"] / (d["ok"] + d["fail"])) if (d["ok"] + d["fail"]) else 0.0
    return d


# ================================================================ 图表
class BarChart(QWidget):
    """近 N 天发布量柱状图（自绘，不引第三方绘图库）。"""

    def __init__(self, data: "OrderedDict[str, int]", parent=None):
        super().__init__(parent)
        self.data = data
        self.setMinimumHeight(150)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(self, theme.BG_CARD)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        items = list(self.data.items())
        if not items:
            return
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 6, 6, 22, 26
        n = len(items)
        gap = 6
        bw = max(6.0, (w - pad_l - pad_r - gap * (n - 1)) / n)
        top = max(1, max(self.data.values()))
        base = h - pad_b

        for i, (day, v) in enumerate(items):
            x = pad_l + i * (bw + gap)
            bh = (base - pad_t) * (v / top) if top else 0
            bh = max(2.0, bh) if v else 2.0
            rect = QRectF(x, base - bh, bw, bh)
            path = QPainterPath()
            path.addRoundedRect(rect, min(5.0, bw / 2), min(5.0, bw / 2))
            col = QColor(theme.PRIMARY if v else theme.BG_HOVER)
            if not v:
                col = QColor(theme.LINE)
            p.fillPath(path, col)
            if v:
                p.setPen(QColor(theme.TEXT_2))
                f = p.font()
                f.setPointSizeF(9)
                p.setFont(f)
                p.drawText(QRectF(x - 4, base - bh - 18, bw + 8, 16),
                           Qt.AlignmentFlag.AlignCenter, str(v))
            # x 轴日期：每 2 个标一次，避免挤在一起
            if i % 2 == 0 or i == n - 1:
                p.setPen(QColor(theme.TEXT_4))
                f = p.font()
                f.setPointSizeF(8.5)
                p.setFont(f)
                p.drawText(QRectF(x - 10, base + 5, bw + 20, 16),
                           Qt.AlignmentFlag.AlignCenter, day[5:])
        p.end()


class HBar(QWidget):
    """一条横向占比条：名称 + 轨道 + 数值。"""

    def __init__(self, label: str, value: int, total: int, color: str,
                 suffix: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        nm = QLabel(label)
        nm.setStyleSheet(f"background:transparent;{theme.css_font(12.5, 500)}color:{theme.TEXT_1};")
        head.addWidget(nm)
        head.addStretch(1)
        vl = QLabel(f"{value}{suffix}")
        vl.setStyleSheet(f"background:transparent;{theme.css_font(12, 600)}color:{color};")
        head.addWidget(vl)
        lay.addLayout(head)

        track = QWidget()
        track.setFixedHeight(7)
        track.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        theme.paint_bg(track, theme.BG_INPUT)
        lay.addWidget(track)

        pct = (value / total) if total else 0.0
        self._bar = QWidget(track)
        self._bar.setObjectName("HBarFill")
        theme.paint_bg(self._bar, color)

        def place():
            track_w = max(1, track.width())
            self._bar.setGeometry(0, 0, max(3, int(track_w * pct)), track.height())
        self._place = place
        place()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()


# ================================================================ 视图
class DashboardView(QWidget):
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
        t = QLabel("数据看板")
        t.setObjectName("H2")
        bl.addWidget(t)
        self.lb_scope = QLabel("")
        self.lb_scope.setObjectName("Muted")
        bl.addWidget(self.lb_scope)
        bl.addStretch(1)
        from PyQt6.QtWidgets import QPushButton
        b = QPushButton("刷新")
        b.setObjectName("Soft")
        b.setMinimumHeight(34)
        b.setIcon(icons.icon("refresh", theme.TEXT_2, 15))
        b.clicked.connect(self.reload)
        bl.addWidget(b)
        root.addWidget(bar)

        page = theme.PageScroll(max_width=1120, top=18, bottom=28, spacing=14)
        root.addWidget(page, 1)
        self.lay = page.body
        self._built = False

        BUS.records_changed.connect(self.reload)
        BUS.library_changed.connect(self.reload)
        self.reload()

    # ---------------------------------------------------------- 组装
    def reload(self):
        theme.clear_layout(self.lay)
        records = store.load_records().get("records", [])
        lib = store.load_library().get("items", [])
        st = compute(records)

        self.lb_scope.setText(f"数据来源：本机发布记录 {len(records)} 条 · 素材库 {len(lib)} 条")

        if not records and not lib:
            self.lay.addWidget(EmptyState(
                "还没有数据",
                "去「内容工坊」生成内容、到「发布工作台」填充或发布后，这里就会有统计",
                "target"))
            self.lay.addStretch(1)
            return

        self.lay.addLayout(self._kpis(st))
        self.lay.addWidget(self._trend(st))
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._platform_card(st), 1)
        row.addWidget(self._status_card(st, lib), 1)
        self.lay.addLayout(row)
        self.lay.addWidget(self._account_card(st))
        self.lay.addStretch(1)

    # ---------------------------------------------------------- KPI
    def _kpis(self, st: Dict[str, Any]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        items = [
            ("今日完成", st["today_pub"] + st["today_fill"], "条", theme.PRIMARY,
             f"今天已填充 {st['today_fill']} 条、已发布 {st['today_pub']} 条"),
            ("近 7 天", st["d7_pub"], "条", theme.SUCCESS, "近 7 天完成填充 / 发布的条数"),
            ("近 30 天", st["d30_pub"], "条", theme.SUCCESS, "近 30 天完成填充 / 发布的条数"),
            ("成功率", f"{st['rate'] * 100:.0f}", "%",
             theme.DANGER if st["rate"] < 0.8 and (st["ok"] + st["fail"]) else theme.PRIMARY,
             f"成功 {st['ok']} 条 / 失败 {st['fail']} 条"),
            ("连续天数", st["streak"], "天", theme.WARNING, "连续有产出的天数"),
        ]
        for label, val, unit, color, tip in items:
            c = Card(padding=14, spacing=4)
            c.setToolTip(tip)
            lb = QLabel(label)
            lb.setStyleSheet(f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_3};")
            c.body.addWidget(lb)
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            v = QLabel(str(val))
            v.setStyleSheet(f"background:transparent;{theme.css_font(26, 700)}color:{color};")
            h.addWidget(v)
            u = QLabel(unit)
            u.setStyleSheet(f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_3};")
            h.addWidget(u, 0, Qt.AlignmentFlag.AlignBottom)
            h.addStretch(1)
            c.body.addLayout(h)
            row.addWidget(c, 1)
        return row

    # ---------------------------------------------------------- 趋势
    def _trend(self, st: Dict[str, Any]) -> QWidget:
        card = Card(padding=16, spacing=10)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel("近 14 天完成量")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch(1)
        total = sum(st["by_day"].values())
        head.addWidget(Pill(f"合计 {total} 条", theme.TEXT_2, theme.BG_INPUT))
        card.body.addLayout(head)
        card.body.addWidget(BarChart(st["by_day"]))
        card.body.addWidget(_hint("「完成」= 已填充 或 已发布。公众号只存草稿，计在已填充里。"))
        return card

    # ---------------------------------------------------------- 平台
    def _platform_card(self, st: Dict[str, Any]) -> QWidget:
        card = Card(padding=16, spacing=10)
        t = QLabel("平台分布")
        t.setObjectName("CardTitle")
        card.body.addWidget(t)
        data = st["by_platform"].most_common(8)
        if not data:
            card.body.addWidget(_hint("还没有完成填充的记录。"))
            return card
        total = sum(st["by_platform"].values())
        for name, n in data:
            key = next((p["key"] for p in PF.all_platforms() if p["name"] == name), "")
            card.body.addWidget(HBar(name, n, total, PF.color_of(key) if key else theme.PRIMARY,
                                     suffix=f" 条 · {n / total * 100:.0f}%"))
        return card

    # ---------------------------------------------------------- 状态
    def _status_card(self, st: Dict[str, Any], lib: List[Dict[str, Any]]) -> QWidget:
        card = Card(padding=16, spacing=10)
        t = QLabel("状态构成 & 素材库")
        t.setObjectName("CardTitle")
        card.body.addWidget(t)
        total = sum(st["by_status"].values()) or 1
        for status in ("已发布", "已填充", "失败", "填充中", "发布中", "待填充"):
            n = st["by_status"].get(status, 0)
            if not n:
                continue
            card.body.addWidget(HBar(status, n, total,
                                     STATUS_COLOR.get(status, theme.TEXT_3),
                                     suffix=f" 条"))
        if not st["by_status"]:
            card.body.addWidget(_hint("还没有执行记录。"))
        card.body.addWidget(_divider())
        card.body.addWidget(_hint(f"素材库共 {len(lib)} 条内容"))
        by_pf = Counter(PF.name_of(i.get("platform", "")) for i in lib if i.get("platform"))
        for name, n in by_pf.most_common(5):
            card.body.addWidget(HBar(name, n, len(lib) or 1, theme.PRIMARY, suffix=" 条"))
        return card

    # ---------------------------------------------------------- 账号
    def _account_card(self, st: Dict[str, Any]) -> QWidget:
        card = Card(padding=16, spacing=10)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel("账号产出排行")
        t.setObjectName("CardTitle")
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(Pill(f"{len(st['by_account'])} 个账号有产出",
                            theme.TEXT_2, theme.BG_INPUT))
        card.body.addLayout(head)
        data = st["by_account"].most_common(10)
        if not data:
            card.body.addWidget(_hint("还没有账号产出记录。"))
            return card
        total = max(data[0][1], 1)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        for i, (name, n) in enumerate(data):
            grid.addWidget(HBar(name, n, total, theme.PRIMARY, suffix=f" 条"),
                           0 if i < 5 else 1, i % 5 if i < 5 else i - 5)
        card.body.addLayout(grid)
        return card


# ================================================================ 小件
def _hint(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("Hint")
    lb.setWordWrap(True)
    return lb


def _divider() -> QWidget:
    w = QWidget()
    w.setFixedHeight(1)
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    theme.paint_bg(w, theme.LINE)
    return w
