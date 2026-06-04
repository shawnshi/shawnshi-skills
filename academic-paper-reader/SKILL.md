---
name: academic-paper-reader
description: "Primary owner for single-paper or small-paper-set reading, dissection, lineage tracing, and first-principles explanation. V4.0 features Narrative Storytelling (七拍故事弧), Extreme Copywriting (灵魂句炼金术), and Deep Critique. Use when the user wants to understand one paper deeply, strip jargon, or trace how a specific idea evolved. Prefer academic-deep-research for topic-wide literature review."
triggers: ["读论文", "拆解论文", "溯源分析", "paper river", "分析这篇论文的演化", "学术透视"]
---

<strategy-gene>
Keywords: 读论文, 溯源分析, 第一性原理, 七拍故事弧, 同例贯穿, 灵魂句炼金术, 承重类比, 变形替代
Summary: 剥离学术外衣，提取思想核心。通过逆推 3-5 层前序论文构建“论文河”，并将整个溯源过程包裹在【主角/困境/旧路/转折/解法/结局/内核】的故事弧中。
Strategy:
1. 宿敌锁定与故事搭台：识别 Related Work 中批判的前人方法，将其作为故事里的“旧路墙壁”。
2. 一例到底与承重类比：强制要求在「问题」段落确立一个具体的具象例子，并在全篇机制解释中持续沿用；优先使用能映射核心组件的类比。
3. 灵魂句炼金术：强制 Title（核心论点）满足 6-15 字、零中英混杂、动词为骨的极致凝练标准，并要求子智能体读取 storytelling_manual.md 获取 Few-Shot 支撑。
4. 变形替代定义：解释概念关系时，优先使用“把A变形成B”代替生硬定义。
AVOID: 禁止全量加载 PDF（算力黑洞）；禁止沦为干瘪的学术编年史；禁止脱离例子的抽象术语堆砌；严禁主文中出现未翻译的 LaTeX 原始公式及“本文提出”等翻译腔。
</strategy-gene>

# SKILL.md: 学术论文透视与精读 (V4.0: Narrative & Cognitive Assault Edition)

> **核心法则**: 读一篇论文，最难的不是看懂，是讲明白。讲给一个不懂这个领域的聪明人——讲到他能复述出来——你才算读完。把学术编年史变成一个跌宕起伏的故事。

## 1. 灵魂句炼金术 (Title & Copywriting Mastery)
这是 V4.0 最核心的认知标准。你必须用最少的字把整个故事的内核取出来。强制要求子智能体读取 `resources/storytelling_manual.md` 以获取 Few-Shot 范例。
- **中文母语凝练**：像汪曾祺、阿城、李娟的标题——短、净、有刃。杀绝被动句（“被锁在…”）、长定语后置（“那个由…引起的…”）、“进行+名词”等翻译腔。自检三问：汪曾祺会这么写吗？抽出来能不能立住？删掉一字会不会塌？
- **零中英混杂**：Title 绝对禁止出现英文术语（如 RL / Agent / token 等）。术语放正文展开，Title 只放纯正思想。例外：人名、产品名（GPT、Claude）。
- **6-15 字约束**：主干 4-8 字，动词为骨，名词具体。形容词能砍就砍（“惊人的”、“重大的”全删）。
- **姿态选择**：必须带有张力，选择以下其一：反直觉（如“学会反成枷锁”）、对仗并置（如“默想胜出口”）、或转折反讽。
- **可识别性兜底**：如果标题过于精炼导致外行完全猜不到方向，必须用中文副标题兜底解释（如 `#+subtitle: 把"还要写多远"做成一个 value 函数`）。

