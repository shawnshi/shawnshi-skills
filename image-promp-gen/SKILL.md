---
name: image-promp-gen
version: 9.0.0
tier: action-allowed
description: 提取一句话需求，生成 Mondo 风格/大师级设计配图提示词。禁止用于生成真实摄影照片或复杂 3D 渲染图。
triggers: ["Mondo风格", "书籍封面", "专辑封面", "海报设计", "读书笔记配图", "公众号封面", "小红书配图", "文章配图"]
---


<strategy-gene>
Keywords: 海报提示词, 书籍封面, 专辑封面, 小红书配图
Summary: 生成大师级视觉提示词，覆盖封面、海报和社媒配图。
Strategy:
1. 提取主题、媒介、比例、目标平台和情绪张力。
2. 选择设计师风格、构图、字体、色彩、符号和摄影/插画语言。
3. 输出可直接用于图像模型的一句话或分层提示词。
AVOID: 禁止堆砌空泛形容词；禁止忽略平台比例和文字排版约束。
</strategy-gene>

# Mondo Style Design Prompt Generator (image-promp-gen)

Generate highly detailed and optimized AI image prompts in Mondo's distinctive alternative aesthetic - known for limited-edition screen-printed posters, book covers, and album art with bold colors, minimalist compositions, and symbolic storytelling.

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (调用 `python3 scripts/generate_mondo.py ...` 获取精密 Prompt)
2. `invoke_subagent` 或 `call_mcp_tool` (联动 `image-studio-architect` 物理出图节点，将提示词送入生成)
3. `write_to_file` (执行强制的 Telemetry 遥测落盘)

**This skill can:**
- Generate detailed Mondo-style prompts for any subject
- Design prompt structures for movie posters, book covers, album art, event posters
- Provide genre-specific and format-specific templates

## Artist-Specific Variations & Aesthetic Guidelines
For comprehensive Mondo aesthetic details, prompt structures, and all 20+ artist styles, refer strictly to [references/mondo-aesthetics.md](references/mondo-aesthetics.md) and [references/artist-styles.md](references/artist-styles.md). All manual instruction details have been left-shifted to the Python script and reference library.

## 🚀 Key Features

### 1. 20+ Artist Styles
Includes legendary artist styles from Art Nouveau to Contemporary Minimalism.
- `saul-bass`, `olly-moss`, `tyler-stout`, `alphonse-mucha`, `milton-glaser`, and more.
- View all styles: `python3 scripts/generate_mondo.py --list-styles`

---

## Direct Prompt Generation

This skill generates prompt strings using the bundled script:

```bash
python3 scripts/generate_mondo.py "subject" "type" [options]
```

**Parameters:**
- `subject`: What to design (e.g., "Akira cyberpunk anime")
- `type`: Design type - "movie", "book", "album", "event"
- `--style`: Artist style (20+ options, see --list-styles)
- `--colors`: Color preferences (e.g., "orange, teal, black")
- `--aspect-ratio`: Aspect ratio (default: 9:16 for mobile/social)

**Examples:**

Basic generation:
```bash
python3 scripts/generate_mondo.py "Blade Runner" movie
```

With specific artist style:
```bash
python3 scripts/generate_mondo.py "cyberpunk noir" movie --style saul-bass
```

List all artist styles:
```bash
python3 scripts/generate_mondo.py --list-styles
```

### Manual Usage

1. Use this skill to generate the Mondo-style prompt.
2. The script will prompt: `Would you like to call 'image-nano-gen' to generate the image with this prompt?`
3. If confirmed, call the `image-nano-gen` skill with the generated prompt.



## <Contracts>
- **Delivery Standard**: 最终交付必须是可直接用于图像生成的高质量提示词，并满足媒介、比例和风格要求。
- **Defaults Handling**: 如果用户没有指定尺寸或平台，默认使用 9:16 海报比例并向用户说明。
- **Conflict Resolution**: 若用户需求（如“要求极简但颜色极多”）与现有风格体系冲突，必须显式说明取舍，禁止混合出模糊的风格。

## <Failure_Taxonomy>
- **Photorealism Leakage**: 使用复杂照片级真实词汇会导致生成失败。必须坚持 screen print aesthetics。
- **Aspect Ratio Neglect**: 忽略移动端 9:16 长宽比偏好。
- **Negative Space Ignorance**: 在极简风格中忽略负空间和双关视觉机会。

## Telemetry (Mandatory)
- 必须使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "image-promp-gen", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`
