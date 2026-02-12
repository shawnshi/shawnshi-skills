# document-summarizer
<!-- Input: Batch PDF/DOCX/PPTX/XLSX files. -->
<!-- Output: Strategic Chinese summaries, tags, and compliance scores. -->
<!-- Pos: Cognitive Layer (Strategic Audit). -->
<!-- Maintenance Protocol: Update 'scripts/orchestrate_enhanced.py' for new schema versions. -->

## 核心功能
医疗信息化领域的战略情报引擎。具备本体驱动的摘要生成能力，能自动执行《电子病历评级标准》等合规性缺口检测。

## 战略契约
1. **本体优先**: 摘要生成必须引用医疗本体库（如 SNOMED-CT 映射）。
2. **审计闭环**: 必须生成 `STRATEGIC_AUDIT.md`，提供趋势盲区分析与行动建议，而非简单的内容罗列。
3. **元数据回写**: 分析产物必须回写至文件属性，实现系统级索引增强。
