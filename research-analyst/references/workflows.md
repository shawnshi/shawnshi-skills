# Research Analyst Workflows (V6.2)

## Phase 0: Alignment Protocol (MANDATORY)
在进入任何模式前，必须执行对齐（使用 `ask_user` 工具）：
1. **确认深度**: 标准报告(3000字) vs 深度报告(6000+字)。
2. **确认对象**: 明确报告的读者画像。
3. **确认核心问题**: 3-5个关键研究痛点。
4. **大纲确认**: 生成 `outline.md` 后，使用 `ask_user` 请求用户确认。若用户提出修改建议，必须循环调整直至批准。

## Mode A: Standard (标准报告 / 约 3000 字)
*Target: Rapid intelligence gathering and synthesis.*
...

## Mode B: Deep Dive (深度研究 / 6000+ 字)
*Target: Strategic defensibility and non-consensus insight.*

### Task 1: Intelligence Saturation
...

### Task 2: Structural Construction
1. **Blueprint**: 生成详细 `outline.md`。
2. **Approval**: **必须**使用 `ask_user` 获得批准或修改建议。
3. **Iteration**:
   - 逐章撰写，每章 >= 800 字。
   - 风格要求：**Narrative Flow** (叙事流)，减少列表使用。
   - 动态更新 Memory，确保上下文衔接。

### Task 3: Forging & 3D Audit
1. **Assembly**: 物理拼接，输出文件名为 `{Topic}_{Date}.md`。
2. **Logic Audit**: 执行 Fidelity/Defensibility/Entropy 校验。
3. **Final Review**: 使用 `ask_user` 验收最终报告，支持返工指令。
4. **Outcome**: 产出包含“灰度解”的万字级深度报告。
