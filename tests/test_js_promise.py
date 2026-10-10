"""守住一个会影响架构决策的前提：Qt 的 runJavaScript **不 await Promise**。

为什么值得单独立一个测试：这条结论直接决定了适配脚本能写成什么样。

  · 如果 Qt 会 await → 适配脚本可以写「点标签页 → await sleep(1.2s) → 填内容」
    一条链，代码干净得多。
  · 实际上不会 → `Promise.resolve({ok:true})` 回到 Python 侧是 `{}`（空对象），
    所有等待都必须拆成「返回 retry:true + Python 侧延迟重跑」。

所以发布队列里那套重试机制不是过度设计，是被这条限制逼出来的。
哪天 Qt 改了行为，这个测试会先红，我们就能把两边都简化掉。

用法：
    python tests/test_js_promise.py
"""
import os
import sys

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
    print("\n=== runJavaScript 与 Promise ===\n")

    from PyQt6.QtCore import QTimer, QUrl
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineCore import QWebEnginePage

    app = QApplication(sys.argv)
    page = QWebEnginePage()
    got = {}

    def run(key, code, wait_ms):
        box = {}

        def cb(r):
            box["v"] = r

        page.runJavaScript(code, cb)

        def collect():
            got[key] = box.get("v", "（回调没被调用）")

        QTimer.singleShot(wait_ms, collect)

    def after_load(ok):
        QTimer.singleShot(300, lambda: (
            run("sync", "1+1", 400),
            run("promise_now", "Promise.resolve({ok:true, message:'resolved'})", 400),
            run("promise_later",
                "(function(){return new Promise(function(res){"
                "setTimeout(function(){res({ok:true, message:'later'});},600);});})()",
                1400),
            run("async_fn",
                "(async function(){ await new Promise(function(r){setTimeout(r,300);});"
                " return JSON.stringify({ok:true,message:'async'}); })()",
                1200),
            QTimer.singleShot(1800, app.quit)))

    page.loadFinished.connect(after_load)
    page.setHtml("<html><body><div>hi</div></body></html>", QUrl("https://example.com/"))
    QTimer.singleShot(9000, app.quit)
    app.exec()

    print("  （原始回调值）")
    for k in ("sync", "promise_now", "promise_later", "async_fn"):
        print(f"      {k:16s} -> {got.get(k)!r}")

    check("同步表达式正常返回数值", got.get("sync") == 2, repr(got.get("sync")))
    check("立即 resolve 的 Promise 拿不到内容（只会拿到空对象）",
          got.get("promise_now") in ({}, None),
          repr(got.get("promise_now")))
    check("延迟 resolve 的 Promise 同样拿不到（回调不会等到它）",
          got.get("promise_later") in ({}, None),
          repr(got.get("promise_later")))
    check("async 函数的返回值也拿不到",
          got.get("async_fn") in ({}, None),
          repr(got.get("async_fn")))
    check("结论：等待只能在 Python 侧做（发布队列的 retry 机制是必需的）",
          all(got.get(k) in ({}, None)
              for k in ("promise_now", "promise_later", "async_fn")))

    print()
    if fails:
        print(f"=== 失败 {len(fails)} 项 ===")
        for f in fails:
            print("  -", f)
        print("\n注意：如果上面「Promise 拿不到」的断言开始失败，"
              "说明 Qt 改了行为 —— 那时可以把适配脚本里的 retry 拆解简化掉。")
        sys.exit(1)
    print("=== 通过 全部 ===")


if __name__ == "__main__":
    main()
