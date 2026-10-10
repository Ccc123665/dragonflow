"""自定义平台链路验证：新增 → 出现在平台列表 → 能挂账号 → 能改 → 能删。

跑法：
    python tests/test_custom_platform.py

数据目录被指到临时目录（见下），**不碰用户的真实 platforms_user.json / accounts.json**。

早先的做法是「备份 → 跑 → 还原」，但还原用 shutil.move，Windows 下会先 unlink 目标；
在有删除守卫的环境里 move 会被拦，拦了就留下「知乎测试号」孤儿账号污染真实库。
改成隔离数据目录后，这个失败模式从根上不存在了。
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import time

# 数据目录隔离：config 在 import 时就会算 DATA_DIR 并 makedirs，
# 所以必须赶在 import config 之前改 APPDATA（Windows 下 config 读的就是它）。
_TMP_DATA = tempfile.mkdtemp(prefix="df_platform_test_")
os.environ["APPDATA"] = _TMP_DATA
# 退出时不删自己那份（见 test_ui_smoke.py 的说明：会撞上 Chromium 收尾，
# 退出码变 139）。改成启动时清上一轮留下的。
for _old in glob.glob(os.path.join(tempfile.gettempdir(), "df_platform_test_*")):
    if _old != _TMP_DATA and time.time() - os.path.getmtime(_old) > 3600:
        shutil.rmtree(_old, ignore_errors=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import config  # noqa: E402
import platforms as PF  # noqa: E402
import store  # noqa: E402

PASS, FAIL = "  [OK]  ", "  [FAIL]"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"{PASS if cond else FAIL} {name}" + (f"  → {detail}" if detail else ""),
          flush=True)


def main():
    print("\n=== 自定义平台链路验证 ===\n")
    print(f"（数据目录：{config.DATA_DIR}）\n")
    try:
        base = len(PF.all_platforms())
        check("内置平台已加载", base >= 5, f"{base} 个")

        item = PF.add_custom(
            name="知乎", short="知", color="#2C6BE8",
            publish_url="https://zhuanlan.zhihu.com/write",
            login_url="https://www.zhihu.com/signin",
            home_url="https://www.zhihu.com/creator")
        check("新增自定义平台", bool(item.get("key")), f"key={item['key']}")
        check("key 带自定义前缀", PF.is_custom(item["key"]))
        check("平台总数 +1", len(PF.all_platforms()) == base + 1)
        check("能在列表里查到", PF.name_of(item["key"]) == "知乎")
        check("能取到发布页", PF.get(item["key"])["publish_url"].endswith("/write"))
        check("自定义平台无适配脚本", PF.has_adapter(item["key"]) is False)
        check("内置平台有适配脚本", PF.has_adapter("xhs") is True)

        # 重名要拦住
        try:
            PF.add_custom(name="知乎", publish_url="https://x.com")
            check("重名被拦截", False)
        except ValueError:
            check("重名被拦截", True)

        # 一个网址都不填也要拦住
        try:
            PF.add_custom(name="空网址平台")
            check("空网址被拦截", False)
        except ValueError:
            check("空网址被拦截", True)

        # 落盘了吗
        with open(config.PLATFORMS_USER_FILE, "r", encoding="utf-8") as f:
            disk = json.load(f)
        check("已写入用户目录", any(p["key"] == item["key"]
                                    for p in disk.get("platforms", [])))

        # 重新加载后还在（模拟重启）
        PF.reload()
        check("重启后仍在（reload）", PF.name_of(item["key"]) == "知乎")

        # 挂账号
        db = store.load_accounts()
        n0 = len(store.list_accounts(db))
        acc = store.add_account(db, item["key"], "知乎测试号",
                                group="测试分组", persona="测试人设")
        check("自定义平台能挂账号", acc["platform"] == item["key"])
        check("账号数量 +1", len(store.list_accounts(db)) == n0 + 1)
        store.delete_account(db, acc["id"])
        check("测试账号已清理",
              len(store.list_accounts(store.load_accounts())) == n0)

        # 改
        PF.update_custom(item["key"], {"name": "知乎专栏", "color": "#7B5BD6"})
        PF.reload()
        check("改名生效", PF.name_of(item["key"]) == "知乎专栏")
        check("改色生效", PF.color_of(item["key"]) == "#7B5BD6")

        # 内置平台不能改
        try:
            PF.update_custom("xhs", {"name": "hacked"})
            check("内置平台拒绝修改", False)
        except ValueError:
            check("内置平台拒绝修改", True)

        # 删
        check("删除自定义平台", PF.delete_custom(item["key"]) is True)
        check("删除后数量还原", len(PF.all_platforms()) == base)
        check("内置平台删不掉", PF.delete_custom("xhs") is False)
    finally:
        # 数据目录是临时目录，不需要还原；这里只把内存里的平台表刷回初始状态
        PF.reload()

    bad = [n for n, ok in results if not ok]
    print(f"\n=== 通过 {len(results) - len(bad)} / {len(results)} ===")
    if bad:
        for n in bad:
            print(f"  - {n}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
