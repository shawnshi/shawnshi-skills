---
name: academic-paper-reader
description: "Primary owner for single-paper or small-paper-set reading, dissection, lineage tracing, and first-principles explanation. Use when the user wants to understand one paper deeply, strip jargon, or trace how a specific idea evolved. Prefer academic-deep-research for topic-wide literature review and academic-paper-writer for drafting or revising a paper."
triggers: ["读论文", "拆解论文", "溯源分析", "paper river", "分析这篇论文的演化", "学术透视"]
---

<strategy-gene>
Keywords: 读论文, 溯源分析, 第一性原理, 演化地图
Summary: 剥离学术外衣提取思想核心，通过逆推 3-5 层前序论文构建“论文河”演化地图。
Strategy:
1. 宿敌锁定：识别 Related Work 中明确批判的前人方法 X，将其定为 Baseline。
2. 填坑叙事：以“上篇留坑 -> 本篇填坑 -> 本篇新坑”的费曼逻辑正向推进叙事。
3. 具象隐喻：必须为每篇核心论文找到一个具象中心隐喻（图/动作/场景）进行控制。
AVOID: 禁止全量加载 PDF（算力黑洞）；禁止保留 [URL] 占位符；禁止写没有推理外显的结果。
</strategy-gene>

# SKILL.md: 学术论文透视与精读 (V3.0: Cognitive Assault Edition)

> **核心法则**: 读论文不是做学术，是猎取思想。把别人的发现拆解成自己能用的认知，同时剥去其复杂的学术外衣，直击第一性原理。

## 1. 格式约束 (Format Stack)

### md 语法
- 加粗用 `*bold*`（单星号），禁止 `**bold**`
- 标题层级从 `*` 开始，严格遵循模板不跳级。

### 模板权威性与基准对齐
- 输出结构**必须**严格依据 `resources/template.md`。
- 生成前**必须**参考 `examples/APR-Reference.md` 满分战报，强行拉齐“毒舌”与“费曼化”的冷峻文风。禁止参考其他历史文件。

