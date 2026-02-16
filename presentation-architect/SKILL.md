---
name: presentation-architect
description: "演示文稿全栈架构师。整合战略逻辑蓝图设计与高保真自动化渲染，确保交付物具备商业穿透力与视觉一致性。"
---

# SKILL.md: Presentation Architect (演示文稿逻辑与视觉专家)

## 1. 触发逻辑 (Trigger)
- 当用户提出“制作 PPT”、“设计演示文稿”、“生成幻灯片”或“构建战略蓝图”时激活。

## 2. 核心工作流 (The Golden Path)
本技能强制执行“逻辑先行，视觉后置”的闭环流程：
1. **Phase 1: Strategic Blueprinting**: 构建 Ghost Decking，定义 Lead-ins 与证据网。
2. **Phase 2: Narrative Approval**: 用户确认逻辑大纲。
3. **Phase 3: Visual Rendering**: 自动化多模态渲染，生成 PPTX/PDF。

## 3. 核心 SOP

### 第一阶段：战略透视 (Blueprint Phase)
1. **意图对齐**：使用 `ask_user` 确认受众、场景与核心结论。
2. **逻辑构建**：生成 `outline.md`。要求每一页标题必须是“行动标题（Action Title）”。
3. **证据织网**：为核心断言标注数据来源或证据点。

### 第二阶段：视觉合成 (Rendering Phase)
1. **风格锚定**：根据内容信号从 `references/styles/` 选择最优视觉基因。
2. **提示词工程**：调用 `scripts/generate-prompts.py` 将逻辑映射为视觉。
3. **自动化渲染**：执行 `scripts/generate-images.py`。启用 **Smart Resume** 机制以应对网络中断。

### 第三阶段：物理固化 (Assembly Phase)
1. **组件注入**：调用 `scripts/build-deck.py`。
2. **可编辑性保障**：默认使用 `--editable-text` 模式，确保用户具备二次微调能力。

## 4. 维护与资源
- **渲染引擎**: scripts/build-deck.py.
- **蓝图模板**: references/blueprint-template.md.
- **风格库**: references/styles/.
