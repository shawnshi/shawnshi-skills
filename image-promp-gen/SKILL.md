---
name: image-promp-gen
description: 一句话生成大师级海报、书籍封面、专辑封面和各类设计作品的提示词。基于33+位传奇设计师风格。支持多平台多比例。包含AI提示词优化。触发词："Mondo风格"、"书籍封面设计"、"专辑封面"、"海报设计"、"读书笔记配图"、"公众号封面"、"小红书配图"、"文章配图"。One-sentence generation of master-level poster and cover prompts.
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

**This skill can:**
- Generate detailed Mondo-style prompts for any subject
- Design prompt structures for movie posters, book covers, album art, event posters
- Provide genre-specific and format-specific templates

## Core Mondo Aesthetic

Mondo posters are characterized by:

1. **Artistic Reinterpretation** - Not literal film scenes, but conceptual visual distillations
2. **Screen Print Aesthetics** - Limited color palettes (2-5 colors), flat color blocks, halftone textures
3. **Minimalist Symbolism** - Key props, silhouettes, negative space over character faces
4. **Bold Vintage Typography** - Hand-drawn lettering, condensed sans-serifs, Art Deco influences
5. **Retro Color Palettes** - High saturation, vintage duotones, bold contrasts (orange/teal, red/cream, etc.)

## Prompt Structure

When generating Mondo-style prompts, use this template:

```
[SUBJECT] in Mondo poster style, [COMPOSITION], [COLOR PALETTE],
screen print aesthetic, limited edition poster art, [KEY VISUAL ELEMENTS],
[TEXTURE/FINISH], minimalist design, vintage movie poster, [MOOD/TONE]
```

### Essential Components

**Style Anchors** (always include):
- "Mondo poster style" or "alternative movie poster"
- "screen print aesthetic" or "silkscreen print"
- "limited edition poster art"
- "vintage [decade] movie poster" (60s/70s/80s)

**Composition Techniques** (choose 1-2):
- Centered symmetrical composition
- Silhouette against [color] background
- Negative space storytelling
- Geometric framing (circles, triangles, arches)
- Layered depth with foreground/midground/background

**Color Strategy** (specify clearly):
- Limited palette: "3-color screen print: [color 1], [color 2], [color 3]"
- Duotone: "[warm color] and [cool color] duotone"
- Vintage scheme: "70s palette: burnt orange, mustard yellow, brown"
- High contrast: "bold [color] on [color] background"

**Visual Elements** (symbolic, not literal):
- Key prop or object (weapon, vehicle, iconic item)
- Silhouettes over detailed faces
- Geometric shapes hiding imagery
- Environmental mood (fog, rain, shadows)
- Symbolic animals or nature elements

**Texture & Finish** (adds authenticity):
- "halftone dot texture"
- "risograph printing effect"
- "paper texture grain"
- "slight misalignment between color layers"
- "vintage print imperfections"

## Artist-Specific Variations

For different Mondo artist styles, see [references/artist-styles.md](references/artist-styles.md).

**Quick reference:**
- **Tyler Stout style**: Dense character collages, intricate details, maximal composition
- **Olly Moss style**: Ultra-minimal, clever negative space, 1-2 colors
- **Martin Ansin style**: Art Deco influence, elegant line work, muted vintage tones

## Advanced Negative Space Techniques

Master-level Mondo designs use **figure-ground inversion** - where the negative space (area without ink) forms meaningful shapes.

### Technique 1: Clever Visual Puns (Olly Moss Style)
**Example structure:**
```
[Subject silhouette] in Mondo poster style, vertical 9:16, negative space WITHIN
silhouette reveals [hidden element], Olly Moss figure-ground inversion, 2-color
duotone: [color 1] and [color 2], clever dual imagery, what's missing tells the story
```

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



##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "image-promp-gen", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- **DO NOT** use complex photorealistic terms; stick to screen print aesthetics.
- **ALWAYS** prefer 9:16 aspect ratio for posters and covers unless specified otherwise.
- **NEVER** ignore the negative space opportunities in minimal designs.

## When to Use
- 当用户要求生成海报、封面、配图或设计风格型图像提示词时使用。
- 具体设计师映射、风格控制和比例策略仍以本文件既有说明为准。

## Workflow
- 遵循本文件已有的风格选择、提示词组装和平台适配流程。
- 不跳过长宽比、负空间和媒介风格限制。

## Resources
- 使用本技能引用的设计师风格库、模板、示例提示词和参考文件。
- 所有提示词拼装规则以技能目录中的现有资源为准。

## Failure Modes
- 将本文件中的比例偏好、风格禁令和 `Gotchas` 视为失败模式。
- 若用户需求与现有风格体系冲突，必须显式说明取舍，而不是混合出模糊风格。

## Output Contract
- 最终交付必须是可直接用于图像生成的高质量提示词，并满足媒介、比例和风格要求。
- 如果用户没有给尺寸或平台，输出必须遵循本文件的默认策略并明确说明。

## Telemetry
- 按本文件上方定义的 telemetry 规则记录元数据。
