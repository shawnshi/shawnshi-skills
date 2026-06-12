---
name: academic-paper-reader
version: 8.1.0
description: "Primary owner for single-paper or small-paper-set reading, dissection, lineage tracing, and first-principles explanation. V4.0 features Narrative Storytelling (七拍故事弧), Extreme Copywriting (灵魂句炼金术), and Deep Critique. Use when the user wants to understand one paper deeply, strip jargon, or trace how a specific idea evolved. Prefer academic-deep-research for topic-wide literature review."
triggers: ["读论文", "拆解论文", "溯源分析", "paper river", "分析这篇论文的演化", "学术透视"]
---

<strategy-gene>
Keywords: 读论文, 溯源分析, 第一性原理, 七拍故事弧, 同例贯穿, 灵魂句炼金术, 承重类比, 变形替代
Summary: 剥离学术外衣，提取思想核心。通过逆推 3-5 层前序论文构建“论文河”，并将溯源过程包裹在七拍故事弧中。
Strategy:
1. 宿敌锁定与故事搭台：识别 Related Work 中批判的前人方法，将其作为故事里的“旧路墙壁”。
2. 一例到底与承重类比：强制在「问题」段落确立一个具体的具象例子，并在全篇极致沿用。
3. 灵魂句炼金术：强制 Title 满足 6-15 字、零中英混杂、动词为骨的极致凝练标准。
4. 变形替代定义：解释概念关系时，优先使用“把A变形成B”代替生硬定义。
AVOID: 禁止全量加载 PDF（算力黑洞）；禁止沦为干瘪的学术编年史；禁止脱离例子的抽象术语堆砌；严禁主文中出现未翻译的 LaTeX 原始公式及“本文提出”等翻译腔。
</strategy-gene>

# Academic Paper Reader (学术透视与精读 V8.1 Native)

> **核心法则**: 读一篇论文，最难的不是看懂，是讲明白。把学术编年史变成一个跌宕起伏的故事。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Pre-processing & Subagent Delegation (格式洗清与并发沙盒) [Mode: PLANNING]
1. **前置降维 (Critical)**: 严禁主代理或子代理直接读取海量二进制 PDF。主代理必须先调用 `run_command` 执行 Markdown 格式转换器降维：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-markdown-converter\scripts\converter.py" <PDF物理绝对路径> -o "C:\Users\shich\.gemini\tmp\playgrounds\cleaned_paper.md"`
2. **任务封装与委派 (Delegation)**: 将提取出的 `cleaned_paper.md` 路径、核心解析指令及“提取核心架构总览图”的任务，封装发给 `research` 子代理（使用 `invoke_subagent` 工具）。主代理必须原地挂起，只读取最终的结构化解析结果，防止注意力衰退。

### Phase 2: Traceback & Narrative Construction (溯源与故事构建) [Mode: EXECUTION]
1. 要求子代理读取 `C:\Users\shich\.gemini\config\skills\academic-paper-reader\resources\storytelling_manual.md` 获取灵魂句 Few-Shot 范例。
2. 根据提取的 Baseline，向上递归追溯 3-5 层前置研究。
3. 用“七拍故事弧”将脉络串联：`主角 -> 困境 -> 旧路(前人墙壁) -> 转折 -> 解法 -> 结局 -> 内核`。

### Phase 3: The Hard Gate (草稿拼装与物理审计) [Mode: VERIFICATION]
1. 将解析的故事线写入临时文件草稿：`C:\Users\shich\.gemini\tmp\draft_paper.md`。
2. 强制调用底层物理过检脚本，必须挂载 UTF-8 安全锁：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\academic-paper-reader\scripts\paper_audit_gate.py" "C:\Users\shich\.gemini\tmp\draft_paper.md"`
3. 若报错退出（如：未包含 3 组对比数字，或一例到底断层），必须退回修正，最多重试 2 次。

### Phase 4: Commit & Telemetry (落盘与归档) [Mode: EXECUTION]
1. 脚本返回 Exit Code 0 后，强制使用 `write_to_file` 归档。
2. 文件命名规范：`paper-{简短标题}--{YYYYMMDDTHHMMSS}.md`。
3. 落盘路径：`C:\Users\shich\.gemini\MEMORY\raw\Huggingface-Daily-Papers\`

## 2. <Contracts> (输出与交付契约)
- **灵魂句炼金术契约 (Copywriting Contract)**：Title 绝对禁止出现英文术语（人名/产品名例外）；6-15 字约束，主干 4-8 字，动词为骨。必须带有反直觉或对仗的张力姿态。杀绝被动句和“进行+名词”等翻译腔。
- **一例到底契约 (Single Anchor Constancy)**：【绝对红线】必须在开局找到一个具象的例子，此后的旧路、转折和机制解法必须在同一个微观例子上推演。换例子 = 换地图 = 认知断层。
- **反直觉数字契约 (Proof Points)**：结局部分必须包含至少 3 组最说明问题的对照数字，并强制挑出一个最反直觉的副发现。
- **致命预设契约 (Hidden Assumptions)**：博导审稿环节严禁只批评“数据集大小”等表面问题，必须指出作者逻辑底层的“未言明假设”。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **路径与工具崩塌 (Path/Tool Deadlock)**：严禁写入漏层级的脚本路径（如 `{SKILL_DIR}`）。执行 Python 审计必须映射绝对物理地址。物理落盘严禁使用编造的 `write_file`，必须且只能使用原生的 `write_to_file` 工具。
- **黑话与公式裸奔 (Jargon Pollution)**：如果发现“本文提出了一种新框架”的翻译腔，或者正文中直接裸露 LaTeX 原始数学公式而没有将其翻译成“自然语言大白话”，该草稿将被系统直接击毙。
- **抽象漂浮症 (Abstract Floating)**：解释机制时如果没有使用“承重类比（如把调度器比作前台护士）”或“变形替代”，而全是脱离具体例子的术语堆砌，将被直接打回重写。
