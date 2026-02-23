---
title: Smart Doc LaTeX - 智能排版印刷机
date: 2026-02-21
status: Active
author: System
---

# 智能排版印刷机 (smart-doc-latex)

将普通文本文档一键转换为工业级出版质感的 PDF 与 LaTeX 源码的专业排版引擎。

## 核心能力

- **多格式输入**：支持 `.md`、`.txt` 和 `.docx` 三种主流格式
- **五大美学模板**：学术论文 (Academic)、技术报告 (Tech Report)、通用书籍 (Book)、O'Reilly 风格技术书 (Tech Book)、个人简历 (CV)
- **智能样式探测**：分析文档内容自动匹配最佳模板
- **全栈编译**：底层调用 Pandoc 转换 + XeLaTeX 编译，端到端输出 PDF

## 环境依赖

| 依赖 | 用途 | 安装检查 |
|:---|:---|:---|
| **Pandoc** | 文档格式转换 | `pandoc --version` |
| **TeX Live / MiKTeX** | LaTeX 编译 (需含 XeLaTeX) | `xelatex --version` |
| **Python 3.6+** | 运行引擎脚本 | `python --version` |

## 快速开始

```bash
# 自动检测样式并编译
python scripts/smart_engine.py --input my_document.md

# 指定样式和作者
python scripts/smart_engine.py --input thesis.md --style academic --title "我的论文" --author "张三"

# 指定输出目录
python scripts/smart_engine.py --input resume.md --style cv --output ./output/
```

## 项目结构

```
smart-doc-latex/
├── SKILL.md              # 技能指令文档 (Agent 入口)
├── README.md             # 本文件
├── _DIR_META.md          # 目录元数据
├── agents/
│   └── gemini.yaml       # Gemini 界面配置
├── scripts/
│   ├── smart_engine.py         # 🔑 核心引擎 (统一入口)
│   └── process_idioms.py       # 成语字典排版 (特殊用途)
├── templates/
│   ├── academic.tex      # 学术论文模板
│   ├── book.tex          # 通用书籍模板
│   ├── cv.tex            # 简历模板
│   ├── tech_book.tex     # O'Reilly 技术书模板
│   └── tech_report.tex   # 技术报告模板
└── references/
    └── styles.md         # 样式参考与检测逻辑说明
```

## 使用场景

- "排版我的论文" → `--style academic`
- "将其制作成高档简历" → `--style cv`
- "作为技术书籍 PDF 发行" → `--style tech_book`
- "生成阅读报告" → `--style tech_report`
- "转为 PDF" → `auto` 自动检测
