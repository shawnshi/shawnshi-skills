---
name: baoyu-slide-deck
description: Transform Markdown content into professional slide decks (PPTX/PDF). Features "Smart Resume" and "Editable Text".
---

# Slide Deck Generator (Presentation Architect)

通过语义分析与多模态渲染，将文本转化为出版级演示文稿。

## Usage

```bash
# 核心指令
/baoyu-slide-deck path/to/content.md [OPTIONS]

# 示例：生成中文商务风 PPT
/baoyu-slide-deck report.md --style elegant --lang zh --editable-text
```

## Core Options

| Option | Description |
|--------|-------------|
| `--style` | 风格 (e.g., elegant, blueprint, sketch-notes). |
| `--model` | 渲染模型 (gemini, dalle3). 默认为 `gemini`。 |
| `--editable-text` | **[推荐]** 生成无字背景图，使用 PPT 原生文本框。 |
| `--resume` | **[推荐]** 断点续传。仅生成 `status.json` 中失败或未完成的页。 |

详细参数见 `references/cli-reference.md`。

## Workflow SOP

### 1. Analysis & Outline
*   Agent 分析输入文档结构。
*   生成 `outline.md`。**必须等待用户确认**（除非使用 `--quick`）。

### 2. Prompt Generation
*   调用 `scripts/generate-prompts.py` 将大纲转化为视觉提示词。

### 3. Image Rendering (Smart Resume)
*   调用 `scripts/generate-images.py`。
*   **Protocol**: 脚本会自动跳过已存在的图片。若网络中断，重新运行命令即可自动续传。

### 4. Assembly
*   调用 `scripts/build-deck.py`。
*   若启用 `--editable-text`，脚本会将文本作为 Shape 注入 PPTX，而非烧录进图片。

## Troubleshooting
*   **文字乱码**: 检查 `--lang` 是否正确设置。
*   **生成中断**: 再次运行命令并加上 `--resume`。
