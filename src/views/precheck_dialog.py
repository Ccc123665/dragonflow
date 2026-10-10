"""发布前体检结果弹窗：把「能不能发出去」和「会不会被限流」一次讲清楚。

体检分两块：
  · 字段规则（precheck）：长度 / 必填 / 话题数量 / 站外引流 / 排版
  · 词库匹配（compliance）：广告法极限词、行业敏感词
两块结果合并成一个按严重程度排序的清单，每条都给出「怎么改」。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

import compliance
import icons
import platforms as PF
import precheck
import skills as SK
import theme
from widgets.common import Badge
from widgets.dialogs import BaseDialog

LEVEL_STYLE = {
    "err": ("必改", theme.DANGER, theme.DANGER_TINT),
    "warn": ("建议改", theme.WARNING, theme.WARNING_TINT),
    "info": ("可优化", theme.PRIMARY, theme.PRIMARY_TINT),
}


class PrecheckDialog(BaseDialog):
    def __init__(self, parent, platform_key: str,
                 issues: List[precheck.Issue],
                 hits: Dict[str, List[Dict[str, Any]]]):
        total = len(issues) + sum(len(v) for v in hits.values())
        name = PF.name_of(platform_key) or "这份内容"
        super().__init__(
            parent, "发布前体检",
            f"{name} · 共 {total} 项" if total else f"{name} · 没有发现问题",
            width=660)

        # ---- 总览条
        e, w, n = precheck.summarize(issues)
        high, mid = compliance.summarize(hits)
        bar = QWidget()
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        level = "err" if (e or high) else ("warn" if (w or mid) else
                                          ("info" if n else "ok"))
        color, bg = {
            "err": (theme.DANGER, theme.DANGER_TINT),
            "warn": (theme.WARNING, theme.WARNING_TINT),
            "info": (theme.PRIMARY, theme.PRIMARY_TINT),
            "ok": (theme.SUCCESS, theme.SUCCESS_TINT),
        }[level]
        theme.paint_bg(bar, bg)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 11, 14, 11)
        bl.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("check" if level == "ok" else "warn", color, 17, 2.0))
        bl.addWidget(ic)
        lb = QLabel(_verdict(level, e, w, n, high, mid))
        lb.setWordWrap(True)
        lb.setStyleSheet(f"background:transparent;{theme.css_font(13, 500)}color:{color};")
        bl.addWidget(lb, 1)
        self.body.addWidget(bar)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setMinimumHeight(260)
        sc.setMaximumHeight(520)
        box = QWidget()
        vl = QVBoxLayout(box)
        vl.setContentsMargins(0, 0, 6, 0)
        vl.setSpacing(8)

        for lv in ("err", "warn", "info"):
            group = [i for i in issues if i.level == lv]
            if not group:
                continue
            vl.addWidget(_group_head(LEVEL_STYLE[lv][0], len(group),
                                     LEVEL_STYLE[lv][1]))
            for i in group:
                vl.addWidget(_issue_row(i, platform_key))

        if hits:
            n_hits = sum(len(v) for v in hits.values())
            vl.addWidget(_group_head("词库命中", n_hits, theme.DANGER))
            for f, arr in hits.items():
                words = "、".join(f"{h['word']}（{h['category']}）" for h in arr[:8])
                vl.addWidget(_simple_row(
                    f"{SK.field_label(f)}：{words}",
                    "广告法极限词 / 行业敏感词，发布前必须换掉", theme.DANGER,
                    theme.DANGER_TINT))

        if not issues and not hits:
            vl.addWidget(_simple_row(
                "字段长度、必填项、话题数量、站外引流、排版、词库 —— 全部通过。",
                "仍建议人工通读一遍：机器只能查规则，查不了语气和事实。",
                theme.SUCCESS, theme.SUCCESS_TINT))
        vl.addStretch(1)
        sc.setWidget(box)
        self.body.addWidget(sc, 1)

        self.add_stretch()
        self.add_button("知道了", "Primary", self.accept, default=True)

    # ---------------------------------------------------------- 快捷
    @staticmethod
    def show_for(parent, platform_key: str, issues, hits) -> None:
        d = PrecheckDialog(parent, platform_key, list(issues or []), hits or {})
        d.exec()


def _verdict(level: str, e: int, w: int, n: int, high: int, mid: int) -> str:
    if level == "ok":
        return "体检通过，可以放心填充。"
    bits = []
    if e:
        bits.append(f"{e} 项必须改")
    if high:
        bits.append(f"{high} 处高风险词")
    if w:
        bits.append(f"{w} 项建议改")
    if mid:
        bits.append(f"{mid} 处中风险词")
    if n:
        bits.append(f"{n} 项可优化")
    head = "、".join(bits)
    tail = "　必改项不处理的话，填充或发布很可能失败。" if (e or high) \
        else "　都不影响填充，但改完效果更好。"
    return head + tail


def _group_head(text: str, count: int, color: str) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 6, 0, 2)
    lay.setSpacing(6)
    lb = QLabel(text)
    lb.setStyleSheet(f"background:transparent;{theme.css_font(13, 600)}color:{color};")
    lay.addWidget(lb)
    lay.addWidget(Badge(str(count)))
    lay.addStretch(1)
    return w


def _issue_row(issue: precheck.Issue, platform_key: str) -> QWidget:
    _, color, tint = LEVEL_STYLE.get(issue.level, LEVEL_STYLE["info"])
    field = SK.field_label(issue.field) if issue.field else ""
    head = (f"[{field}] " if field else "") + issue.message
    return _simple_row(head, issue.hint, color, tint)


def _simple_row(head: str, hint: str, color: str, tint: str) -> QWidget:
    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    theme.paint_bg(w, theme.BG_SUBTLE)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(12, 9, 12, 9)
    lay.setSpacing(3)

    row = QHBoxLayout()
    row.setSpacing(8)
    dot = QLabel("●")
    dot.setStyleSheet(f"background:transparent;{theme.css_font(10)}color:{color};")
    row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
    t = QLabel(head)
    t.setWordWrap(True)
    t.setStyleSheet(f"background:transparent;{theme.css_font(13, 500)}color:{theme.TEXT_1};")
    row.addWidget(t, 1)
    lay.addLayout(row)

    if hint:
        h = QLabel(hint)
        h.setWordWrap(True)
        h.setStyleSheet(
            f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_3};"
            f"padding-left:18px;")
        lay.addWidget(h)
    return w
