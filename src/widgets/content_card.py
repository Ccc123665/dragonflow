"""内容卡片：一个平台一份内容的编辑单元。"""
import os
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

import compliance
import config
import icons
import platforms as PF
import precheck
import skills as SK
import theme
from widgets.common import IconButton, Pill, TagDot, toast

MULTILINE = {"body", "topics", "image_hint", "shot_hint"}
TALL = {"body"}
# 这两个字段是「产出物说明」（流水线写的目录 / 文件路径 + 风格描述），
# 不再渲染成可编辑文本框 —— 用户对着一行小字路径根本不知道图片在哪，
# 手一滑改了还会把发布链路的目录解析弄断。改成只读状态条：
# 「已出图 N 张 · [打开文件夹] [更换配图]」。
MEDIA_FIELDS = {"image_hint", "shot_hint"}


def _to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v)


def _from_text(field: str, text: str) -> Any:
    """从编辑框读回字段值。

    只有 `topics` 是「标签列表」，要按空格 / 逗号拆开。
    `image_hint` / `shot_hint` 是**成句的说明**，以前也照拆 ——
    结果「已出图 8 张，目录：J:/…」被拆成 ['已出图','8','张','目录：J:/…']，
    发布时解析不出目录，配图就永远传不上去。
    """
    if field == "topics":
        raw = text.replace("\n", " ").replace("，", " ").replace(",", " ")
        return [x.strip().lstrip("#") for x in raw.split(" ") if x.strip()]
    return text


