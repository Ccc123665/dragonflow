"""S2 适配器验证：在本地模拟发布页上跑真实适配脚本。

验证目标（这是「一键填充」方案成立的前提）：
  1. 适配脚本能被注入并在页面上执行
  2. 标题能写进 React 受控输入，且触发 input/change 事件
  3. 正文能写进 contenteditable 富文本编辑器
  4. 填充后平台的完整性校验能通过（发布按钮解锁）
  5. submit() 能点到发布按钮

用法：
    python tests/test_adapters.py
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu --disable-software-rasterizer --no-sandbox"
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

# WebEngine 必须在 QApplication 之前导入
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PyQt6.QtCore import QEventLoop, QTimer, QUrl  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import publisher as PUB  # noqa: E402

PASS, FAIL = "  [OK]  ", "  [FAIL]"
results = []


def check(name: str, cond: bool, detail: str = ""):
    results.append((name, bool(cond)))
    print(f"{PASS if cond else FAIL} {name}" + (f"  → {detail}" if detail else ""), flush=True)


def js(page, code, timeout=18000):
    """同步执行 JS 并取回结果。

    ⚠ 超时给足：正常路径在回调里 loop.quit() 提前返回，**给大了不花时间**；
    给小了才要命 —— 机器一忙（比如刚连跑完几套测试）Chromium 冷启动 +
    GLES3 降级就要更久，报出一串莫名其妙失败，单独再跑又全绿。
    """
    loop = QEventLoop()
    box = {"done": False, "val": None}

    def cb(v):
        box["val"] = v
        box["done"] = True
        loop.quit()

    page.runJavaScript(code, cb)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    return box["val"]


def wait_until(fn, timeout_ms=18000, interval_ms=150):
    """轮询等待条件成立。

    ⚠ 异步渲染的判定**不要用固定 sleep** —— React 重渲染的时机不定，
    固定等 600ms 会让测试偶发失败（时快时慢，看起来像"代码坏了"）。
    """
    waited = 0
    while waited < timeout_ms:
        try:
            if fn():
                return True
        except Exception:
            pass
        loop = QEventLoop()
        QTimer.singleShot(interval_ms, loop.quit)
        loop.exec()
        waited += interval_ms
    try:
        return bool(fn())
    except Exception:
        return False


def page_state(page):
    st = js(page, "JSON.stringify(window.__getState())")
    try:
        return json.loads(st) if st else {}
    except Exception:
        return {}


def main():
    app = QApplication(sys.argv)

    prof = QWebEngineProfile("df_test", None)
    prof.setPersistentStoragePath(os.path.join(ROOT, ".workbuddy-ai", "tmp", "df_test_profile"))
    page = QWebEnginePage(prof, None)
    view = QWebEngineView()
    view.setPage(page)
    view.resize(900, 700)

    loaded = {"ok": False}
    page.loadFinished.connect(lambda ok: (loaded.update(ok=ok), None))
    page.load(QUrl.fromLocalFile(os.path.join(HERE, "mock_publish.html")))

    loop = QEventLoop()
    page.loadFinished.connect(lambda ok: loop.quit())
    QTimer.singleShot(30000, loop.quit)
    loop.exec()

    print("\n=== S2 适配器注入验证 ===\n")
    check("模拟发布页加载成功", loaded["ok"])

    # ---- 注入适配脚本（走真实的生产代码路径） ----
    full = PUB.adapter_js("xhs")
    check("适配脚本拼装成功", bool(full) and len(full) > 1000, f"{len(full)} 字符")

    js(page, full)
    has = js(page, "typeof window.DragonFlow === 'object' && !!window.DragonFlow.fill")
    check("DragonFlow 对象已挂载到页面", has is True)

    ready = js(page, "window.DragonFlow.ready()")
    check("ready() 判定页面可填充", ready is True, f"返回 {ready!r}")

    # ---- 填充 ----
    payload = {
        "title": "省考行测提速的三个关键动作",
        "body": "先说结论：行测提分的关键不在刷题量，而在做题顺序。\n\n"
                "第一，先做常识和言语，进入状态。\n第二，数量关系放到最后。",
        "topics": ["省考", "行测"],
    }
    r = js(page, f"JSON.stringify(window.DragonFlow.fill({json.dumps(payload, ensure_ascii=False)}))")
    try:
        res = json.loads(r) if r else {}
    except Exception:
        res = {}
    check("fill() 返回 ok=true", res.get("ok") is True, str(res.get("message", "")))
    check("fill() 报告已填字段含 body", "body" in (res.get("filled") or []),
          f"filled={res.get('filled')}")

    st = js(page, "JSON.stringify(window.__getState())")
    try:
        state = json.loads(st) if st else {}
    except Exception:
        state = {}

    check("标题写入成功（React 受控输入）",
          state.get("title") == "省考行测提速的三个关键动作",
          f"实际值 = {state.get('title')!r}")
    check("标题真正落到 DOM 原生 value 上",
          state.get("titleDomNative") == "省考行测提速的三个关键动作")
    check("React 会因此触发 onChange（tracker ≠ DOM 值）",
          state.get("reactWouldFireOnChange") is True,
          f"tracker={state.get('reactTracker')!r}")
    check("标题写入触发了 input/change 事件",
          state.get("titleInputFired") is True and state.get("titleChangeFired") is True,
          f"events={state.get('events')}")
    check("正文写入 contenteditable 成功",
          "行测提分的关键" in (state.get("body") or ""),
          f"正文长度 {len(state.get('body') or '')}")
    check("话题标签写入正文",
          "#省考" in (state.get("body") or "") and "#行测" in (state.get("body") or ""))

    # 平台的完整性校验通常由定时器/异步渲染触发 —— 轮询等它解锁，别固定 sleep
    unlocked = wait_until(
        lambda: page_state(page).get("submitDisabled") is False)
    state = page_state(page)
    check("填充后平台完整性校验通过（发布按钮解锁）", unlocked,
          f"submitDisabled={state.get('submitDisabled')!r}")

    # ---- 提交 ----
    r2 = js(page, "JSON.stringify(window.DragonFlow.submit())")
    try:
        res2 = json.loads(r2) if r2 else {}
    except Exception:
        res2 = {}
    check("submit() 返回 ok=true", res2.get("ok") is True, str(res2.get("message", "")))
    st2 = js(page, "JSON.stringify(window.__getState())")
    try:
        state2 = json.loads(st2) if st2 else {}
    except Exception:
        state2 = {}
    check("发布按钮被真实点击", state2.get("submitted") is True)

    # ---- 未登录分支 ----
    js(page, "document.body.insertAdjacentHTML('afterbegin',"
             "'<div class=\"login-container\">请扫码登录</div>')")
    r3 = js(page, "JSON.stringify(window.DragonFlow.ready ? "
                  "window.DragonFlow.fill({title:'x',body:'y'}) : {})")
    try:
        res3 = json.loads(r3) if r3 else {}
    except Exception:
        res3 = {}
    check("未登录时 fill() 正确拒绝", res3.get("ok") is False, str(res3.get("message", "")))

    # ---- 全部适配器：语法与挂载检查 ----
    print("\n--- 全部平台适配脚本挂载检查 ---", flush=True)
    import platforms as PF
    for p in PF.all_platforms():
        key = p["key"]
        if not PUB.has_adapter(key):
            check(f"{p['name']}：适配脚本存在", False, "文件缺失")
            continue
        code = PUB.adapter_js(key)
        # 清掉上一轮的全局对象，避免相互污染
        js(page, "try{delete window.DragonFlow}catch(e){}; window.DragonFlow=undefined;")
        js(page, code)
        mounted = js(page, "typeof window.DragonFlow === 'object' "
                           "&& typeof window.DragonFlow.name === 'string' "
                           "&& typeof window.DragonFlow.fill === 'function' "
                           "&& typeof window.DragonFlow.submit === 'function'")
        name = js(page, "window.DragonFlow && window.DragonFlow.name")
        check(f"{p['name']}：脚本挂载正常", mounted is True, f"name={name!r}")
        # fill 不得抛异常（选择器不匹配时应优雅返回 ok=false）
        threw = js(page, "(function(){try{var r=window.DragonFlow.fill("
                         "{title:'t',body:'b',topics:['x']});"
                         "return (r&&typeof r.ok==='boolean')?'ok':'bad-return';}"
                         "catch(e){return 'THREW: '+e.message}})()")
        check(f"{p['name']}：fill() 不抛异常", threw == "ok", str(threw))

    ok_n = sum(1 for _, c in results if c)
    print(f"\n=== 通过 {ok_n} / {len(results)} ===\n")
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
