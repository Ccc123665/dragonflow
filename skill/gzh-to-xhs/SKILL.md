---
name: gzh-to-xhs
description: 把公众号文章链接（或选题）重构为小红书专属图文笔记——含 3:4 竖版高清配图、可直接发布的文案、按选题单独归档。触发词：公众号转小红书、gzh转小红书、链接转小红书图文、小红书图文、多平台分发、考公图文笔记。
kind: pipeline
pipeline: gzh_to_xhs_magazine
platform: 小红书
fields: title,body,topics,cover,image_hint
agent_created: true
---

# 公众号链接 → 小红书图文笔记

把一个公众号链接（或一个选题）二次创作成小红书可直接发布的图文笔记：**文案 + 3:4 配图 + 独立归档**。

> **形态说明**：本 skill 描述的是「要动手」的流程（抓网页、下载配图、PIL 出图、写文件）。
> 在 DragonFlow 里它以 **pipeline 形态**运行，执行器是 `src/pipelines/gzh_to_xhs_magazine.py`
> （front matter 的 `kind` / `pipeline` 字段即声明了这个绑定，导入时自动登记）。
> 在 WorkBuddy 这类带工具调用的 Agent 环境里，则由 Agent 按下面的流程逐步执行。

## 何时用

用户给出公众号/网页链接，或给出一个选题，要求产出小红书图文笔记。典型场景是考公考编、教培、本地生活这类"同一选题多平台分发"的账号运营。

## 硬性规则（不可违反）

1. **不编造**：考情数据、招录规则、报考条件必须来自原文，不改数字、不加码、不"大概"。
2. **不出现**任何第三方机构名称、课程宣传、引流话术、私域引导。
3. **不出现**任何网址、链接、二维码、外链地址（包括"阅读原文"这类指引）。
4. **不搬运**：不能大段复制原文，要重写语言、重排结构、改成口语化。
5. **必归档**：每期单独建文件夹，命名贴合选题，禁止多期混放、禁止散落保存。

## 执行流程

### 1. 抓原文（**必须两步，缺一不可**）

**第一步：WebFetch 抓正文**
prompt 明确要求"完整提取标题、正文全文、所有小标题、所有数据、政策信息，逐字保留不要概括"。

**第二步：抓 HTML、下载全部配图、逐张看图 —— 这一步绝对不能省**

公众号文章的核心数据经常**只存在于图片里**（题量统计表、竞争比排行、岗位表）。WebFetch 会把 `<img>` 全部丢掉，只拿正文会漏掉整批数据。实战踩过：一篇文章正文只写了"职业素养每年2-6题"，但配图里有一张 2020-2026 逐年逐模块的完整题量表——这才是最有价值的部分。

```python
import re, os, urllib.request, ssl
URL = "<文章链接>"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
       "Referer": "https://mp.weixin.qq.com/"}
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
h = urllib.request.urlopen(urllib.request.Request(URL, headers=HDR), timeout=60, context=ctx) \
        .read().decode("utf-8", "ignore")
imgs = list(dict.fromkeys(re.findall(r'data-src="(https://mmbiz\.qpic\.cn/[^"]+)"', h)))
os.makedirs("src", exist_ok=True)
for i, u in enumerate(imgs, 1):
    d = urllib.request.urlopen(urllib.request.Request(u, headers=HDR), timeout=60, context=ctx).read()
    open("src/%02d.%s" % (i, "png" if "png" in u else "jpg"), "wb").write(d)
```

要点：
- 必须带 `Referer: https://mp.weixin.qq.com/`，否则图片 403
- 走 `urllib` 而不是 `curl`，curl 抓公众号容易超时；耗时超过 2 分钟就 `run_in_background`
- 同一张图在文中会重复出现，用 `dict.fromkeys` 去重；**先按文件大小分组**，同尺寸同字节数的就是同一张，只需看一次
- 表格图必须**逐张 Read 原图**看清数字，别靠缩略图猜。长图先用 PIL 上下切两半再看
- 图片里的**水印、机构名、课程广告、二维码一律不要复现**，只取数据

**判断哪些图要看**：宽 600px 以上、字节数 >20KB 的通常是数据表或信息图；几十像素的（logo、分割线）、纯色几何块、表情包可以直接跳过。

### 2. 建归档目录

```
<工作区>/<选题名>/
├── 小红书文案.md          # 标题主推+备选、正文、标签、图-文对应表、发布提示
├── 正文_纯文本可复制.txt   # 只放正文+标签，方便直接粘贴
├── 图片/                   # 01_封面.png ...
└── make_images.py          # 出图脚本，留档方便改
```

### 3. 拆内容 → 排图序

标准 8 张结构（可按内容量增减，小红书上限 18 张）：

| 序号 | 作用 |
| --- | --- |
| 01 | 封面：大标题 + 3 个核心数字 |
| 02 | 关键变化 / 背景 |
| 03 | 全局总览（题量、占比、分布） |
| 04~07 | 逐模块展开，一块一张 |
| 08 | 划重点 + 收尾 |

拆图原则：**一屏一个信息块**。信息密度超过 7 行就拆成两张。封面必须放大字号，缩略图状态下也要能读。

### 4. 出图（PIL）

设计规范见 `references/design.md`，可直接改造的脚本模板见 `assets/template.py`。

