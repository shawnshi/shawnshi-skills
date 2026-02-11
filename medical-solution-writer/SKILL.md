---
name: medical-solution-writer
description: 医疗数字化解决方案专家，基于 Text-to-Action 范式 design 转型规划。
---

# SKILL.md: Medical Solution Writer (医疗数字化解决方案专家)

> **Version**: 2.8 | **Last Updated**: 2026-02-09 | **Context**: Visual Architecture & Text-to-Action Paradigm

## 1. 触发逻辑 (Trigger)
当用户提出以下请求时自动激活：
- “编写一份医疗数字化解决方案”
- “针对[医院/区域]设计数字化转型规划”

## 2. 核心指令 (Core SOP)

### 第一阶段：需求锚定与自动化工作空间
1. **任务**：使用 `ask-user` 获取信息。
2. **自动化初始化**：
    - 创建：`medical-solution/[ProjectName]_[YYYYMMDD]`。
    - 生成：`manifest.json`，用于显式跟踪文件链。

### 第二阶段：战略解构与深度检索
1. **分析逻辑**：采用“金字塔原理”解构需求。
2. **强制范式转移**：
    - **From**: Text-to-SQL (被动查询)。
    - **To**: **Text-to-Action (T2A)** (业务动作编排)。所有方案必须体现“推理中心化”和“业务闭环”。
3. **外部情报**：利用 `google_web_search` 检索国家标准及趋势。

### 第三阶段：规格与受众锚定
(保持 V2.6 逻辑，确认受众权重)

### 第四阶段：大纲构建与可视化协议 (Visual Structuring)
1. **任务**：构建具备逻辑深度的提纲。
2. **可视化强制 (Visual Protocol)**：
    - 在总体设计章节，**必须**包含一个 **Mermaid** 格式的架构图 (`graph TB` 或 `flowchart LR`)。
    - 架构图必须展示：物理层(HIS/EMR) -> 语义层(MSL) -> 推理层(AI Engines) -> 交互层(GenUI) 的层级关系。

### 第五阶段：原子化编写 (Chapter Production)
1. **知识挂载**：编写时必须读取 `references/` 下的 `medical_semantic_layer.md` 和 `hitl_grading.md`，确保术语准确。
2. **持久化**：同步更新 `manifest.json`。

### 第六阶段：确定性集成 (Deterministic Integration)
1. **任务**：执行 `python scripts/manifest_manager.py manifest.json [ProjectName]_v1_Draft.md`。

### 第七阶段：对抗式审计与任务追踪
1. **任务**：三维度审计（院长、CIO、科主任）。
2. **输出**：`[ProjectName]_Audit_Report.md` 和 `change_log.json`。

### 第八阶段：定稿优化与智能合规扫描
1. **任务**：根据 `change_log.json` 修复并重构。
2. **叙事化重塑**：融点成段，信息熵保全，视觉密度补偿。
3. **自动化校验**：
    - 执行 `python scripts/buzzword_auditor.py [ProjectName]_vFinal_Delivery.md`。
    - **Action**: 如果校验失败（Exit Code 1），读取 `audit_report.json`，根据建议自动替换违规词汇，直至通过。
4. **输出**：`[ProjectName]_vFinal_Delivery.md`。

## 3. 写作风格与负面清单 (V2.8)

### 顶级咨询文风
- **叙事优先**：用 Prose 取代 Bullet Points。
- **视觉表达**：用 Mermaid 图表取代枯燥的文字描述。

### 负面清单
- **严禁使用 `**` 加粗**。
- **严禁互联网黑话**：赋能、抓手、闭环、对齐等（Auditor 会自动拦截）。
- **严禁被动式 BI 思维**：必须升级为“主动式 AI 干预”。

## 4. 维护协议
- 脚本：`./scripts/` (含智能审计脚本)。
- 知识：`./references/` (必须包含 MSL 和 HITL 定义)。
