---
name: presentation-architect
description: "演示文稿全栈架构师。V3.0 认知枢纽版：引入多 Agent 博弈审计、逻辑湖自动联结与视觉信噪比度量。"
---

# SKILL.md: Presentation Architect V3.0 (The Cognitive Nexus)

## 0. 就绪度审计 (Readiness Audit - Phase 0)
- **环境自愈**：检测文件类型，强制执行markitdown环境检查。
- **模板锚定**：必须定位到 `blueprint-template.md`。

## 1. 核心工作流 (The Golden Path)

### 第一阶段：战略透视 (Blueprint Phase)
0. **初始化物理目录**：初始化物理目录 `./.gemini/MEMORY/slide-deck/{Topic}_{Date}`与 `working_memory.json`
1. **意图对齐**：使用 `ask_user` 确认受众权重、核心结论与痛点。
2. **逻辑湖联结 (NEW)**：自动检索 `memory.md` 中的 `Project Context` 与 `Lessons Learned`，将历史经验作为约束条件注入当前蓝图。
3. **逻辑构建**：生成 `outline.md`，使用 `ask_user` 确认。**[硬约束：全量 Action Titles]**。
4. **证据织网**：将源文档的“干货”物理索引至每一页。
5. **全量蓝图生成**：参考“.\references\layouts.md”使用 `ask_user` 确认设计风格，遵循模板生成 .md。
   - **信息熵保护**：Body 严禁摘要化。
   - **视觉微码标准化**：遵循 Schema 生成 `VISUAL_CODE`。
6. **视觉信噪比度量 (NEW)**：计算 `Visual_SNR`。若低于阈值，自动建议增加数据维度或拆分页面。
7. **多 Agent 冲突审计 (NEW)**：
   - **Customer Agent**: 质疑落地性与 ROI。
   - **Competitor Agent**: 寻找逻辑同质化漏洞。
   - **Financial Agent**: 计算隐性成本。
   - **机制**: 只有当方案在三方博弈中存活，才允许进入下一阶段。
8. **闭环修订**：保存最终版至 `.\.gemini\slide-deck\final_blueprint.md`。

### 第二阶段：视觉锻造 (Forging Phase)

1. **素材生成**：基于 `automation_prompt` 调用图像生成技能。
2. **数据可视化**：调用 Python 脚本生成 SVG 图表。

### 第三阶段：物理组装 (Assembly Phase)
1. **自动化合并**：调用 `scripts/build-deck.py`。

## 2. 核心约束 (The Iron Rules)
- **反熵减协议**：长文输出时，严禁使用“以此类推”。
- **路径锁定**：所有产出锚定在 `.\.gemini\slide-deck\`。
- **资产主权**：强调本地文件存储。

## 3. 维护与资源
- **审计维度**: 逻辑链、证据密度、视觉隐喻、三方博弈。
- **逻辑湖**: memory.md (Project Context).
- **模板**: references/blueprint-template.md.
