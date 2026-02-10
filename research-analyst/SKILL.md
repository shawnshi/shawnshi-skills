---
name: research-analyst
description: 执行万字级深度研究的专家系统。V6.0 引擎版，支持分章生产、状态管理与物理拼接，产出高密度战略报告。
---

# Research Analyst (V6.0: Engine Edition)

工业级深度研究流水线。通过 `scripts/` 引擎管理状态与产物，突破 LLM 上下文限制。

## Core Philosophy
*   **Cognitive Assembly Line**: 分章撰写，增量加载。
*   **Anti-Summarization**: 物理拼接，拒绝摘要导致的信息熵减。
*   **3D Logic Audit**: 真实性(Fidelity)、防御性(Defensibility)、信息熵(Entropy)。

## Execution Protocol

### Phase 1: Initiation & Alignment (Semantic Alignment Layer)
1.  **Alignment (MANDATORY)**: 在开始前，**必须**确认参数。若用户未提供核心问题，必须先输出“推荐关注点”供确认。
    ```javascript
    ask_user({
      questions: [
        { header: "研究深度", type: "choice", question: "深度选择：", options: [{ label: "标准报告", description: "3000字" }, { label: "深度报告", description: "6000字+" }] },
        { header: "报告对象", type: "text", question: "目标受众？" },
        { header: "核心问题", type: "text", question: "核心痛点？（若为空将由 AI 推荐）" }
      ]
    })
    ```
2.  **Initialize**: 目录初始化将自动生成 `_DIR_META.md`。
    ```bash
    python scripts/memory_manager.py init --path "research_projects/research_{Topic}" --topic "{Topic}"
    ```
3.  **Intelligence (OSINT Mandatory)**: 
    *   **Rule**: 对于“深度报告”，在撰写章节前**必须**执行至少一次 `google_web_search`。
    *   获取 2025-2026 年最新案例、政策及非共识观点，并存入 `sources/`。

### Phase 2: Structural Drafting (Loop & Parallelism)
1.  **Outline**: 生成大纲。
2.  **Approval (STOP)**: 展示大纲并获得批准。
3.  **Drafting (Parallel Mode)**:
    *   **Header Requirement**: 每一个章节文件必须包含 GEB-Flow 头部。
    ```markdown
    """
    <!-- Input: Raw Intelligence from sources/, Previous Chapters -->
    <!-- Output: Chapter Logic, Strategic Insights -->
    <!-- Pos: {Project_Path}/chapter_xx.md -->
    """
    ```
    *   **Parallelism**: 若章节间逻辑耦合度低，可同时启动多个 `write_file` 任务以提升效率。

### Phase 3: Forging & Delivery (Recursive Evolution)
1.  **Assembly**: 执行 `scripts/assembler.py`。
2.  **Executive Layer**: 添加执行摘要。
3.  **Final Review (STOP)**: 确认验收。
4.  **Strategic Genome Mutation (AUTOMATED)**:
    *   验收通过后，**必须**自动分析报告中的“非共识观点”。
    *   更新 `memory/strategic_genome.json`。
    *   执行修复后的同步脚本：
    ```bash
    python scripts/sync_macro.py
    ```

5.  **Visual Standards**: 
    *   **Consulting Style**: 采用顶级咨询公司风格（如 McKinsey）。**坚持叙事流 (Narrative Flow)**，**严禁滥用列表 (Anti-Bullet Points)**。仅在展示数据或互斥选项时使用列表。
    *   **排版约束**: **禁止**在正文中使用加粗（双星号 `**`）。仅在标题或执行摘要等关键元数据区域允许使用。
    *   默认使用二级标题 (`##`)。
    *   保持呼吸感（每段不超过 200 字）。
6.  **Density Guard**: 脚本会自动校验 `source_bytes` vs `final_bytes`。如果损失率 > 5%，脚本会报警，此时**禁止交付**。

## Resources
*   **Detailed Workflows**: `references/workflows.md`
*   **Audit Standards**: `references/editor.md`

## Troubleshooting
*   **Memory Corruption**: 若 JSON 读写失败，手动检查 `working_memory.json` 格式。
*   **Density Warning**: 若拼接后变小，检查是否有空文件或编码问题。
