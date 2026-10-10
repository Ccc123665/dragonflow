"""启动自检：验证 main.py 的初始化顺序在真实环境下能跑通。

存在的意义：`main()` 里两处顺序都是「错了就静默崩进程、退出码 127、无任何报错」的坑，
只有真正跑一遍才能发现。这个测试就是跑一遍。

  坑 1：QtWebEngineWidgets 必须在 QApplication 之前导入
  坑 2：theme.init_font() 必须在 QApplication 之后调用（QFontDatabase 依赖它）

用法：
    python tests/test_startup.py
"""
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu --disable-software-rasterizer --no-sandbox"
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

fails = []


def check(name, cond, detail=""):
    print(f"  {'[OK]  ' if cond else '[FAIL]'} {name}" + (f"  → {detail}" if detail else ""),
          flush=True)
    if not cond:
        fails.append(name)


def main():
    print("\n=== 启动自检 ===\n")
    try:
        import main as M
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        check("main 模块导入成功（含 WebEngine）", True)

        app = QApplication(sys.argv)
        check("QApplication 创建成功", True)

        # 关键顺序：必须在 QApplication 之后
        try:
            M.theme.init_font()
            check("theme.init_font() 在 QApplication 之后调用成功", True,
                  f"字体 = {M.theme.FONT_FAMILY}")
        except RuntimeError as e:
            check("theme.init_font() 顺序正确", False, str(e))

        app.setApplicationName(M.config.APP_NAME)
        app.setStyleSheet(M.theme.style())
        app.setFont(M.theme.font(14))
        check("样式表生成成功", len(M.theme.style()) > 1000,
              f"{len(M.theme.style())} 字符")

        win = M.MainWindow()
        M.theme.apply_styled_bg(win)
        win.show()
        check("MainWindow 构建 + show 成功", win.isVisible(),
              f"{win.width()}x{win.height()}")

        from browser import BROWSER
        check("浏览器共享视图已挂载", BROWSER.view() is not None)

        # 六个视图都建出来了
        for attr, label in (("studio_view", "内容工坊"), ("workbench_view", "发布工作台"),
                            ("library_view", "素材库"), ("records_view", "发布记录"),
                            ("dashboard_view", "数据看板"),
                            ("settings_view", "设置")):
            check(f"{label} 视图已构建", getattr(win, attr, None) is not None)

        # 导航与视图栈必须一一对应（错位会让点「数据看板」跳到设置）
        check("NAV 与 VIEW_ORDER 前 5 项一致",
              [k for k, _, _ in M.NAV] == M.VIEW_ORDER[:len(M.NAV)],
              f"{[k for k, _, _ in M.NAV]}")
        check("视图栈数量 = NAV + 设置",
              win.stack.count() == len(M.NAV) + 1, f"{win.stack.count()} 个")

        # 内容流水线运行器（公众号转图文 / 文案转视频）
        import pipelines as PL
        check("内容流水线运行器已注册", set(PL.keys()) >= {"gzh_to_xhs", "xhs_video"},
              "、".join(PL.keys()))
        for p in PL.all_pipelines():
            check(f"  流水线 {p.name} 的输入项可读", isinstance(p.inputs(), list),
                  f"{len(p.inputs())} 项")

        # 发布前体检规则
        import precheck
        import platforms as PF
        with_rules = [p["key"] for p in PF.all_platforms() if precheck.rules_of(p["key"])]
        check("发布前体检规则已加载", len(with_rules) >= 5, "、".join(with_rules))
        _iss = precheck.check("xhs", {"title": "超" * 40, "body": "短"},
                              {"fields": ["title", "body"]})
        check("体检能识别超长标题", any(i.level == "err" for i in _iss),
              precheck.one_line(_iss))

        # ---- 模型网关：模型名 / 推理模型额度 / 错误整理 ----
        import llm
        _prov = llm.PROVIDERS["deepseek"]
        check("DeepSeek 预设填的是接口 ID 而不是显示名",
              _prov["model"] == "deepseek-flash" and "DeepSeek" not in _prov["model"],
              _prov["model"])
        check("每个服务商都带了可选模型列表",
              all(isinstance(v.get("models"), list) for v in llm.PROVIDERS.values()),
              "、".join(f"{k}:{len(v.get('models') or [])}" for k, v in llm.PROVIDERS.items()))

        # 显示名 → 接口 ID 的建议，从服务端报错里抠
        _err = ('The supported API model names are deepseek-flash, deepseek-v4-pro, '
                'but you passed DeepSeek-V4.1-Flash. (request_id: 0199dd14-8ea8)')
        check("能从报错里抠出可用模型 ID",
              llm.suggest_models(_err) == ["deepseek-flash", "deepseek-v4-pro"],
              str(llm.suggest_models(_err)))
        check("suggest_models 对无关文本不误报", llm.suggest_models("网络连接失败") == [])

        _clean = llm.clean_error(400, '{"error":{"message":"' + _err + '","type":"x","param":null}}')
        check("错误整理去掉了 request_id 和 JSON 噪声",
              "request_id" not in _clean and "param" not in _clean and "接口返回" not in _clean,
              _clean.splitlines()[0][:60])
        check("错误整理附带了「改成什么」的建议",
              "deepseek-flash" in _clean and "把「模型」改成" in _clean)

        # 推理模型的额度下限（思考也占输出额度）
        _rs = {"provider": "deepseek", "model": "deepseek-flash", "max_tokens": 1200}
        check("推理模型能被识别", llm.is_reasoning(_rs))
        check("推理模型的输出额度被抬到下限",
              llm.effective_max_tokens(_rs) == llm.REASONING_FLOOR,
              f"1200 → {llm.effective_max_tokens(_rs)}")
        check("非推理模型不动额度",
              llm.effective_max_tokens({"provider": "qwen", "model": "qwen-plus",
                                        "max_tokens": 1200}) == 1200)
        check("额度不会超过上限",
              llm.effective_max_tokens({"provider": "deepseek", "model": "deepseek-flash",
                                        "max_tokens": 99999}) == llm.MAX_OUTPUT_CEILING)
        check("模型名也能识别推理模型（自定义服务商）",
              llm.is_reasoning({"provider": "custom", "model": "deepseek-reasoner"}))
        check("普通模型名不会被误判",
              not llm.is_reasoning({"provider": "custom", "model": "gpt-4o-mini"}))

        check("能从 /chat/completions 推出 /models 地址",
              llm.models_endpoint("https://api.deepseek.com/v1") ==
              "https://api.deepseek.com/v1/models"
              and llm.models_endpoint("https://x.cn/v1/chat/completions") ==
              "https://x.cn/v1/models")

        # ---- 视觉能力判断 ----
        # deepseek-v4-pro 读不了图，而且是**静默丢弃**（不报错、prompt_tokens 不涨），
        # 所以必须靠判断而不是"发过去试试"。
        check("每个服务商都标了可读图的模型",
              all("vision_models" in v for v in llm.PROVIDERS.values()),
              "、".join(f"{k}:{len(v.get('vision_models') or [])}"
                        for k, v in llm.PROVIDERS.items()))
        check("deepseek-flash 判定为可读图",
              llm.supports_vision({"provider": "deepseek", "model": "deepseek-flash"}))
        check("deepseek-v4-pro 判定为不可读图",
              not llm.supports_vision({"provider": "deepseek", "model": "deepseek-v4-pro"}))
        check("qwen-vl-max 判定为可读图",
              llm.supports_vision({"provider": "qwen", "model": "qwen-vl-max"}))
        check("qwen-plus 判定为不可读图",
              not llm.supports_vision({"provider": "qwen", "model": "qwen-plus"}))
        check("自定义服务商按命名猜视觉能力",
              llm.supports_vision({"provider": "custom", "model": "gpt-4o"})
              and not llm.supports_vision({"provider": "custom", "model": "my-text-model"}))
        check("模型为空时不算可读图",
              not llm.supports_vision({"provider": "deepseek", "model": ""}))

        # ---- 长图切片：整张等比缩会让表格字糊掉，必须竖着切 ----
        from PIL import Image as _Im
        _long = _Im.new("RGB", (1000, 3708))
        _slices = llm.image_slices(_long)
        check("长图会被切成多块", len(_slices) >= 2, f"{len(_slices)} 块")
        check("每块长边不超过上限",
              all(max(im.size) <= llm.VISION_MAX_SIDE for im in _slices),
              str([im.size for im in _slices]))
        check("普通比例的图不切",
              len(llm.image_slices(_Im.new("RGB", (1000, 900)))) == 1)
        _url = llm.encode_image(_Im.new("RGB", (800, 600)))
        check("编码成 data URL", len(_url) == 1 and _url[0].startswith("data:image/jpeg;base64,"))
        check("坏图片不会抛异常，返回空列表",
              llm.image_slices(b"not-an-image") == [])

        # 设置页要能选模型、能拉取、能提示额度
        sv = win.settings_view
        check("设置页模型是可选可填的下拉", sv.cb_model.isEditable())
        check("设置页模型下拉带了预设项", sv.cb_model.count() >= 2,
              f"{sv.cb_model.count()} 项")
        check("设置页有「拉取可用模型」按钮", hasattr(sv, "btn_models"))
        check("设置页会提示实际输出额度", "实际按" in sv.lb_budget.text(),
              sv.lb_budget.text()[:60])
        sv.cb_model.setCurrentText("deepseek-flash")
        check("切到推理模型后额度提示会变成警告", "推理模型" in sv.lb_budget.text(),
              sv.lb_budget.text()[:40])
        check("_collect 能取到下拉里的模型名",
              sv._collect()["model"] == "deepseek-flash")

        # ---- 页面不该横向溢出 ----
        # 某个长 QLabel 忘了 setWordWrap(True) 时，它的最小宽度 = 整句宽度，
        # 会把内容容器撑得比视口还宽；而横向滚动条默认关闭，
        # 于是这一行右侧的控件会**静默消失**（踩过：设置页被撑到 2170px）。
        over = []
        for vkey, view in [("studio", win.studio_view),
                           ("dashboard", win.dashboard_view),
                           ("settings", win.settings_view)]:
            win.stack.setCurrentWidget(view)
            for _ in range(4):
                app.processEvents()
            for p in view.findChildren(M.theme.PageScroll):
                d = p.widget().minimumSizeHint().width() - p.viewport().width()
                if d > 4:
                    over.append(f"{vkey} 溢出 {d}px")
        check("页面内容不会横向溢出（控件不会被挤出屏幕）", not over,
              "、".join(over) or "无")

        # 事件循环能正常跑起来并退出
        QTimer.singleShot(800, app.quit)
        rc = app.exec()
        check("事件循环正常启动与退出", rc == 0, f"退出码 {rc}")

    except Exception:
        traceback.print_exc()
        check("启动过程未抛异常", False, "见上方 traceback")

    print(f"\n=== 通过 {len(fails) == 0 and '全部' or (len(fails))} "
          f"{'项' if fails else ''} ===" if not fails else f"\n=== 失败 {len(fails)} 项 ===")
    for f in fails:
        print(f"  - {f}")
    print()
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