关键点：
- 画布 **1080×1440**（正好 3:4）
- 统一色板：**暖橙奶油杂志风** —— 奶油底 `#FAF3E9` + 深棕墨 `#2A2118` + 暖橙强调 `#E8622B` + 焦糖金 `#C98A2E`
- 封面走**杂志刊头版式**：刊头条（胶囊标签 + 刊号 + 细分割线）→ 引题 → 124px 大标题（一个关键词染橙）→ 橙条 → 副标题 → **整块深棕墨数据卡**（竖向细线三等分，不用三张小卡）
- 严禁渐变、高斯模糊光晕、网点、斜切贴纸装饰；装饰只允许直线、细圆环、纯色块
- 暖橙是点睛色，一张图最多 3 处；投影必须是暖棕 `(72,54,38)`，冷灰投影会毁掉奶油暖调
- 中文字体 `C:\Windows\Fonts\msyhbd.ttc`（粗）/ `msyh.ttc`（常规），`index=0`
- **不要在 RGBA 画布上用带 alpha 的 fill 画图形**——会直接覆盖像素而不是混合，`convert("RGB")` 后变纯白，白字就看不见了。半透明面板必须画在独立 RGBA 图层再 `alpha_composite()`
- 图片里不要放 emoji（PIL 渲染不出彩色 emoji，会出豆腐块），用几何形状和色块代替
- 每张图留 ~100-150px 底部呼吸空间，各张留白量保持一致才显得专业

### 5. 写文案

- **标题**：≤20 字，本地化 + 痛点，主推 1 条 + 备选 3 条
- **正文**：短段落，emoji 分区（📌📊🧩⚖️📚🎯🛡✅ 这类），口语化，干货前置
- **结尾**：8-10 个垂直标签，不堆无关的
- **正文控制在 1000 字以内**（小红书限制）

### 6. 校验

```bash
# 尺寸比例必须是 0.75
python -c "from PIL import Image;import glob,os
for p in sorted(glob.glob('图片/*.png')):
    im=Image.open(p);print(os.path.basename(p),im.size,im.size[0]/im.size[1])"
```

逐张 Read 看图，重点检查：

1. **文字有没有叠在一起** —— 尤其"小标签 + 大数字"的卡片。`anchor="lm"` 居中的是字体盒子不是字形，凭感觉给 y 值一定会压字。间距算法见 `references/design.md` 的"文本块间距"。
2. **最后一行有没有贴住卡片底边** —— 净间距小于 20px 就是没留够。
3. **表格末行有没有被裁掉** —— 溢出不会报错，只会静默丢内容。
4. **有没有白字白底** —— RGBA 画布上用带 alpha 的 fill 会覆盖底色。
5. **有没有 emoji 豆腐块** —— 图片里不要放 emoji。
6. **底部留白是否一致** —— 各张差异太大显得不专业。

每张图的底部留白目标 150-250px，控制在合理区间内。

## 环境备忘（作者本机 Windows 环境，换机器请按需调整）
> 下面这一节是作者机器的踩坑记录（绝对路径、DLL 修复等），**换机器时请按实际情况修改或整节删掉**，否则会误导。

- Python：`C:\Users\Surface\.workbuddy\binaries\python\versions\3.13.12\python.exe`
- **venv 别用**：`binaries\python\envs\default` 里 pip 会报错。直接用托管 python 本体 `-m pip install`。
- **pip 默认源极慢**（20 分钟装不上 onnxruntime），一律加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
- **本机模型读不了图片**（Read 图片返回"不支持"），看配图改走 OCR：`pip install rapidocr-onnxruntime`，OCR 结果**直接在 python 里写 UTF-8 文件**，不要走 stdout（控制台会乱码）。水印盖住的数字列放大 4x+提对比度也救不回来，识别不出就别编，展示"已确认"的数据即可。
- **onnxruntime DLL 修复**（本机 System32 缺 VC++ 运行库）：把 `D:\software\WorkBuddy\resources\app.asar.unpacked\cli\vendor\sandbox\5.5.5\` 下的 `msvcp140.dll`、`vcruntime140.dll`、`vcruntime140_1.dll` 复制到 `site-packages\onnxruntime\capi\`，再从 `D:\software\WeMeet\3.29.3.498\msvcp140_1.dll`（注意 WPS 那份是 32 位，不能用）复制到同一目录，`import onnxruntime` 即通过。用 PE 头字节（pe+4 处 0x8664=x64）验证位数。
- **PowerShell 工具 stdout 经常为空**：命令输出一律先写入文件（`Set-Content -Encoding UTF8`）再用 Read 看；长命令用 `run_in_background`。
- 本机没装 playwright，出图走 PIL。
- 若需要 HTML 渲染出图，用 agent-browser skill（Windows x64 支持）。

## 出图后自检（模型看不了图时）

用反向 OCR 校验生成图：对 `图片/*.png` 跑 RapidOCR，检查每张图的关键文字（尤其表格末行、合计行、竞争比列）是否都被识别到。再配合像素检查（裁剪区域 `min(getdata())`，<100 说明有字、255 说明空白）。这能抓住两类静默 bug：表格末行溢出被裁、表格行元数据漏传导致整列没画。

## 收尾

- 用 present_files 把 `小红书文案.md` + `正文_纯文本可复制.txt` + 全部图片一次性展示出来，图片放前面
- 往工作区 `.workbuddy-ai/memory/YYYY-MM-DD.md` 追加一条：源链接、产出目录、图片张数
