# gzh-to-xhs —— 安装说明

把一个公众号链接（或选题）自动重构成小红书图文笔记：文案 + 3:4 竖版配图 + 独立归档。

本包**声明为 pipeline 形态**（SKILL.md front matter 里 `kind: pipeline` +
`pipeline: gzh_to_xhs_magazine`）—— 它描述的是要动手的流程（抓网页、下载配图、
PIL 出图、写文件），只靠一次文本生成干不了这些活，必须由流水线运行器执行。

## 安装到 DragonFlow（30 秒）

1. 把 `gzh-to-xhs` 整个文件夹打成 zip（或直接用 `gzh-to-xhs-pipeline.zip`）
2. DragonFlow →「设置 → 内容模板 Skill → 上传 Skill ▾ → 导入压缩包…」
3. 导入后它会出现在**内容工坊**的能力列表里，形态显示为「流水线」：
   贴公众号链接 → 抓原文 → 读配图 → 生成文案 → 出 8 张暖橙奶油杂志风 3:4 配图

前置条件（缺一个都会在「自检」里标红）：

- DragonFlow 的 `src/pipelines/` 下有 `gzh_to_xhs_magazine.py` 运行器
  （本仓库已自带；把包发给别人时，对方也需要这份代码）
- Python 装了 `Pillow` 和 `requests`
- 中文字体：Windows `C:\Windows\Fonts\msyhbd.ttc`（一般都有）

## 安装到 WorkBuddy（Agent 环境）

把 `gzh-to-xhs` 文件夹放进 `~/.workbuddy/skills/`，重启对话即可。
Agent 有工具调用能力，会按 SKILL.md 的流程自己抓网页、跑脚本、出图。

## 目录结构

```
gzh-to-xhs/
├── SKILL.md              # 主指令 + 形态声明（kind/pipeline）
├── references/design.md  # 出图设计规范（暖橙奶油杂志风：色板/版式/间距算法）
└── assets/template.py    # 同风格出图脚本模板（Agent 环境直接改造用）
```

## 安全提示

Skill 本质是「让 AI 照着执行的指令 + 脚本」，收到别人的 skill 请先花一分钟扫一眼
`SKILL.md` 和 `assets/` 里的脚本，确认没有你不希望执行的操作，再放进技能目录。
