---
name: image-promp-gen
version: 8.1.0
description: '一句话生成大师级海报、书籍封面、专辑封面和各类设计作品的提示词。基于33+位传奇设计师风格。支持多平台多比例。包含AI提示词优化。触发词："Mondo风格"、"书籍封面设计"、"专辑封面"、"海报设计"、"读书笔记配图"、"公众号封面"、"小红书配图"、"文章配图"。'
triggers: ["海报设计", "书籍封面", "专辑配图", "Mondo风格", "生成提示词"]
---

<strategy-gene>
Keywords: 海报提示词, 书籍封面, 专辑封面, Mondo, 丝网印刷
Summary: 提取用户模糊意图，通过脚本生成极具视觉张力的 Mondo 风格（丝网印刷、复古、负空间）AI 绘图提示词。
Strategy:
1. 提取意图：捕获主题、媒介、比例、目标平台和情绪张力。
2. 风格锻造：调用本地 Python 引擎生成包含艺术家风格、构图、色彩、符号的完整 Prompt。
3. 协同生成：询问是否联动 `nanobanana-image-gen` 技能完成端到端物理出图。
AVOID: 禁止使用照相写实主义词汇（photorealistic）；禁止漏掉长宽比与色彩限制。
</strategy-gene>

# Mondo Style Prompt Generator (视觉提示词炼金炉 V8.1 Native)

> **Vision**: 摒弃烂俗的 3D 渲染与写实风。我们以 Mondo 的另类美学为准则——丝网印刷、有限色彩、负空间把玩与符号隐喻。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Context & Strategy (意图提取) [Mode: PLANNING]
1. 明确用户的设计主体 (Subject) 与类型 (Type: movie/book/album/event)。
2. 确定艺术家风格。支持的传奇风格涵盖 Saul Bass (剪影/爵士风), Olly Moss (极简/负空间双重意境), Tyler Stout (高密度人物拼贴) 等。

### Phase 2: Engine Execution (脚本唤起) [Mode: EXECUTION]
1. 必须使用 `run_command` 调用底层脚本合成复杂提示词。
2. 强制挂载中文字符集安全锁与绝对物理路径：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\image-promp-gen\scripts\generate_mondo.py" "您的主题" "类型" --style [艺术家风格] --colors "期望色彩" --aspect-ratio "9:16"`
   *(注：查看所有支持风格可执行：`python "C:\Users\shich\.gemini\config\skills\image-promp-gen\scripts\generate_mondo.py" --list-styles`)*

### Phase 3: Deliver & Handoff (交付与联动) [Mode: EXECUTION]
1. 向用户输出生成的 Mondo 风格大师级提示词。
2. 主动询问用户：“是否需要我立即调用 `image-nano-gen` 技能，使用该提示词为您物理出图？”
3. 使用 `write_to_file` 记录遥测日志至绝对物理地址：
   `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 2. <Contracts> (输出与交付契约)
- **丝网美学契约 (Screen Print Aesthetic)**：所有输出的提示词必须强制包含 `Mondo poster style`, `screen print aesthetic` 或 `limited edition poster art` 等核心锚点。强制要求定义 `limited palette` (例如 2-5 色的双色调或复古高饱和色调)。
- **比例与排版契约 (Ratio & Typography)**：如果没有特殊要求，默认输出适用移动端的 `9:16` 比例。如果是书籍/海报，必须在提示词中囊括对复古字体 (vintage typography / hand-drawn lettering) 的布局要求。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **沙盒宏塌陷与引擎幻觉 (Pathing & Env Deadlock)**：严禁使用 `python3` 等 Unix 习惯指令，严禁在路径中使用 `{root}` 或相对路径 (`scripts/...`)。脚本执行必须且只能挂载绝对物理地址和 UTF-8 安全锁，否则将因找不到文件或解码失败导致任务崩溃。
- **写实主义污染 (Photorealism Pollution)**：如果系统侦测到你在给脚本传参或生成的提示词中使用了 `photorealistic, 8k resolution, Unreal Engine, hyper-detailed photograph` 等 3D/写实类词汇，这将被视为严重破坏 Mondo 丝网美学，直接判定任务失败并打回重构。
- **符号缺位 (Symbolism Missing)**：Mondo 的灵魂在于负空间与符号（例如：在人物轮廓的剪影中藏着另一个场景）。如果你生成的提示词只停留在直白的“人物站在雨中”，而没有 `clever negative space` 或 `figure-ground inversion` 等符号设计，将被视为残次品。
- **工具伪造 (Tool Forgery)**：严禁使用旧版本废弃工具 `write_file`，物理落盘必须使用合规的 `write_to_file`。