### Denote 物理归档规范
- 时间戳格式：`YYYYMMDDTHHMMSS` (如 `20260401T103000`)
- 可读时间格式：`YYYY-MM-DD Day HH:MM` (如 `2026-04-01 Wed 10:30`)
- 文件名规范：`paper-{简短标题}--{YYYYMMDDTHHMMSS}.md`
- 输出物理路径：强制使用 `write_file` 写入 `C:\Users\shich\.gemini\MEMORY\raw\Huggingface-Daily-Papers\`

## 2. 红线 (Mandatory Check)

1. *口语检验* — 你会这样跟朋友介绍一篇论文吗？如果不会，立即重写。学术腔是默认敌人。
2. *锚点撑全文* — 必须找到一个具象的中心隐喻（一张图、一个动作、一个场景），让所有概念围绕它生长。
3. *推理外显* — 模拟“一个人想明白的过程”，而非“呈现结果”。用“既然 A 是这样，那 B 能不能也这样？”带着读者推演。
4. *零术语* — 先用大白话落地，再顺带提术语名。能用两个字不用的四个字（“他们做了个东西” > “本文提出了一种框架”）。
5. *变形替代定义* — 解释概念关系时，优先用“把 A 变形为 B”而非“A 和 B 是 XX 关系”。
6. *不填充* — 删掉所有“值得注意的是”、“近年来随着”等废话。每句都要干活。
7. *落点在能用* — 给出“这意味着你可以___”，而非“这让我们重新思考___”。
8. *问题为轴* — 叙事主线是"问题怎么演化的"，论文只是配角。每篇论文的讲解重心必须是"它和前一篇的差异在哪"，而不是独立介绍。
9. *逻辑不断链* — 从祖师爷到目标论文，因果链条不能断。让读者感受到"前人留下了坑，所以这篇才不得不这么做"。
10. *诚实溯源* — 找不到 5 层就说找到几层。不确定就说不确定，严禁为了凑数编造引用批判关系。

## 3. 写作原则 (Writing Principles)
- **第一性原理透视** — 剥去学术外壳，看其本质。这个解决方案背后的物理/数学/逻辑本质是什么？
- **旧瓶装新酒** — 它是在哪个旧概念上做了什么微调？找出它的原型。
- **推理外显** — 模拟"一个人想明白的过程"，而非呈现"想明白之后的结果"。
- **落点在能用** — 给出"这意味着你可以___"，而非"这让我们重新思考___"。

## 3.5 Sub-agent Delegation Protocol (Mandatory Sandboxing)
**CRITICAL RULE**: To protect the main agent's context window from attention degradation and data bloat, heavy lifting tasks (e.g., mass web scraping, parsing long PDFs, or generating multi-thousand-word drafts) MUST NOT be executed directly in the main memory.
1. **Packet Creation**: Before starting the heavy task, write the required parameters, URLs, or chapter outlines to a physical sandbox file: `C:\Users\shich\.gemini\tmp\playgrounds\Task_Packet_[TIMESTAMP].md`.
2. **Delegation**: Explicitly invoke a sub-agent (e.g., `generalist`) to read the packet, execute the heavy generation/scraping, and write the final output back to a designated result file.
3. **Suspension**: The main agent must suspend its execution, wait for the sub-agent to finish, and then read ONLY the final output file to proceed with orchestration or final review.

## 4. 执行工作流 (OODA Pipeline)

###[Step 1: 目标锁定与核心批判提取]
- 获取目标论文：读取本地 PDF 或抓取网页。
- **锁定宿敌**：仔细阅读引言和 Related Work。找到它明确宣称“前人方法 X 有问题 Y”的地方。锁定它作为 Baseline 或主要批判对象的 1-3 篇核心前序论文。

###[Step 2: 逆向递归溯源 (Recursive Traceback)]
- 针对 Step 1 锁定的核心前序论文，调用搜索/阅读工具，**向上递归追溯 3-5 层**（或直到该领域的奠基论文）。
- **每层只抓三个核心**：标题/年份、它的核心解法、它对更前人的批判点。只追最相关的那条主线，严禁发散。

###[Step 3: 前沿延伸 (Forward Extension)]
- 反向搜索：目标论文之后，有没有新论文在批判/改进它？（谁又打了它的脸？）
- 找到最相关的 1-3 篇后续论文，提取同样的 Gap -> Fix 逻辑。

###[Step 4: X-Ray 核心透视与双图构建 (The Blackboard)]
在脑海中完成信息压缩，准备绘制两张纯 ASCII 字符图：
1. **溯源地图 (Traceback Map)**：以时间线展示 `[Paper A] --(问题X)--> [Paper B] --(问题Y)--> [目标论文]` 的演化链。
2. **逻辑拓扑 (Topology)**：针对目标论文，绘制其第一性原理映射图（输入 -> 核心干预 -> 输出）。

###[Step 5: 费曼式演化叙事 (Feynman Evolutionary Narrative)]
- **差异驱动叙事**：从最老的论文开始正向讲述。不要独立拼凑摘要，必须以“上一篇留下了什么坑（场景说明） -> 这一篇怎么填坑（类比说明） -> 这一篇又制造了什么新坑”为模板推进。
- 然后对目标论文进行常规的 V3.0 解剖（方法论、数据、结果、第一性概念拆解）。

### [Step 6: 博导审稿与启发 (Mentat Audit)]
- **博导判决**：结合演化史给出毒舌点评。它究竟是真正推动了河流向前，还是在一条快干涸的支流上自嗨？
- **启发点**：
    - **迁移**：某个零件能升级我的系统吗？
    - **混搭**：能产生化学反应吗？
    - **反转**：它颠覆了我的什么默认假设？该停下什么？

## 5. Telemetry & Metadata (Mandatory)
使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。JSON 结构：`{"skill_name": "academic-paper-reader", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 6. 历史失效先验 (NLAH Gotchas)
- `IF [Condition == "System Detected Repeated Failure"] THEN [Inject NLAH Prohibition Rule Here]`
- `IF [Action == "Read PDF"] THEN [Halt if Unconditional Full Read] AND [Require Targeted Extraction (start_line/end_line OR Extractors)]`
- `IF [Action == "Read PDF"] AND [File Size > 20MB] THEN [Halt standard extraction] AND [Require invoking markitdown to convert the PDF to an MD file prior to analysis]`
- `IF [Action == "Generate Org-mode Timestamp"] THEN [Require Format == "YYYYMMDDTHHMMSS" FOR "#+identifier:" AND "[YYYY-MM-DD Day HH:MM]" FOR "#+date:"]`
- `IF [Section == "Writing Style"] THEN [Halt if Tone == "Overly Academic/Passive"] AND [Require Direct, Active Voice]`

## When to Use
- 当用户要求精读、拆解、溯源或批判性分析学术论文时使用。
- 具体执行细节、阶段划分和输出风格仍以本文件上方既有协议为准。

## Workflow
- 遵循本文件已有的阶段化阅读、溯源、论证和写作流程。
- 不跳过已有的证据提取、问题重构、风格约束和失效先验检查。

## Resources
- 使用本技能目录中已经引用的 `assets/`、`references/`、`scripts/` 和模板文件。
- 若正文点名了具体提取器、转换脚本或参考模板，以那些本地资源为准。

## Failure Modes
- 将本文件已有的 `NLAH Gotchas` 以及各阶段的硬约束视为失败模式。
- 若缺少论文原文、分页定位或必要引用信息，必须显式报出阻塞点，不能静默降级。

## Output Contract
- 交付必须符合本文件已有的分析框架、叙事口径和证据标准。
- 如果存在引用、页码、时间戳或原话抽取要求，最终输出必须完整满足。

## Telemetry
- 按本文件上方已经定义的路径和 JSON 结构记录执行元数据。