class ContentCard(QFrame):
    """可折叠的内容编辑卡片。"""

    changed = pyqtSignal(str)                 # platform_key
    request_regen = pyqtSignal(str)
    request_rewrite = pyqtSignal(str, str)    # (platform_key, 动作)
    request_save = pyqtSignal(str)
    request_fill = pyqtSignal(str)

    def __init__(self, platform_key: str, parent=None, compact: bool = False):
        super().__init__(parent)
        self.platform_key = platform_key
        self.compact = compact
        self.skill: Dict[str, Any] = {}
        self.topic = ""
        self.artifacts: List[str] = []
        self._editors: Dict[str, QWidget] = {}
        self._media_values: Dict[str, str] = {}    # MEDIA_FIELDS 的原始文本
        self._media_rows: Dict[str, "MediaRow"] = {}
        self._collapsed = False

        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            QFrame#Card {{ background:{theme.BG_CARD}; border:1px solid {theme.LINE};
                           border-radius:{theme.R_CARD}px; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ---------------- 头部
        head = QHBoxLayout()
        head.setSpacing(8)
        self.tag = TagDot(PF.short_of(platform_key), PF.color_of(platform_key))
        head.addWidget(self.tag)

        self.lb_platform = QLabel(PF.name_of(platform_key))
        self.lb_platform.setStyleSheet(
            f"background:transparent;{theme.css_font(14, 600)}color:{theme.TEXT_1};")
        head.addWidget(self.lb_platform)

        self.lb_skill = QLabel("")
        self.lb_skill.setStyleSheet(
            f"background:transparent;{theme.css_font(11.5, 500)}color:{theme.TEXT_3};")
        head.addWidget(self.lb_skill)

        head.addStretch(1)

        self.pill_status = Pill("待填充", theme.TEXT_2, theme.BG_INPUT)
        head.addWidget(self.pill_status)

        self.btn_toggle = IconButton("chevron_down", "折叠 / 展开", 26, 14)
        self.btn_toggle.clicked.connect(self.toggle)
        head.addWidget(self.btn_toggle)
        root.addLayout(head)

        # ---------------- 合规提示条
        self.bar = QLabel("")
        self.bar.setWordWrap(True)
        self.bar.setVisible(False)
        self.bar.setStyleSheet(
            f"background:{theme.DANGER_TINT};color:{theme.DANGER};border-radius:7px;"
            f"padding:7px 10px;{theme.css_font(12)}"
        )
        root.addWidget(self.bar)

        # ---------------- 字段区
        self.fields_box = QWidget()
        self.fields_lay = QVBoxLayout(self.fields_box)
        self.fields_lay.setContentsMargins(0, 0, 0, 0)
        self.fields_lay.setSpacing(9)
        root.addWidget(self.fields_box)

        # ---------------- 操作区
        root.addWidget(self._build_actions())

    # ---------------------------------------------------------- 操作栏
    def _build_actions(self) -> QWidget:
        bar = QFrame()
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame{{background:{theme.BG_SUBTLE};border:1px solid {theme.LINE};"
            f"border-radius:9px;}}")
        al = QHBoxLayout(bar)
        al.setContentsMargins(7, 6, 7, 6)
        al.setSpacing(4)
        self.actions = bar

        def mk(text: str, icon: str, tip: str, slot, primary: bool = False):
            b = QPushButton(text if not self.compact else "")
            b.setObjectName("Soft")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(icons.icon(icon, theme.PRIMARY if primary else theme.TEXT_2, 14))
            b.setToolTip(tip)
            b.setMinimumHeight(28)
            if self.compact:
                b.setFixedWidth(34)
            else:
                b.setMinimumWidth(0)
            b.clicked.connect(slot)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:1px solid transparent;"
                f"border-radius:7px;padding:4px 9px;{theme.css_font(12.5, 500)}"
                f"color:{theme.TEXT_2};}}"
                f"QPushButton:hover{{background:{theme.BG_CARD};border:1px solid {theme.LINE_STRONG};"
                f"color:{theme.TEXT_1};}}"
                f"QPushButton:pressed{{background:{theme.BG_HOVER};}}"
                f"QPushButton:disabled{{color:{theme.TEXT_4};}}"
            )
            return b

        self.btn_regen = mk("重新生成", "sparkle", "用当前选题重新生成这一份",
                            lambda: self.request_regen.emit(self.platform_key))
        self.btn_rewrite = mk("AI 改写", "edit", "扩写 / 精简 / 换角度 / 换人设",
                              self._rewrite_menu)
        self.btn_check = mk("发布前体检", "check",
                            "长度 / 必填 / 站外引流 / 排版 + 广告法词库，一次全查",
                            self.run_precheck)
        self.btn_copy = mk("复制全文", "copy", "把这份内容整段复制到剪贴板", self.copy_all)
        self.btn_save = mk("存入素材库", "folder", "归档到素材库，之后可复用",
                           lambda: self.request_save.emit(self.platform_key))

        for b in (self.btn_regen, self.btn_rewrite, self.btn_check,
                  self.btn_copy, self.btn_save):
            al.addWidget(b)
        al.addStretch(1)
        return bar

    # ---------------------------------------------------------- 数据
    def set_content(self, skill: Dict[str, Any], content: Dict[str, Any],
                    topic: str = "", slots: Dict[str, str] = None):
        self.skill = skill or {}
        self.topic = topic
        self.lb_skill.setText(skill.get("name", "") if skill else "")
        self._clear_fields()

        fields = self.skill.get("fields") or ["title", "body", "topics"]
        for f in fields:
            label = SK.field_label(f)
            val = _to_text(content.get(f, ""))
            self._add_field(f, label, val)
        # 模型多给的字段也展示出来，便于排查
        for k, v in (content or {}).items():
            if k not in fields:
                self._add_field(k, SK.field_label(k), _to_text(v), readonly=True)
        self.set_status("待填充", "info")

    def _clear_fields(self):
        theme.clear_layout(self.fields_lay)
        self._editors.clear()
        self._media_rows.clear()
        self._media_values.clear()

    def _add_field(self, field: str, label: str, value: str, readonly: bool = False):
        if field in MEDIA_FIELDS:
            self._add_media_field(field, label, value)
            return
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        lb = QLabel(label)
        lb.setStyleSheet(f"background:transparent;{theme.css_font(12, 600)}color:{theme.TEXT_3};")
        head.addWidget(lb)
        head.addStretch(1)

        cnt = QLabel()
        cnt.setStyleSheet(f"background:transparent;{theme.css_font(11.5)}color:{theme.TEXT_4};")
        head.addWidget(cnt)
        lay.addLayout(head)

        if field in MULTILINE:
            ed = QPlainTextEdit()
            ed.setPlainText(value)
            ed.setReadOnly(readonly)
            h = 150 if field in TALL else 58
            ed.setFixedHeight(h)
            ed.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            ed = QLineEdit(value)
            ed.setReadOnly(readonly)
            ed.setFixedHeight(34)

        if isinstance(ed, QPlainTextEdit):
            ed.textChanged.connect(lambda f=field: self._on_edit(f))
            self._limit_hint(field, ed.toPlainText, cnt)
        else:
            ed.textChanged.connect(lambda _t, f=field: self._on_edit(f))
            self._limit_hint(field, ed.text, cnt)

        self._editors[field] = ed
        lay.addWidget(ed)
        self.fields_lay.addWidget(box)

    # ---------------------------------------------------------- 媒体状态条
    def _add_media_field(self, field: str, label: str, value: str):
        """image_hint / shot_hint 的只读状态条。

        用户原话：「点开上传图片，根本不知道内容工坊生成的图片放到哪里去了」。
        一行小字路径 + 隐藏的 %APPDATA% 目录 = 无解。现在：
          · 数量与目录一眼可见（tooltip 给完整路径）
          · 「打开文件夹」一键直达
          · 「更换配图」选完自动回写目录，发布链路跟着更新
        原始文本仍保存在 _media_values，content() 原样带出，
        上传解析 / 体检 / 素材库的语义都不变。
        """
        self._media_values[field] = value
        row = MediaRow(field, label, self)
        row.open_requested.connect(self._open_media_folder)
        row.replace_requested.connect(self._replace_media)
        self._media_rows[field] = row
        self.fields_lay.addWidget(row)

    def _refresh_media_rows(self):
        for f, row in self._media_rows.items():
            row.refresh(self._media_values.get(f, ""), self.artifacts)

    def _open_media_folder(self, field: str):
        d = PF.media_dir_of(self.artifacts, self._media_values)
        if not PF.open_in_explorer(d):
            toast(self.window(), "还没找到生成的图片 / 视频目录", "warn")

    def _replace_media(self, field: str):
        """更换配图：选一个文件夹，里面的图片成为这份内容的配图。"""
        from PyQt6.QtWidgets import QFileDialog
        cur = PF.media_dir_of(self.artifacts, self._media_values)
        d = QFileDialog.getExistingDirectory(self.window(), "选择配图所在文件夹",
                                             cur or config.OUTPUT_DIR)
        if not d:
            return
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            toast(self.window(), f"读不了这个文件夹：{e}", "err")
            return
        imgs = [os.path.join(d, n) for n in names
                if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))]
        if not imgs:
            toast(self.window(), "这个文件夹里没有图片（png / jpg / webp / gif）", "warn")
            return
        # 保留风格描述行，重写目录行 —— 上传解析认「目录：」这个标记
        old = self._media_values.get(field, "")
        style = [ln for ln in old.splitlines()
                 if ln.strip() and "目录：" not in ln and "目录:" not in ln
                 and not ln.strip().startswith("已出图")]
        self._media_values[field] = "\n".join(style + [f"已出图 {len(imgs)} 张，目录：{d}"])
        self.artifacts = imgs
        self._refresh_media_rows()
        self.changed.emit(self.platform_key)
        toast(self.window(), f"已换上 {len(imgs)} 张配图，填充时会自动上传", "ok")

    def _limit_hint(self, field: str, getter, label: QLabel):
        limits = (self.skill.get("limits") or {})
        limit = limits.get(field)
        text = getter()
        if limit:
            n = len(text)
            color = theme.DANGER if n > limit else theme.TEXT_4
            label.setText(f"{n} / {limit}")
            label.setStyleSheet(f"background:transparent;{theme.css_font(11.5)}color:{color};")
        else:
            label.setText(f"{len(text)} 字")

    def _on_edit(self, field: str):
        ed = self._editors.get(field)
        if ed is None:
            return
        # 更新字数
        box = ed.parentWidget()
        if box:
            lbl = box.findChildren(QLabel)
            if len(lbl) >= 2:
                self._limit_hint(field, (ed.toPlainText if isinstance(ed, QPlainTextEdit)
                                         else ed.text), lbl[-1])
        self.changed.emit(self.platform_key)

    def content(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f, ed in self._editors.items():
            txt = ed.toPlainText() if isinstance(ed, QPlainTextEdit) else ed.text()
            out[f] = _from_text(f, txt)
        # media 字段没有编辑器（只读状态条），原始文本在这里
        out.update(self._media_values)
        return out

    def populated(self) -> bool:
        """卡片是否已经装载过内容。

        刚 new 出来、还没 set_content 的卡片 content() 返回空 dict，
        外部同步时如果拿它去覆盖草稿，就会把内容清空 —— 用这个先判断一下。
        """
        return bool(self._editors)

    # ---------------------------------------------------------- 状态
    def set_status(self, status: str, kind: str = "info", message: str = ""):
        colors = {
            "info": (theme.TEXT_2, theme.BG_INPUT),
            "ok": (theme.SUCCESS, theme.SUCCESS_TINT),
            "warn": (theme.WARNING, theme.WARNING_TINT),
            "err": (theme.DANGER, theme.DANGER_TINT),
            "run": (theme.PRIMARY, theme.PRIMARY_TINT),
        }
        c, bg = colors.get(kind, colors["info"])
        self.pill_status.setText(status)
        self.pill_status.setStyleSheet(
            f"background:{bg};color:{c};border-radius:9px;padding:3px 9px;"
            f"{theme.css_font(11.5, 600)}"
        )
        if message:
            self.pill_status.setToolTip(message)

    def set_busy(self, busy: bool, text: str = "生成中"):
        for b in (self.btn_regen, self.btn_rewrite, self.btn_check,
                  self.btn_copy, self.btn_save):
            b.setEnabled(not busy)
        self.set_status(text if busy else "待填充", "run" if busy else "info")

    def toggle(self):
        self._collapsed = not self._collapsed
        self.fields_box.setVisible(not self._collapsed)
        self.actions.setVisible(not self._collapsed)
        self.btn_toggle.set_icon_name(
            "chevron_right" if self._collapsed else "chevron_down")

    # ---------------------------------------------------------- 动作
    def _rewrite_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        for key, text in (("expand", "扩写（内容更充实）"),
                          ("shrink", "精简（更短更利落）"),
                          ("angle", "换角度重写"),
                          ("persona", "换人设重写")):
            act = menu.addAction(text)
            act.triggered.connect(
                lambda _=False, k=key: self.request_rewrite.emit(self.platform_key, k))
        menu.exec(self.btn_rewrite.mapToGlobal(self.btn_rewrite.rect().bottomLeft()))

    def run_check(self) -> int:
        """只跑词库检测，返回命中数。兼容旧调用。"""
        content = self.content()
        hits_by_field = compliance.check_content(content)
        high, mid = compliance.summarize(hits_by_field)
        if not hits_by_field:
            self.bar.setVisible(True)
            self.bar.setStyleSheet(
                f"background:{theme.SUCCESS_TINT};color:{theme.SUCCESS};border-radius:7px;"
                f"padding:7px 10px;{theme.css_font(12)}"
            )
            self.bar.setText("未发现词库中的风险词。仍建议人工通读一遍再发布。")
            return 0

        parts = []
        for f, hits in hits_by_field.items():
            words = "、".join(f"{h['word']}（{h['category']}）" for h in hits[:6])
            parts.append(f"{SK.field_label(f)}：{words}")
        self.bar.setVisible(True)
        self.bar.setStyleSheet(
            f"background:{theme.DANGER_TINT};color:{theme.DANGER};border-radius:7px;"
            f"padding:7px 10px;{theme.css_font(12)}"
        )
        head = f"命中 {high} 处高风险、{mid} 处中风险 —— "
        self.bar.setText(head + "；".join(parts))
        return high + mid

    # ---------------------------------------------------------- 发布前体检
    def precheck_issues(self):
        """字段规则问题清单（长度 / 必填 / 引流 / 排版）。"""
        return precheck.check(self.platform_key, self.content(), self.skill,
                              self.artifacts)

    def set_artifacts(self, paths):
        """pipeline 产出的图片 / 视频，供体检判断配图数量。

        顺手刷新媒体状态条 —— 生成完成的瞬间，用户就该在卡片上
        看到「已出图 N 张」和直达文件夹的按钮，而不是自己去找路径。
        """
        self.artifacts = [p for p in (paths or [])]
        self._refresh_media_rows()

    def attach_media(self, field: str, paths: List[str]):
        """外部（发布工作台）给这份内容挂上配图文件。

        与 _replace_media 同一套回写逻辑：保留风格描述行、重写目录行，
        卡片状态条即时反映。选完目录后发布链路（upload_files）就能拿到文件。
        """
        paths = [p for p in (paths or []) if p]
        if not paths:
            return
        d = os.path.dirname(paths[0]) if os.path.isfile(paths[0]) else ""
        old = self._media_values.get(field, "")
        style = [ln for ln in old.splitlines()
                 if ln.strip() and "目录：" not in ln and "目录:" not in ln
                 and not ln.strip().startswith("已出图")]
        self._media_values[field] = "\n".join(
            style + [f"已出图 {len(paths)} 张，目录：{d}"])
        self.artifacts = list(paths)
        self._refresh_media_rows()
        self.changed.emit(self.platform_key)

    def run_precheck(self, show_dialog: bool = True) -> int:
        """体检 + 词库一起跑，结果写进提示条，需要细节时弹窗。"""
        issues = self.precheck_issues()
        hits = compliance.check_content(self.content())
        high, mid = compliance.summarize(hits)
        n_err, n_warn, _ = precheck.summarize(issues)

        if not issues and not hits:
            self.bar.setVisible(True)
            self.bar.setStyleSheet(
                f"background:{theme.SUCCESS_TINT};color:{theme.SUCCESS};border-radius:7px;"
                f"padding:7px 10px;{theme.css_font(12)}")
            self.bar.setText("体检通过：字段长度、话题数量、排版、词库都没发现问题。")
            if show_dialog:
                from views.precheck_dialog import PrecheckDialog
                PrecheckDialog.show_for(self.window(), self.platform_key, [], {})
            return 0

        level = precheck.worst_level(issues)
        if high:
            level = "err"
        elif mid and level == "ok":
            level = "warn"
        color, bg = {
            "err": (theme.DANGER, theme.DANGER_TINT),
            "warn": (theme.WARNING, theme.WARNING_TINT),
            "info": (theme.PRIMARY, theme.PRIMARY_TINT),
        }.get(level, (theme.TEXT_2, theme.BG_INPUT))

        summary = precheck.one_line(issues)
        if hits:
            summary += f"；词库命中 {high} 处高风险、{mid} 处中风险"
        self.bar.setVisible(True)
        self.bar.setStyleSheet(
            f"background:{bg};color:{color};border-radius:7px;padding:7px 10px;"
            f"{theme.css_font(12)}")
        self.bar.setText("发布前体检：" + summary + "　（点「发布前体检」看逐条说明）")

        if show_dialog:
            from views.precheck_dialog import PrecheckDialog
            PrecheckDialog.show_for(self.window(), self.platform_key, issues, hits)
        return n_err * 10 + n_warn + high + mid

    def copy_all(self):
        from PyQt6.QtWidgets import QApplication
        content = self.content()
        text = self._plain_text(content)
        QApplication.clipboard().setText(text)
        toast(self.window(), f"已复制{PF.name_of(self.platform_key)}全文", "ok")

    def _plain_text(self, content: Dict[str, Any]) -> str:
        from publisher import fallback_text
        return fallback_text(content, self.skill.get("fields") or list(content.keys()))


class MediaRow(QFrame):
    """image_hint / shot_hint 的只读状态条。

    回答用户最高频的困惑「生成的图片放到哪里去了」：
    数量直接写在条上，完整目录挂在 tooltip，「打开文件夹」一键直达。
    """
    open_requested = pyqtSignal(str)      # field
    replace_requested = pyqtSignal(str)   # field

    _IMG = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    _VID = (".mp4", ".mov", ".m4v", ".webm")

    def __init__(self, field: str, label: str, parent=None):
        super().__init__(parent)
        self.field = field
        self.setObjectName("MediaRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#MediaRow{{background:{theme.BG_SUBTLE};"
            f"border:1px solid {theme.LINE};border-radius:9px;}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(8)

        self.ic = QLabel()
        self.ic.setPixmap(icons.icon("folder", theme.PRIMARY, 15).pixmap(15, 15))
        self.ic.setStyleSheet("background:transparent;border:none;")
        lay.addWidget(self.ic)

        self.lb = QLabel("")
        self.lb.setStyleSheet(
            f"background:transparent;border:none;{theme.css_font(12, 500)}"
            f"color:{theme.TEXT_2};")
        lay.addWidget(self.lb, 1)

        self.btn_open = QPushButton("打开文件夹")
        self.btn_open.setObjectName("Soft")
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setToolTip("在文件管理器里打开图片 / 视频所在的文件夹")
        self.btn_open.setMinimumHeight(26)
        self.btn_open.setStyleSheet(
            f"QPushButton{{background:{theme.BG_CARD};border:1px solid {theme.LINE_STRONG};"
            f"border-radius:7px;padding:3px 9px;{theme.css_font(11.5, 500)}"
            f"color:{theme.TEXT_1};}}"
            f"QPushButton:hover{{border-color:{theme.PRIMARY};color:{theme.PRIMARY};}}"
            f"QPushButton:disabled{{color:{theme.TEXT_4};}}")
        self.btn_open.clicked.connect(lambda: self.open_requested.emit(self.field))
        lay.addWidget(self.btn_open)

        self.btn_pick = None
        if field == "image_hint":
            self.btn_pick = QPushButton("更换配图")
            self.btn_pick.setObjectName("Soft")
            self.btn_pick.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_pick.setToolTip("换个文件夹里的图片作为这份内容的配图，"
                                     "填充时会自动上传新选的这些图")
            self.btn_pick.setMinimumHeight(26)
            self.btn_pick.setStyleSheet(self.btn_open.styleSheet())
            self.btn_pick.clicked.connect(lambda: self.replace_requested.emit(self.field))
            lay.addWidget(self.btn_pick)

    def refresh(self, text: str, artifacts: List[str]):
        artifacts = artifacts or []
        d = PF.media_dir_of(artifacts, {self.field: text or ""})
        if self.field == "shot_hint":
            vids = [p for p in artifacts if p.lower().endswith(self._VID)]
            if vids:
                self.lb.setText(f"短视频 · 视频已生成（{len(vids)} 个）")
            elif d:
                self.lb.setText("短视频 · 视频文件在所选目录里")
            else:
                self.lb.setText("短视频 · 还没有生成")
        else:
            n = len([p for p in artifacts if p.lower().endswith(self._IMG)])
            if not n and d and os.path.isdir(d):
                try:
                    n = len([x for x in os.listdir(d)
                             if x.lower().endswith(self._IMG)])
                except OSError:
                    n = 0
            self.lb.setText(f"配图 · 已出图 {n} 张" if n else "配图 · 还没有生成")
        self.lb.setToolTip(d or "还没有找到图片 / 视频所在的文件夹")
        self.btn_open.setEnabled(bool(d))
