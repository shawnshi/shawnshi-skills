---
name: presentation-architect
description: 战略级演示文稿架构师 (V10.0)。当用户需要“制作战略 PPT”、“CTO 汇报布道”或“构建决策型方案”时，务必强制调用。该技能遵循 Mentat 语义主权协议，执行 Phase 1-4 硬阻塞流转，交付 100% 原生、具备逻辑深度的 PPT 资产。
triggers: ["制作战略级PPT", "生成演示文稿蓝图", "构建决策型汇报", "设计高级咨询级幻灯片", "CTO技术布道", "架构转型汇报"]
---

# SKILL.md: Presentation Architect V10.0 (Native Rendering Edition)

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：系统必须严格执行 Phase 1 (校准) -> Phase 2 (骨架与风格) -> Phase 3 (叙事蓝图) -> Phase 4 (原生组装)。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 进行显式声明。如果检测到跨级跳跃，视为严重违规。

## 1. 核心哲学 (Core Philosophy)
*   **Narrative is Asset (叙事即资产)**：每一页幻灯片都是逻辑链条上的物理节点。
*   **Action Title is King (判词先行)**：标题必须是具备观点的主题句，而非名词。
*   **High Visual SNR (极高信噪比)**：字不如表，表不如图。强迫听众在 3 秒内理解核心。
*   **Semantic Invariance (语义守恒)**：生成的 PPT 原生对象必须与获批的蓝图逻辑 100% 同态。

## 1.5 Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation, the mass generation of speaker notes and slide content MUST NOT be executed directly in the main memory.
1. **Storyboard Packet**: After Phase 2, write the approved Storyboard (Architecture Diagram) and outline to a physical sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Storyboard_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent (e.g., `generalist`) to consume the packet, generate the detailed script and content for each slide, and write the output back to a physical assembly file.
3. **Suspension**: The main agent must suspend execution, wait for the sub-agent to complete the heavy lifting, and then read ONLY the final assembled file to perform the final "De-AI" polish (Phase 4).

## 2. 核心工作流 (The Golden Path)

### [⏳] Phase 1: Strategic Calibration (战略校准) **[Mode: PLANNING]**
1. **初始化**：在对话框中明确输出 `[System State: Moving to Phase 1]`。
2. **战略对齐 (First ask_user)**：无论用户初始输入多么详尽，你都【必须强制】调用 `ask_user` 工具，获取并确认以下参数：
   - **场景模型**：(如：咨询项目汇报 - 决策型 / 内部产品发布 - 愿景型)。
   - **核心受众**：(明确具体职能，如：卫宁健康 CEO、某三甲医院院长 - 👉 决定技术深度与商业黑话的浓度)。
   - **政策/业务锚点 (Business/Policy Anchor)**：锁定本次汇报的外部驱动力。
   - **核心影响力目标**：(定义一句话的终局，如：消除对短期投入的顾虑，达成二期合同签署)。
   - **汇报时长与规格**：(定义汇报时间、页面数量，默认强制锁定 16:9 画布比例)。
   - **视觉风格 (Visual Style)**：(向用户推荐 `references/styles/` 目录下的风格库文件或请求用户指定)。
3. **Memory Interleave (MSA 增强)**：【必须强制】使用 `run_shell_command` 调用 `python C:\Users\shich\.gemini\extensions\vector-lake\cli.py query "你的推演指令" --interleave` 校验上述锚点的本地技术可行性，确保 PPT 核心主张有物理事实支撑。

