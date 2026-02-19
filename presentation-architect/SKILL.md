---
name: presentation-architect
description: "演示文稿全栈架构师。V3.0 认知枢纽版：引入多 Agent 博弈审计、逻辑湖自动联结与视觉信噪比度量。"
language: js
---

# SKILL.md: Presentation Architect V3.0 (The Cognitive Nexus)

## 0. 就绪度审计 (Readiness Audit - Phase 0)
- **环境自愈**：检测文件类型，强制执行 markitdown 环境检查。
- **模板锚定**：必须定位到 `blueprint-template.md`。
- **知识就绪**：预加载 `references/content-rules.md` 以注入咨询级交付标准。

## 1. 核心工作流 (The Golden Path)

### 第一阶段：战略透视 (Blueprint Phase)
*   **Input**: 用户原始需求、源文件（DOCX/PDF/MD）、`memory.md`。
*   **Output**: `outline.md`, `working_memory.json` (Logic context).
1. **初始化物理目录**：初始化目录 `./.gemini/MEMORY/slide-deck/{Topic}_{Date}`。
2. **意图对齐**：使用 `ask_user` 确认受众权重、核心结论与痛点。
3. **逻辑湖联结**：检索 `memory.md`，将历史教训与项目背景注入蓝图。
4. **逻辑构建**：生成 `outline.md`，使用 `ask_user` 确认。**[硬约束：全量 Action Titles]**。
5.**确认风格逻辑构建**：使用 `ask_user` 确认视觉风格。
6. **全量蓝图生成**：遵循 `blueprint-template.md` 生成最终 MD 文件。
7. **视觉信噪比度量**：计算 `Visual_SNR`。低于 0.7 必须拆分页面。
78 **多 Agent 冲突审计**：
    - **Customer Agent**: 质疑落地性。
    - **Competitor Agent**: 寻找同质化漏洞。
    - **Financial Agent**: 审计 ROI。

### 第二阶段：视觉锻造 (Forging Phase)
*   **Input**: `outline.md`, `references/styles/`。
*   **Output**: `assets/images/*.png`, `assets/charts/*.svg`。
1. **素材生成**：基于 `automation_prompt` 调用图像生成脚本。参考 `references/styles/` 确保视觉一致性。
2. **数据可视化**：根据蓝图中的 `VISUAL_CODE` 生成图表。

### 第三阶段：物理组装 (Assembly Phase)
*   **Input**: 蓝图 MD、图片素材、`references/layouts.md`。
*   **Output**: `final_deck.pptx`, `final_deck.pdf`。
1. **自动化合并**：执行 `scripts/build-deck.py` 进行物理层组装。

## 2. 知识锚点 (Knowledge Anchors - Progressive Disclosure)
当任务涉及特定细节时，**必须**查阅以下资源：
*   **内容规范**：`references/content-rules.md` (用于审计标题和正文密度)。
*   **视觉风格**：`references/styles/` (用于选择设计调性)。
*   **布局指南**：`references/layouts.md` (用于确定页面结构)。

## 3. 核心约束 (The Iron Rules)
*   **反熵减协议**：严禁使用“以此类推”、“如下所示”等模糊表述。
*   **路径锁定**：产出必须在 `./.gemini/slide-deck/` 或指定 MEMORY 目录下。
*   **证据密度**：每页 Slide 必须包含至少一个核心证据点（数据或引用）。

## 4. 维护协议 (Maintenance Protocol)
*   **Logic Mutation**: 修改脚本逻辑后，必须更新脚本 Standard Header 中的 `@Input/@Output`。
*   **Knowledge Update**: 新增样式或布局后，同步更新 `_DIR_META.md` 指向的新资源。
*   **Validation**: 任何重大更新后，必须通过 `skill-creator/scripts/quick_validate.py`。
