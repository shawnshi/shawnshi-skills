# Research Analyst (V6.2: Forge Edition)

工业级深度研究流水线。通过 `scripts/` 引擎管理状态与产物，突破 LLM 上下文限制。V6.2 版本强化了“深度守卫”与“脱模自动化”。

## Core Philosophy
*   **Cognitive Assembly Line**: 分章撰写，增量加载。
*   **Substance Guard**: 强制执行每章 800+ 字的水位线约束，拒绝肤浅综述。
*   **De-molding Logic**: 交付产物自动剔除元数据注释、Todo 与非法加粗。
*   **3D Logic Audit**: 真实性(Fidelity)、防御性(Defensibility)、信息熵(Entropy)。

## Execution Protocol

### Phase 1: Initiation & Alignment
1.  **Alignment**: 在开始前，**必须**确认参数。
    ```javascript
    ask_user({
      questions: [
        { header: "研究深度", type: "choice", question: "深度选择：", options: [{ label: "标准报告", description: "3000字" }, { label: "深度报告", description: "6000字+" }] },
        { header: "报告对象", type: "text", question: "目标受众？" },
        { header: "核心问题", type: "text", question: "核心痛点？" }
      ]
    })
    ```
2.  **Initialize**: 目录初始化。生成 `_DIR_META.md` 及 `working_memory.json`。
3.  **Fact Sheet Initialization**: 在 OSINT 结束后，**必须**提炼“核心技术锚点” (Technical Anchors) 存入 `working_memory.json`。

### Phase 2: Structural Drafting (Substance Focus)
1.  **Outline**: 生成大纲。
2.  **Approval (STOP)**: 展示大纲并获得批准。
3.  **Drafting Rules (MANDATORY)**:
    *   **Depth**: 每一章原则上**不少于 800 字**。必须包含：技术细节、工程逻辑、二阶效应。
    *   **Style**: 叙事流 (Narrative Flow)。**严禁**使用列表 (Bullet Points)。
    *   **Negative Constraints**: **禁止**在正文中使用加粗 (`**`)。
    *   **Headers**: 每个分章节文件必须包含标准的 GEB-Flow 头部。

### Phase 3: Forging & Delivery (Automatic Audit)
1.  **Assembly & Polish**: 执行集成后的 `scripts/assembler.py`。
    *   自动移除元数据块 (`"""..."""`)。
    *   自动移除所有正文加粗 (`**`)。
    *   **深度审计**: 脚本会报告每章字数，若未达标则标记为 `warning_depth_insufficient`。
    ```bash
    python scripts/assembler.py --path "research_projects/research_{Topic}/chapters" --title "{Full Title}" --min_words 800
    ```
2.  **Executive Layer**: 手动添加最终执行摘要。
3.  **Final Review (STOP)**: 确认验收。
4.  **Strategic Genome Mutation**: 执行 `scripts/sync_macro.py` 同步记忆。

## Resources
*   **Scripts**: `scripts/assembler.py` (Blacksmith), `scripts/memory_manager.py` (Core).
*   **Audit Standards**: `references/editor.md`.

## Troubleshooting
*   **Depth Warning**: 若脚本报警字数不足，必须重新扩充相关章节，严禁直接交付。
*   **Metadata Leak**: 若报告中出现注释块，重新运行组装脚本并检查正则表达式。