### [🧠] Phase 2: Style & Ghost Deck (风格指令与骨架) **[Mode: PLANNING]**
1. **载入视觉风格**：读取 `C:\Users\shich\.gemini\skills\presentation-architect\references\styles\{Style_Name}.md` 并在脑海中构建全局视觉基调。
2. **构建 Ghost Deck (标题大纲)**：设计叙事性标题链条。使用 Mermaid 语法 (`graph TD` 或 `mindmap`) 物理生成一张“逻辑推演全局视图”，展现推导路径。
3. **红队审计**：激活对抗视角，从核心受众的角度审视标题链条，指出可能遭受反驳的弱点，并在大纲中予以修补。
4. **强制审批 (Approval Gate)**：调用 `ask_user` 提交风格块与标题大纲。未获批前禁止跨入 Phase 3。同时创建沙箱目录：`C:\Users\shich\.gemini\slide-deck\{Topic}_{Date}\`。

### [💡] Phase 3: Slide-by-Slide Blueprinting (逐页叙事蓝图) **[Mode: EXECUTION]**
**【防脱水与单步落盘机制】：** 
1. 每次对话轮次仅允许起草 3-5 页蓝图，使用 `write_file` 或 `replace` 写入沙箱目录内的 `plan.md` 和蓝图文件。
2. 组装后的**最终蓝图文件名必须为 `outline.md`**，存放在 `C:\Users\shich\.gemini\slide-deck\{Topic}_{Date}\outline.md`。禁止使用任何其他命名，否则 Phase 4 的渲染脚本将直接崩溃。

**审计强制标记位 (Mandatory Markers) - `outline.md` 必须包含：**
#### 封面 (Title Slide)
*   **风格**: 海报式布局 (Poster-style)。
*   **文字**: 只有主标题、副标题和品牌标识，严禁任何细碎文字。

#### 封底 (Closing Slide)
*   **风格**: 行动锚点式 (Call to Action)。
*   **文字**: 一个强有力的金句或一个清晰的下一步行动建议。

#### 内容页 (Content Slide)
每一页蓝图必须【物理包含】以下标签：
- **Page [X]: [叙事性主题句]**
- **// NARRATIVE GOAL (叙事目标)**：解释本页如何承上启下。
- **// PUNCHLINE (一句话洞察)**：本页的金句或最核心观点。
- **// KEY CONTENT (关键内容)**：
    - Headline: [有观点的主标题。严格限制：≤ 8 单词 或 15个中文字]
    - Sub-headline: [补充说明。严格限制：≤ 12 单词 或 20个中文字]
    - Body/Data: [关键论据高度浓缩，带有具体数字的数据点，严禁大段说明文]。
    - Trust_Anchor: `[Ref: Evidence_Node_ID]`，确保事实下锚。
- **// VISUAL_CODE (结构化视觉微码)**：精确的 Hex 颜色值或具体的材质描述。
- **// VISUAL (视觉画面)**：描述具体图像内容，强调信息图表化。
- **// LAYOUT (布局结构)**：描述物理区域比例（如：左侧 30% 结论 / 右侧 70% 瀑布图）。
- **// Script**：演讲逐字稿与注意事项。

**完工确认**：在确保所有蓝图碎片合并保存至 `outline.md` 后，宣告进入下一阶段。

### [📦] Phase 4: Red Team Audit & Native Asset Forging (红队终审与原生锻造) **[Mode: EXECUTION & VERIFICATION]**
1. **语义对抗门**：对 `outline.md` 进行最终的逻辑快查，若有致命缺陷使用 `replace` 局部修补，严禁大改骨架。
2. **原生渲染 (Native Rendering)**：调用渲染引擎。必须使用系统环境中的绝对路径。
   执行：`run_shell_command`: `python C:\Users\shich\.gemini\skills\presentation-architect\scripts\build-deck.py C:\Users\shich\.gemini\slide-deck\{Topic}_{Date}`
3. **输出资产**：如果脚本执行成功 (Exit Code == 0)，则在终端内输出 PPT 生成成功的绝对路径。

## 3. 核心约束 (Iron Rules)
*   ❌ **禁止“谢谢聆听”**：末页必须是 Call to Action。
*   ❌ **禁止模糊占位符**：严禁“这里放置图表”，必须写明 X/Y 轴与趋势结论。
*   **【数据图解强约束】**：当涉及架构、流程或医疗数据闭环时，必须在蓝图的 `// VISUAL` 节点强制要求使用具有逻辑深度的图解模型（例如：桑基图描述资金/数据流向、等距视角表示系统分层），拒绝单纯的柱状图/饼图堆砌。
*   **【视觉平衡与层级】**：强制保持 30% 的画面留白。遵循严格的字体与视觉层级（标题 > 副标题 > 数据 > 装饰）。
*   **【图文映射法则】**：严禁使用项目符号列表 (Bullet points) 罗列超过3条以上的信息。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "presentation-architect", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- **[CRITICAL: OUTLINE NAMING]**: The output of Phase 3 MUST be explicitly named `outline.md` and saved to the project directory. The script `build-deck.py` is hard-coded to look for this exact filename.
- **[PATH CONSISTENCY]**: All paths in shell commands must be absolute, e.g., `C:\Users\shich\.gemini\...`
- **[TOOL_ENFORCEMENT]**: "task_boundary" is NOT a valid tool. Do NOT attempt to call it. Manage state explicitly using `[System State: Moving to Phase X]` standard text output.

---
*SYS_CHECK: V10.0 Narrative Engine Ready. Native Rendering Enforced.*