## 2. 格式与物理约束 (Format Stack)
- **模板权威性**：输出结构**必须**严格依据 `resources/template.md`。生成前**必须**参考 `examples/APR-Reference.md`。
- **Denote 物理归档规范**：
  - 时间戳：`YYYYMMDDTHHMMSS` (如 `20260401T103000`)
  - 可读时间：`YYYY-MM-DD Day HH:MM` (如 `2026-04-01 Wed 10:30`)
  - 文件名：`paper-{简短标题}--{YYYYMMDDTHHMMSS}.md`
  - 输出路径：强制使用 `write_file` 写入 `C:\Users\shich\.gemini\MEMORY\raw\Huggingface-Daily-Papers\`

## 3. 七拍故事弧与核心红线 (Narrative & Check Rules)
必须将整篇拆解包裹在以下七拍节奏中：`主角 -> 困境 -> 旧路 -> 转折 -> 解法 -> 结局 -> 内核`。
1. **一例到底 (Single Anchor Constancy)** — **绝对红线**。必须在开局找到一个具象的例子（如一道数学题、一个失败的交互），此后的旧路、转折和机制解法**必须**在同一个微观例子上推演。换例子 = 换地图 = 认知断层。
2. **三组数字与反直觉副发现 (Mandatory Proof Points)** — 结局部分必须包含至少三组最说明问题的对照数字（Baseline对比），并强制挑出一个**最反直觉的副发现**。如果没有反直觉发现，明说“这篇没有”，绝不硬挤。
3. **寻找致命预设 (Self-referential Critique)** — 博导审稿模块**严禁**只批评数据集大小等表面问题。必须揪出作者的**“核心未言明假设 (Hidden Assumptions)”**，指出其逻辑底层的脆弱点。
4. **口语检验** — 读起来必须像一个人在讲故事。把所有子标题盖住，故事流不能断。严禁“本文提出了一种新的框架”、“值得注意的是”等学术黑话。
5. **推理外显** — 模拟“一个人想明白的过程”，用“既然 A 是这样，那能不能试试 B？”带着读者往前推。
6. **落点在能用** — 结尾的启发必须是“这意味着你可以___”，绝非虚幻的感慨。
7. **承重类比与变形替代** — 解释机制时，优先使用能映射核心组件的类比（如跑步选手+手表）；解释概念时，优先用“把A变形成B”代替生硬定义。
8. **主文禁止公式裸奔** — 所有公式必须翻译成自然语言（如“模型每写一字都被监督”），原始 LaTeX 公式只能放在附录。禁止英文戏剧术语外露（如 protagonist/climax）。

## 3.5 Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation and data bloat, heavy lifting tasks (e.g., mass web scraping, parsing long PDFs, or generating multi-thousand-word drafts) MUST NOT be executed directly in the main memory.
1. **Packet Creation**: Write required parameters, URLs, or outlines to `C:\Users\shich\.gemini\tmp\playgrounds\Task_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent to read the packet and execute heavy generation.
3. **Suspension**: The main agent must suspend execution, wait for the sub-agent, and read ONLY the final output.

## 4. 执行工作流 (OODA Pipeline / Phase-Gate Architecture)

**必须按以下物理阶段串行执行，严禁跳步。**

### [Phase 1: Pre-processing & Task Delegation (格式洗清与调度隔离)]
- **前置格式洗清 (Critical)**: 在生成 Task Packet 之前，主代理必须先利用 `tool-markdown-converter` 技能（执行 `python C:/Users/shich/.gemini/config/skills/tool-markdown-converter/scripts/converter.py <PDF路径> -o C:/Users/shich/.gemini/tmp/playgrounds/cleaned_paper.md`）将原始 PDF 降维并结构化为纯净的 Markdown 文件。严禁让主代理或子代理直接读取二进制 PDF。
- **任务封装**: 将清洗后的 `cleaned_paper.md` 路径及核心指令封装为 Task Packet，交由子智能体处理。
- **架构图提取要求**：指示子智能体在生成的 MD 中尝试定位能够承载全文核心思路的总览图（如 Figure 1 对应的文本或描述），这对于后续故事推演至关重要。

### [Phase 2: Traceback & Narrative Construction (溯源与故事构建)]
- 强制子智能体读取 `resources/storytelling_manual.md`。
- 根据 Phase 1 提取的 Baseline，向上递归追溯 3-5 层。
- 用“七拍故事弧”将这些历史串联起来：前人的论文是“旧路撞墙”，目标论文是“转折”。

### [Phase 3: Markdown Assembly (拼装草稿)]
- 严格遵循 `一例到底` 和 `承重类比` 原则拼装内容，并写入临时路径 `tmp/draft_paper.md`。
- 必须包含三组关键数字和反直觉副发现。

### [Phase 4: The Hard Gate (物理层强制审计)]
- 调用：`python {SKILL_DIR}/scripts/paper_audit_gate.py tmp/draft_paper.md`
- 如果报错退出，必须阅读日志，退回 Phase 3 修正并重新过检。最多重试 2 次。

### [Phase 5: Commit (物理落盘)]
- 仅在脚本明确返回 `Audit Passed` 状态码 (Exit Code 0) 后，将内容落盘至最终归档目录。

## 5. Telemetry & Metadata (Mandatory)
使用 `write_file` 保存元数据至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
格式：`{"skill_name": "academic-paper-reader", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 6. 历史失效先验 (NLAH Gotchas)
- `IF [Condition == "System Detected Repeated Failure"] THEN [Inject NLAH Prohibition Rule Here]`
- `IF [Action == "Read PDF"] THEN [Force limit read_file or use grep_search. Strictly prohibit unconditionally ingesting all raw text of PDF.]`
- `IF [Section == "Writing Style"] THEN [Halt if Tone == "Overly Academic/Passive"] AND [Require Direct, Active Voice]`







## When to Use
TBD.

## Workflow
TBD.

## Resources
TBD.

## Failure Modes
TBD.

## Output Contract
TBD.

## Telemetry
TBD.
