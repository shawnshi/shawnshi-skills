---
name: document-summarizer
description: 批量总结 PDF/DOCX/PPTX/XLSX 文件，附带智能中文摘要和标签体系。
---

# Document Summarizer (Medical Intelligence Edition)

批量处理医疗信息化文档的战略情报引擎。具备本体驱动的摘要生成、合规性审计及战略盲区检测能力。

## Core Capabilities

*   **Intelligent Summarization**: 生成 100-150 字的高精度中文摘要，自动提取医院、厂商及核心指标。
*   **Compliance Audit**: 基于《电子病历评级标准》与《互联互通标准》自动检测文档合规性缺口。
*   **Strategic Tagging**: 生成 5 层级标签（领域 > 主题 > 核心技术 > 政策映射 > 战略价值）。
*   **Metadata Injection**: 将摘要与标签自动回写至文件属性（PDF/Office），实现系统级索引增强。

## Usage

### 1. 核心指令 (Auto-Orchestration)

当需要处理目录下的所有文档时，直接调用编排脚本。脚本会自动处理提取、分析、审计与回写全流程，并将产物存入 `output/`。

```bash
python scripts/orchestrate_enhanced.py all --dir <DOCUMENT_DIRECTORY>
```

### 2. 战略审计 (Strategic Audit)

若用户需要查看文档库的整体战略分布（如“这份资料库覆盖了哪些 2026 趋势？”），请查看生成的审计报告：

```bash
read_file output/STRATEGIC_AUDIT.md
```

### 3. 分步执行 (Advanced)

*   **仅提取文本**: `python scripts/orchestrate_enhanced.py extract --dir ...`
*   **仅生成摘要**: `python scripts/orchestrate_enhanced.py generate`
*   **仅回写元数据**: `python scripts/orchestrate_enhanced.py apply`
*   **清理过程文件**: `python scripts/orchestrate_enhanced.py clean`

## Artifacts (in `output/`)

*   `STRATEGIC_AUDIT.md`: **[High Value]** 战略组合审计报告，包含趋势盲区与行动建议。
*   `document_summaries_enhanced.json`: 结构化的摘要数据。
*   `compliance_analysis.json`: 逐文档的合规性评分详情。
*   `metadata_application.log`: 执行日志。

## Best Practices for Agents

1.  **路径感知**: 所有中间产物默认生成在 `output/` 目录下，不要在根目录寻找日志。
2.  **依赖检查**: 首次运行时，若报错 `ModuleNotFoundError`，请先运行 `pip install -r scripts/requirements.txt`。
3.  **大文件预警**: 对于超过 50MB 的 PDF，提取时间可能较长，请告知用户耐心等待。

## Troubleshooting

*   **Excel 回写失败**: 脚本已内置三层回退机制，若仍失败，通常是因为文件被其他程序占用（如 WPS/Excel 打开中）。
*   **中文乱码**: 脚本强制使用 UTF-8，若源文件名含特殊字符导致路径错误，脚本会自动跳过并记录在 `failures.json` 中。
