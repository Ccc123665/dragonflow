"""设置：模型、发布策略、Skill 模板、词库、数据。"""
import os
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

import compliance
import config
import icons
import llm
import platforms as PF
import skills as SK
import store
import theme
from bus import BUS
from widgets.common import Badge, Card, IconButton, Pill, Switch, toast
from widgets.dialogs import MessageDialog


def _lb(text: str, obj: str = "Muted") -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(obj)
    if obj == "Hint":
        # 提示类长句必须换行。不换行的话，QLabel 的最小宽度 = 整句话的宽度，
        # 会把整个内容容器撑得比视口还宽 —— 而横向滚动条默认是关的，
        # 结果是这一行右侧的控件**静默消失**（不是压扁，是根本看不见、也滚不过去）。
        # 实测：设置页「内容模板」卡片里一句 60 字的提示把内容撑到 2170px，
        # 行尾的按钮直接跑到屏幕外。
        lb.setWordWrap(True)
    return lb


class SettingsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.s = store.load_settings()

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
        t = QLabel("设置")
        t.setObjectName("H2")
        bl.addWidget(t)
        bl.addStretch(1)
        self.btn_save = QPushButton("保存设置")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setIcon(icons.icon("check", "#FFFFFF", 15))
        self.btn_save.setMinimumHeight(34)
        self.btn_save.clicked.connect(self._save)
        bl.addWidget(self.btn_save)
        root.addWidget(bar)

        page = theme.PageScroll(max_width=900, top=18, bottom=28, spacing=16)
        root.addWidget(page, 1)
        lay = page.body

        lay.addWidget(self._model_card())
        lay.addWidget(self._publish_card())
        lay.addWidget(self._skills_card())
        lay.addWidget(self._words_card())
        lay.addWidget(self._data_card())
        lay.addWidget(self._about_card())
        lay.addStretch(1)

    # ================================================== 模型
    def _model_card(self) -> QWidget:
        card = Card(padding=18, spacing=12)
        h = QLabel("AI 模型")
        h.setObjectName("CardTitle")
        card.body.addWidget(h)
        card.body.addWidget(_lb(
            "接口由 Python 直接发起，不经过浏览器，因此不存在跨域限制。"
            "Key 只保存在本机配置文件，不会上传到任何第三方服务器。", "Hint"))

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_lb("服务商"))
        self.cb_provider = QComboBox()
        for k in llm.PROVIDER_ORDER:
            self.cb_provider.addItem(llm.PROVIDERS[k]["name"], k)
        i = self.cb_provider.findData(self.s.get("provider", "deepseek"))
        if i >= 0:
            self.cb_provider.setCurrentIndex(i)
        self.cb_provider.currentIndexChanged.connect(self._on_provider)
        row.addWidget(self.cb_provider, 1)

        row.addWidget(_lb("模型"))
        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)                 # 可下拉选，也可自己填
        self.cb_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._fill_models(self.s.get("provider", "deepseek"), self.s.get("model", ""))
        self.cb_model.setMinimumWidth(190)
        row.addWidget(self.cb_model, 1)

        self.btn_models = QPushButton("拉取可用模型")
        self.btn_models.setObjectName("Soft")
        self.btn_models.setMinimumHeight(34)
        self.btn_models.setToolTip("问服务端这个 Key 能用哪些模型，避免手抄错 ID")
        self.btn_models.clicked.connect(self._pull_models)
        row.addWidget(self.btn_models)
        card.body.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(_lb("接口地址"))
        self.ed_base = QLineEdit(self.s.get("base_url", ""))
        row2.addWidget(self.ed_base, 2)
        card.body.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(10)
        row3.addWidget(_lb("API Key"))
        self.ed_key = QLineEdit(self.s.get("api_key", ""))
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setPlaceholderText("粘贴你的 API Key")
        row3.addWidget(self.ed_key, 2)

        self.btn_test = QPushButton("测试连接")
        self.btn_test.setObjectName("Soft")
        self.btn_test.setMinimumHeight(34)
        self.btn_test.clicked.connect(self._test)
        row3.addWidget(self.btn_test)
        card.body.addLayout(row3)

        self.lb_test = QLabel("")
        self.lb_test.setObjectName("Hint")
        self.lb_test.setWordWrap(True)
        card.body.addWidget(self.lb_test)

        row4 = QHBoxLayout()
        row4.setSpacing(10)
        row4.addWidget(_lb("创意度"))
        self.sp_temp = QDoubleSpinBox()
        self.sp_temp.setRange(0.0, 1.5)
        self.sp_temp.setSingleStep(0.1)
        self.sp_temp.setValue(float(self.s.get("temperature", 0.8)))
        row4.addWidget(self.sp_temp)

        row4.addWidget(_lb("单次输出上限"))
        self.sp_tokens = QSpinBox()
        self.sp_tokens.setRange(500, llm.MAX_OUTPUT_CEILING)
        self.sp_tokens.setSingleStep(500)
        self.sp_tokens.setValue(int(self.s.get("max_tokens", 3000)))
        row4.addWidget(self.sp_tokens)
        row4.addStretch(1)
        card.body.addLayout(row4)

        self.lb_budget = QLabel("")
        self.lb_budget.setObjectName("Hint")
        self.lb_budget.setWordWrap(True)
        card.body.addWidget(self.lb_budget)
        self.cb_model.currentTextChanged.connect(lambda _t: self._refresh_budget())
        self.sp_tokens.valueChanged.connect(lambda _v: self._refresh_budget())
        self._refresh_budget()
        return card

    def _refresh_budget(self):
        """把「实际发出去的输出额度」写清楚 —— 推理模型的思考也占额度。"""
        probe = {
            "provider": self.cb_provider.currentData(),
            "model": self.cb_model.currentText().strip(),
            "max_tokens": self.sp_tokens.value(),
        }
        eff = llm.effective_max_tokens(probe)
        if llm.is_reasoning(probe):
            self.lb_budget.setText(
                f"注意：当前是推理模型，思考过程也占用输出额度 —— 实际按 {eff} 发出"
                f"（下限 {llm.REASONING_FLOOR}）。写长正文时建议把上限调到 8000 以上，"
                f"否则会出现「思考完没额度写正文」。")
        else:
            self.lb_budget.setText(f"实际按 {eff} 发出。")

    # ================================================== 模型名下拉
    def _fill_models(self, provider_key: str, keep: str = ""):
        """按服务商预设填模型下拉。keep 有值时保留用户当前填的，别被预设冲掉。"""
        cur = (keep or self.cb_model.currentText() or "").strip()
        preset = llm.PROVIDERS.get(provider_key, {})
        names = list(preset.get("models") or [])
        if cur and cur not in names:
            names.insert(0, cur)
        self.cb_model.blockSignals(True)
        self.cb_model.clear()
        self.cb_model.addItems(names)
        self.cb_model.setCurrentText(cur or (names[0] if names else ""))
        self.cb_model.blockSignals(False)

    def _pull_models(self):
        s = self._collect()
        if not s["api_key"].strip():
            toast(self.window(), "先填 API Key", "warn")
            return
        self.btn_models.setEnabled(False)
        self.btn_models.setText("拉取中…")
        self._mtask = llm.ListModelsTask(s, self)
        self._mtask.done.connect(self._on_models)
        self._mtask.failed.connect(self._on_models_fail)
        self._mtask.start()

    def _on_models(self, names: list):
        self.btn_models.setEnabled(True)
        self.btn_models.setText("拉取可用模型")
        if not names:
            self.lb_test.setText("服务端没返回任何模型，可能该接口不支持 /models")
            self.lb_test.setStyleSheet(
                f"background:transparent;{theme.css_font(12)}color:{theme.WARNING};")
            return
        cur = self.cb_model.currentText().strip()
        self.cb_model.blockSignals(True)
        self.cb_model.clear()
        self.cb_model.addItems(names)
        # 当前填的 ID 不在列表里 → 直接切到第一个可用项，省得用户再试一次
        self.cb_model.setCurrentText(cur if cur in names else names[0])
        self.cb_model.blockSignals(False)
        self.lb_test.setText(f"拉到 {len(names)} 个可用模型：{'、'.join(names)}")
        self.lb_test.setStyleSheet(
            f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_2};")
        self._refresh_budget()
        if cur and cur not in names:
            toast(self.window(), f"「{cur}」不在可用列表里，已切到 {names[0]}", "warn", 5000)

    def _on_models_fail(self, err: str):
        self.btn_models.setEnabled(True)
        self.btn_models.setText("拉取可用模型")
        self.lb_test.setText(f"拉取失败：{err}")
        self.lb_test.setStyleSheet(
            f"background:transparent;{theme.css_font(12)}color:{theme.DANGER};")

    def _on_provider(self, _i):
        key = self.cb_provider.currentData()
        preset = llm.PROVIDERS.get(key, {})
        if key != "custom":
            self.ed_base.setText(preset.get("base_url", ""))
            self._fill_models(key, preset.get("model", ""))
        else:
            self._fill_models(key)
        self.lb_test.setText(preset.get("help", ""))
        self.lb_test.setStyleSheet(
            f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_3};")
        self._refresh_budget()

    def _test(self):
        s = self._collect()
        if not s["api_key"].strip():
            toast(self.window(), "先填 API Key", "warn")
            return
        self.btn_test.setEnabled(False)
        self.lb_test.setText("正在测试…")
        self._task = llm.TestTask(s, self)
        self._task.done.connect(self._on_test_ok)
        self._task.failed.connect(self._on_test_fail)
        self._task.start()

    def _on_test_ok(self, text: str):
        self.btn_test.setEnabled(True)
        self.lb_test.setText(f"连接正常，模型回复：{text}")
        self.lb_test.setStyleSheet(f"background:transparent;{theme.css_font(12)}color:{theme.SUCCESS};")
        toast(self.window(), "模型连接正常", "ok")

    def _on_test_fail(self, err: str):
        self.btn_test.setEnabled(True)
        self.lb_test.setText(f"连接失败：{err}")
        self.lb_test.setStyleSheet(f"background:transparent;{theme.css_font(12)}color:{theme.DANGER};")
        toast(self.window(), "连接失败，请检查配置", "err")

        # 服务端明确说了「支持的模型是 X、Y」→ 直接把候选填进下拉，用户点一下就好
        hint = llm.suggest_models(err)
        if hint:
            cur = self.cb_model.currentText().strip()
            self.cb_model.blockSignals(True)
            self.cb_model.clear()
            self.cb_model.addItems(hint)
            self.cb_model.setCurrentText(hint[0])
            self.cb_model.blockSignals(False)
            self.lb_test.setText(
                f"连接失败：模型名不对。「{cur}」是显示名，接口认的是 ID。"
                f"已帮你把模型改成 {hint[0]}，点「测试连接」再试一次。")
            self._refresh_budget()
            toast(self.window(), f"模型名已改为 {hint[0]}，再点一次「测试连接」", "warn", 6000)

    # ================================================== 发布
    def _publish_card(self) -> QWidget:
        card = Card(padding=18, spacing=12)
        h = QLabel("发布策略")
        h.setObjectName("CardTitle")
        card.body.addWidget(h)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_lb("平台间发布间隔"))
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(0, 600)
        self.sp_interval.setSuffix(" 秒")
        self.sp_interval.setValue(int(self.s.get("publish_interval", 8)))
        row.addWidget(self.sp_interval)

        row.addWidget(_lb("单账号单日上限"))
        self.sp_daily = QSpinBox()
        self.sp_daily.setRange(1, 200)
        self.sp_daily.setSuffix(" 条")
        self.sp_daily.setValue(int(self.s.get("daily_limit", 10)))
        row.addWidget(self.sp_daily)
        row.addStretch(1)
        card.body.addLayout(row)

        card.body.addWidget(_lb(
            "发布动作全部由人工触发，程序不做任何定时或无人值守的批量分发。"
            "间隔与上限只用于降低短时间高频操作带来的风控风险，"
            "不构成对账号安全的承诺。", "Hint"))

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(_lb("硬件加速"))
        self.sw_gpu = Switch(checked=bool(self.s.get("hardware_accel", False)))
        row2.addWidget(self.sw_gpu)
        row2.addWidget(_lb("关闭可解决老机器或远程桌面下的白屏、卡顿（需重启生效）"))
        row2.addStretch(1)
        card.body.addLayout(row2)
        return card

    # ================================================== Skill
    def _skills_card(self) -> QWidget:
        card = Card(padding=18, spacing=12)
        head = QHBoxLayout()
        head.setSpacing(8)
        h = QLabel("内容模板 Skill")
        h.setObjectName("CardTitle")
        head.addWidget(h)
        self.lb_skill_count = Badge("0")
        head.addWidget(self.lb_skill_count)
        head.addStretch(1)

        b_up = QPushButton("上传 Skill  ▾")
        b_up.setObjectName("Primary")
        b_up.setIcon(icons.icon("upload", "#FFFFFF", 15))
        b_up.setMinimumHeight(34)
        b_up.setToolTip(
            "三种方式：选模板文件（.json/.md/.txt）、选整个 Skill 文件夹、"
            "导入 .zip 压缩包。文件夹里带 SKILL.md 会按「Skill 包」处理。")
        b_up.clicked.connect(lambda _=False, b=b_up: self._upload_menu(b))
        head.addWidget(b_up)

        b_new = QPushButton("新建")
        b_new.setObjectName("Soft")
        b_new.setMinimumHeight(34)
        b_new.clicked.connect(self._new_skill)
        head.addWidget(b_new)

        b_audit = QPushButton("自检")
        b_audit.setObjectName("Soft")
        b_audit.setMinimumHeight(34)
        b_audit.setToolTip("逐个检查这些模板能不能真的跑起来："
                           "流水线有没有运行器、生成指令是否为空、"
                           "是不是描述了做不了的动作")
        b_audit.clicked.connect(self._audit_skills)
        head.addWidget(b_audit)

        b_exp = QPushButton("导出")
        b_exp.setObjectName("Soft")
        b_exp.setMinimumHeight(34)
        b_exp.clicked.connect(self._export_skills)
        head.addWidget(b_exp)

        b_reset = QPushButton("恢复内置")
        b_reset.setObjectName("Soft")
        b_reset.setMinimumHeight(34)
        b_reset.setToolTip("把被停用 / 删除的内置模板找回来")
        b_reset.clicked.connect(self._restore_builtins)
        head.addWidget(b_reset)
        card.body.addLayout(head)

        card.body.addWidget(_lb(
            "每个平台的内容由这里的模板决定。模板有三种形态："
            "「模板」走一次模型生成，「流水线」会跑抓取 / 出图 / 渲染视频等多步流程，"
            "「Skill 包」是整目录导入的 SKILL.md 方法论。"
            "内置模板可以「停用」或删除；上传自己的模板后，在内容工坊的「内容模板」里选它即可。", "Hint"))
        card.body.addWidget(_lb(f"Skill 目录：{config.SKILLS_DIR}", "Hint"))

        self.skills_box = QWidget()
        self.skills_lay = QVBoxLayout(self.skills_box)
        self.skills_lay.setContentsMargins(0, 0, 0, 0)
        self.skills_lay.setSpacing(6)
        card.body.addWidget(self.skills_box)
        self._fill_skills()
        return card

    def _fill_skills(self):
        theme.clear_layout(self.skills_lay)
        items = SK.all_skills(include_disabled=True)
        disabled = set(SK.load_user().get("disabled", []))
        self.lb_skill_count.setText(str(len(items)))

        for sk in items:
            off = sk["id"] in disabled
            row = QWidget()
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row.setStyleSheet(
                f"background:{theme.BG_SUBTLE};border:1px solid {theme.LINE};"
                f"border-radius:9px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 8, 8, 8)
            rl.setSpacing(10)

            name = QLabel(sk.get("name", ""))
            name.setStyleSheet(
                f"background:transparent;{theme.css_font(13.5, 600)}"
                f"color:{theme.TEXT_4 if off else theme.TEXT_1};")
            # 名字列要**可收窄**（换行）：名称 150 + 平台/类型胶囊 ×3~4 +
            # 描述 + 停用/编辑/删除按钮的最小宽度，曾把设置页撑出横向溢出
            # （回归自检抓的：默认窗口宽下溢出 22px，行尾按钮被挤出屏幕）。
            # 宽窗口下仍是最多 150px，视觉不变；窄了才换行让路。
            name.setWordWrap(True)
            name.setMinimumWidth(112)
            name.setMaximumWidth(150)
            name.setToolTip(sk.get("desc", ""))
            rl.addWidget(name)

            pk_name = PF.name_of(sk.get("platform", ""))
            if len(pk_name) > 8:
                pk_name = pk_name[:7] + "…"   # 自定义平台名可能很长，会把整行撑宽
            rl.addWidget(Pill(pk_name, theme.TEXT_2, theme.BG_INPUT))
            if SK.is_pipeline(sk):
                rl.addWidget(Pill("流水线", theme.PRIMARY, theme.PRIMARY_TINT))
            elif SK.kind_of(sk) == "bundle":
                rl.addWidget(Pill("Skill 包", theme.WARNING, theme.WARNING_TINT))
            if sk.get("builtin"):
                rl.addWidget(Pill("内置", theme.TEXT_3, theme.BG_INPUT))
            else:
                rl.addWidget(Pill("自定义", theme.PRIMARY, theme.PRIMARY_TINT))
            if off:
                rl.addWidget(Pill("已停用", theme.WARNING, theme.WARNING_TINT))

            # 可用性：装上了不代表能用。有必改问题的标红，有提醒的标黄，
            # 鼠标悬停看具体原因 —— 免得点了生成才发现跑不动。
            issues = SK.check_skill(sk)
            n_err, n_warn, _ = SK.issue_counts(issues)
            if n_err:
                p = Pill(f"不可用 {n_err}", theme.DANGER, theme.DANGER_TINT)
                p.setToolTip("\n".join("· " + i["text"] for i in issues
                                       if i["level"] == "err"))
                rl.addWidget(p)
            elif n_warn:
                p = Pill(f"注意 {n_warn}", theme.WARNING, theme.WARNING_TINT)
                p.setToolTip("\n".join("· " + i["text"] for i in issues
                                       if i["level"] == "warn"))
                rl.addWidget(p)

            desc = QLabel(sk.get("desc", ""))
            desc.setStyleSheet(f"background:transparent;{theme.css_font(12)}color:{theme.TEXT_3};")
            # 模板描述经常很长（流水线那种一句话能到 40 字）。不换行的话
            # QLabel 的最小宽度 = 整句宽度，会把这一行、进而把整张卡片、整页撑宽，
            # 行尾的「停用 / 编辑 / 删除」按钮就被挤出屏幕了。
            desc.setWordWrap(True)
            # 不设最小宽度 —— 描述是这行里带 stretch 的元素，
            # 换行标签可以收得很窄，窄窗口下由它负责「让路」
            rl.addWidget(desc, 1)

            b_toggle = QPushButton("启用" if off else "停用")
            b_toggle.setObjectName("Ghost")
            b_toggle.clicked.connect(
                lambda _=False, s=sk, o=off: self._toggle_skill(s, not o))
            rl.addWidget(b_toggle)

            b_edit = QPushButton("编辑")
            b_edit.setObjectName("Ghost")
            b_edit.clicked.connect(lambda _=False, s=sk: self._edit_skill(s))
            rl.addWidget(b_edit)

            b_del = IconButton("trash", "删除模板", 26, 14)
            b_del.clicked.connect(lambda _=False, s=sk: self._del_skill(s))
            rl.addWidget(b_del)
            self.skills_lay.addWidget(row)

        if not items:
            hint = QLabel("还没有任何模板。点右上角「上传 Skill」把你自己的模板传进来。")
            hint.setStyleSheet(
                f"background:transparent;{theme.css_font(12.5)}color:{theme.TEXT_3};"
                f"padding:18px 4px;")
            self.skills_lay.addWidget(hint)

    def _upload_menu(self, anchor):
        """上传入口：文件 / 文件夹 / 压缩包三选一。

        之前只调 getOpenFileNames，所以只能选文件 —— 文件夹和压缩包都点不进去，
        这是用户反馈「为什么选不了文件夹或者压缩包」的原因。
        """
        from PyQt6.QtWidgets import QMenu
        m = QMenu(self.window())
        m.addAction("选择模板文件…（.json / .md / .txt，可多选）",
                    self._upload_files)
        m.addAction("选择 Skill 文件夹…（整个目录，含附件）",
                    self._upload_folder)
        m.addAction("导入压缩包…（.zip）", self._upload_zip)
        m.addSeparator()
        a = m.addAction("打开 Skill 目录", self._open_skill_dir)
        a.setEnabled(os.path.isdir(config.SKILLS_DIR))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _upload_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self.window(), "上传 Skill 模板", "",
            "Skill 模板 (*.json *.md *.markdown *.txt *.zip);;"
            "模板文件 (*.json *.md *.markdown *.txt);;"
            "压缩包 (*.zip);;所有文件 (*.*)")
        self._do_import(paths)

    def _upload_folder(self):
        path = QFileDialog.getExistingDirectory(
            self.window(), "选择 Skill 文件夹（整包导入，含 SKILL.md 与附件）")
        if path:
            self._do_import([path])

    def _upload_zip(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self.window(), "导入 Skill 压缩包", "", "压缩包 (*.zip);;所有文件 (*.*)")
        self._do_import(paths)

    def _open_skill_dir(self):
        _open_path(config.SKILLS_DIR)

    def _do_import(self, paths):
        if not paths:
            return
        n, msgs = SK.import_files(paths)
        self._fill_skills()
        BUS.settings_changed.emit()
        if n:
            packs = [s for s in SK.all_skills() if s.get("pack_dir")]
            tail = f"（其中 {len(packs)} 个是整包导入的 Skill）" if packs else ""
            toast(self.window(),
                  f"已导入 {n} 个模板{tail}，去内容工坊的「内容模板」里选它",
                  "ok", 4600)
        if msgs:
            # 两类消息要分开说：导入失败（路径/格式问题）和
            # 「导进来了但这个模板跑不动」（可用性自检）。混在一起说
            # 用户会以为全部失败了。
            notes = [m for m in msgs if "不可用：" in m or "要注意：" in m]
            failed = [m for m in msgs if m not in notes]
            if failed and not notes:
                MessageDialog.alert(self.window(), "部分内容没导入成功",
                                    f"成功 {n} 个，以下路径有问题：", kind="warn",
                                    detail="\n".join(failed[:8]))
            elif notes and not failed:
                MessageDialog.alert(
                    self.window(), "导入完成，但有几个模板要留意",
                    f"已导入 {n} 个模板。下面这些不能直接用：", kind="warn",
                    detail="\n".join(notes[:8])
                           + "\n\n点右上角「自检」可以随时重新检查全部模板。")
            else:
                MessageDialog.alert(
                    self.window(), "导入完成，但有需要注意的地方",
                    f"成功 {n} 个。以下路径没导入：", kind="warn",
                    detail="\n".join(failed[:5])
                           + "\n\n【模板可用性】\n" + "\n".join(notes[:5]))
        if not n and not msgs:
            toast(self.window(), "没有导入任何模板", "warn")

    def _toggle_skill(self, sk: Dict[str, Any], disable: bool):
        SK.set_disabled(sk["id"], disable)
        self._fill_skills()
        BUS.settings_changed.emit()
        toast(self.window(), f"已{'停用' if disable else '启用'}「{sk.get('name')}」", "ok")

    def _restore_builtins(self):
        n = SK.restore_builtins()
        self._fill_skills()
        BUS.settings_changed.emit()
        toast(self.window(), f"内置模板已恢复（共 {n} 个）", "ok")

    def _new_skill(self):
        from views.skill_dialog import SkillDialog
        d = SkillDialog(self.window(), None)
        if d.exec():
            self._fill_skills()
            BUS.settings_changed.emit()
            toast(self.window(), "模板已创建", "ok")

    def _edit_skill(self, sk: Dict[str, Any]):
        from views.skill_dialog import SkillDialog
        d = SkillDialog(self.window(), sk)
        if d.exec():
            self._fill_skills()
            BUS.settings_changed.emit()
            toast(self.window(), "模板已保存", "ok")

    def _del_skill(self, sk: Dict[str, Any]):
        ok = MessageDialog.confirm(
            self.window(), "删除模板",
            f"确定删除「{sk.get('name')}」吗？",
            kind="err",
            detail="内置模板删除后可以点「恢复内置」找回；自定义模板删除后不可恢复。",
            ok_text="删除", cancel_text="取消")
        if not ok:
            return
        SK.delete_skill(sk["id"])
        self._fill_skills()
        BUS.settings_changed.emit()

    def _export_skills(self):
        path, _ = QFileDialog.getSaveFileName(
            self.window(), "导出 Skill 模板", "dragonflow-skills.json", "JSON (*.json)")
        if not path:
            return
        SK.export_skills(path)
        toast(self.window(), "模板已导出", "ok")

    def _audit_skills(self):
        """逐个检查模板能不能真的跑起来，把问题摊开说。"""
        bad = SK.audit_all()
        total = len(SK.all_skills(include_disabled=True))
        if not bad:
            MessageDialog.alert(
                self.window(), "模板自检", f"{total} 个模板全部可用。",
                kind="info", detail="流水线都有运行器，生成指令都非空。")
            return

        lines = []
        n_err = n_warn = 0
        for sk, issues in bad:
            e, w, _ = SK.issue_counts(issues)
            n_err += e
            n_warn += w
            lines.append(f"【{sk.get('name', '')}】"
                         f"{'（已停用）' if SK.is_disabled(sk['id']) else ''}")
            for i in issues:
                mark = {"err": "✕", "warn": "!", "info": "·"}.get(i["level"], "·")
                lines.append(f"  {mark} {i['text']}")
            lines.append("")
        head = (f"{total} 个模板里 {len(bad)} 个有问题："
                f"{n_err} 项不可用、{n_warn} 项要注意。")
        MessageDialog.alert(
            self.window(), "模板自检", head, kind="warn" if n_err else "info",
            detail="\n".join(lines).strip())

    # ================================================== 词库
    def _words_card(self) -> QWidget:
        card = Card(padding=18, spacing=12)
        h = QLabel("合规词库")
        h.setObjectName("CardTitle")
        card.body.addWidget(h)
        card.body.addWidget(_lb(
            "每行一个词。修改后只影响本机，内置词库文件不会被覆盖。"
            "检测结果仅作提醒，最终仍需人工通读确认。", "Hint"))

        tabs = QTabWidget()
        self._word_editors: Dict[str, QPlainTextEdit] = {}
        for cat in compliance.all_categories():
            ed = QPlainTextEdit()
            ed.setPlainText("\n".join(cat.get("words", [])))
            ed.setPlaceholderText("每行一个词")
            self._word_editors[cat["key"]] = ed
            tabs.addTab(ed, f"{cat['name']}（{len(cat.get('words', []))}）")
        card.body.addWidget(tabs)

        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton("保存词库")
        b.setObjectName("Soft")
        b.setMinimumHeight(34)
        b.clicked.connect(self._save_words)
        row.addWidget(b)
        card.body.addLayout(row)
        return card

    def _save_words(self):
        import compliance as C
        builtin = C.load_builtin()
        user = C.load_user()
        user.setdefault("extra", {})
        user.setdefault("disabled", [])
        for cat in builtin.get("categories", []):
            key = cat["key"]
            ed = self._word_editors.get(key)
            if ed is None:
                continue
            new = {w.strip() for w in ed.toPlainText().split("\n") if w.strip()}
            base = set(cat.get("words", []))
            user["extra"][key] = sorted(new - base)
            user["disabled"] = sorted(set(user["disabled"]) | (base - new))
        C.save_user(user)
        toast(self.window(), "词库已保存", "ok")

    # ================================================== 数据
    def _data_card(self) -> QWidget:
        card = Card(padding=18, spacing=12)
        h = QLabel("数据与备份")
        h.setObjectName("CardTitle")
        card.body.addWidget(h)

        row = QHBoxLayout()
        row.setSpacing(8)
        for text, fn in (("备份到文件", self._backup),
                         ("导出配置包", self._export_pack),
                         ("导入配置包", self._import_pack),
                         ("打开数据目录", self._open_data),
                         ("查看日志", self._open_log)):
            b = QPushButton(text)
            b.setObjectName("Soft")
            b.setMinimumHeight(34)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        card.body.addLayout(row)

        card.body.addWidget(_lb(f"数据目录：{config.DATA_DIR}", "Hint"))
        card.body.addWidget(_lb(
            "配置包包含 Skill 模板、词库和发布策略，不含 API Key，可直接发给同事。", "Hint"))
        return card

    def _backup(self):
        path = store.backup_now()
        toast(self.window(), f"已备份到 {os.path.basename(path)}", "ok")

    def _export_pack(self):
        path, _ = QFileDialog.getSaveFileName(
            self.window(), "导出配置包", "dragonflow-config.json", "JSON (*.json)")
        if not path:
            return
        store.export_all(path)
        toast(self.window(), "配置包已导出", "ok")

    def _import_pack(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window(), "导入配置包", "", "JSON (*.json)")
        if not path:
            return
        ok = MessageDialog.confirm(
            self.window(), "导入配置包",
            "导入会覆盖本机的账号、模板与词库。",
            kind="warn", detail="原数据会自动备份一份，继续？",
            ok_text="继续导入", cancel_text="取消")
        if not ok:
            return
        try:
            store.import_all(path)
        except Exception as e:
            toast(self.window(), f"导入失败：{e}", "err")
            return
        self._fill_skills()
        BUS.accounts_changed.emit()
        BUS.settings_changed.emit()
        toast(self.window(), "配置包已导入", "ok")

    def _open_data(self):
        _open_path(config.DATA_DIR)

    def _open_log(self):
        from widgets.dialogs import BaseDialog
        d = BaseDialog(self.window(), "操作日志", "最近 400 行", width=780, height=520)
        ed = QPlainTextEdit()
        ed.setReadOnly(True)
        ed.setPlainText("".join(store.read_log(400)))
        d.body.addWidget(ed, 1)
        d.add_stretch()
        d.add_button("关闭", "Soft", d.reject)
        d.exec()

    # ================================================== 关于
    def _about_card(self) -> QWidget:
        card = Card(padding=18, spacing=8)
        h = QLabel(f"{config.APP_NAME}")
        h.setObjectName("CardTitle")
        card.body.addWidget(h)
        card.body.addWidget(_lb(f"{config.APP_SUBTITLE} · v{config.APP_VERSION}"))
        card.body.addWidget(_lb(
            "本工具提供内容生产与发布页填充能力，所有登录与发布动作均由人工触发。"
            "账号只保存名称与备注，不保存任何密码。请遵守各平台规则使用。", "Hint"))
        return card

    # ================================================== 保存
    def _collect(self) -> Dict[str, Any]:
        s = dict(self.s)
        s.update({
            "provider": self.cb_provider.currentData(),
            "api_key": self.ed_key.text().strip(),
            "base_url": self.ed_base.text().strip(),
            "model": self.cb_model.currentText().strip(),
            "temperature": float(self.sp_temp.value()),
            "max_tokens": int(self.sp_tokens.value()),
            "publish_interval": int(self.sp_interval.value()),
            "daily_limit": int(self.sp_daily.value()),
            "hardware_accel": self.sw_gpu.isChecked(),
        })
        return s

    def _save(self):
        self.s = self._collect()
        store.save_settings(self.s)
        BUS.settings_changed.emit()
        toast(self.window(), "设置已保存", "ok")


def _open_path(path: str):
    import subprocess
    import sys
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)          # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
