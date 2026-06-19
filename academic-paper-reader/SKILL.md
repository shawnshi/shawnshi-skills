---
name: academic-paper-reader
version: 9.0.0
tier: action-allowed
description: '提取单篇文献的核心思想与前序溯源。使用七拍故事弧与一例到底将论文重构为极简的非术语认知故事。禁止用于大规模批量文献扫描（应移交deep-research）或未定稿资料的分析。'
triggers: ["读论文", "拆解论文", "溯源分析", "paper river", "分析这篇论文的演化", "学术透视"]
---

<strategy-gene>
Keywords: 读论文, 溯源分析, 第一性原理, 七拍故事弧, 同例贯穿, 灵魂句炼金术, 承重类比, 变形替代
Summary: 剥离学术外衣，提取思想核心，逆推构建论文河，并包裹在七拍故事弧中。
Strategy:
1. 1. 识别批判的前人方法作为故事的“旧路墙壁”。
2. 2. 确立具象例子并一例到底。
3. 3. 遵循精炼的灵魂句规则与变形替代定义。
AVOID: 大规模读取 PDF；堆砌抽象术语；原样保留未翻译的 LaTeX 原始公式。
</strategy-gene>

# Academic Paper Reader (学术透视与精读 V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. 
2. un_command (执行 converter.py 进行降维)
3. invoke_subagent (委托 research 代理读取模板与提取)
4. 
5. un_command (执行 paper_audit_gate.py 物理审计)
6. write_to_file (最终结果落盘)
7. 注：偏离此轨迹则视为执行越权或幻觉。

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Pre-processing & Subagent Delegation (格式洗清与并发沙盒)
1. **前置降维**: PDF 二进制解析约束已左移。使用原生 
un_command 脚本执行格式转换降维：
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-markdown-converter\scripts\converter.py" <PDF物理绝对路径> -o "C:\Users\shich\.gemini\tmp\playgrounds\cleaned_paper.md"
2. **任务委派**: 将解析指令及“提取核心架构总览图”任务，使用 invoke_subagent (指定 TypeName: research 或 self) 委托。主代理只读取结构化结果以防上下文膨胀。

### Phase 2: Traceback & Narrative Construction (溯源与故事构建)
1. 子代理需读取 C:\Users\shich\.gemini\config\skills\academic-paper-reader\resources\storytelling_manual.md 获取灵魂句 Few-Shot 范例。
2. **架构依赖**：子代理需读取并遵循 C:\Users\shich\.gemini\config\skills\academic-paper-reader\resources\template.md 的全套字段与四段式结构进行输出。
3. 根据提取的 Baseline，向上递归追溯 3-5 层前置研究。
4. 将“七拍故事弧”无缝浇筑进 	emplate.md 的架构中，不可遗漏任何一拍。

### Phase 3: The Hard Gate (草稿拼装与物理审计)
1. 将解析的故事线写入临时文件草稿：C:\Users\shich\.gemini\tmp\draft_paper.md。
2. **脚本审计**: 调用底层脚本过检：
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\academic-paper-reader\scripts\paper_audit_gate.py" "C:\Users\shich\.gemini\tmp\draft_paper.md"
3. 若报错退出，需退回修正，最多重试 2 次。

### Phase 4: Commit & Telemetry (落盘与归档)
1. 脚本返回 Exit Code 0 后，强制使用 write_to_file 归档。
2. 文件命名规范：paper-{简短标题}--{YYYYMMDDTHHMMSS}.md。
3. 落盘路径：C:\Users\shich\.gemini\MEMORY\raw\Huggingface-Daily-Papers\

## 2. <Contracts> (输出与交付契约)
- **灵魂句炼金术契约 (Copywriting Contract)**：Title 绝对禁止出现英文术语（人名/产品名例外）；6-15 字约束，主干 4-8 字，动词为骨。必须带有反直觉或对仗的张力姿态。杀绝被动句和翻译腔。
- **一例到底契约 (Single Anchor Constancy)**：【绝对红线】必须在开局找到一个具象的例子，此后的旧路、转折和机制解法必须在同一个微观例子上推演。换例子 = 换地图 = 认知断层。
- **反直觉数字契约 (Proof Points)**：结局部分必须包含至少 3 组最说明问题的对照数字，并强制挑出一个最反直觉的副发现。
- **致命预设契约 (Hidden Assumptions)**：博导审稿环节严禁只批评“数据集大小”等表面问题，必须指出作者逻辑底层的“未言明假设”。

## 3. <Failure_Taxonomy> (失败分类学)
- **轨迹越权 (Trajectory Bypass)**：未遵循 [IN_ORDER] 轨迹执行；使用相对路径或非原生的编造指令（如伪名 write_file）。
- **黑话与公式裸奔 (Jargon Pollution)**：未翻译的 LaTeX 数学公式和“本文提出了一种新框架”的翻译腔（将由审计脚本 paper_audit_gate.py 直接拦截并击毙）。
- **抽象漂浮症 (Abstract Floating)**：解释机制时未应用承重类比或变形替代，脱离了微观例子（将由审计脚本拦截打回）。
