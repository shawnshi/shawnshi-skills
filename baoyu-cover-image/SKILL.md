---
name: baoyu-cover-image
description: 为文章生成四维定制化（类型、风格、文字、情绪）封面图。支持 20 种手绘与商业风格。使用场景：文章配图、社交媒体封面、书籍封面。
---

# Cover Image Generator (The Visual Alchemist)

通过参数化控制生成出版级文章封面。

## Usage

```bash
# 全自动模式
/baoyu-cover-image path/to/article.md

# 快捷模式 (跳过确认)
/baoyu-cover-image article.md --quick

# 指定维度
/baoyu-cover-image article.md --type conceptual --style blueprint
```

## Options

| Option | Description | Values |
|--------|-------------|--------|
| `--type` | 视觉构成 | hero, conceptual, typography, metaphor, scene, minimal |
| `--style` | 艺术审美 | 详见 `references/gallery.md` |
| `--text` | 文字密度 | none, title-only, title-subtitle, text-rich |
| `--mood` | 情绪强度 | subtle, balanced, bold |
| `--aspect` | 比例 | 16:9, 2.35:1, 4:3, 3:2, 1:1, 3:4 |

## Workflow SOP

### 1. Initiation & Auth (Step 0)
*   检查 `EXTEND.md`。若无，标记为 Global Tool 模式。
*   检查 `.env`。若包含 `GOOGLE_API_KEY`，启用 Private Auth 模式。

### 2. Analysis & Confirmation
*   分析文章语义，根据 `references/logic.md` 推荐参数。
*   **必须停止并确认** (除非使用 `--quick`)。

### 3. Prompt Construction
*   组合四个维度的描述语。
*   保持标题长度在 8 字以内。

### 4. Generation & Backup
*   **Private Mode**: 调用 `python scripts/executor.py`。
*   **Global Mode**: 调用 `generate_image`。
*   **Rule**: 再次生成前必须备份旧图为 `cover-backup-{timestamp}.png`。

## Reference Assets
*   **样式库**: `references/gallery.md`
*   **自动逻辑**: `references/logic.md`
*   **维度详解**: `references/dimensions/`

!!! Maintenance Protocol: 逻辑变更请同步更新脚本头与 `_DIR_META.md`。
