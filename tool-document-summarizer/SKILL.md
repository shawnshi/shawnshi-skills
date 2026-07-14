---
name: tool-document-summarizer
description: 提取医疗信息化、商业方案、招标材料和政策文件的结构化摘要与标签。当用户要求总结专业文档、提取 PDF 核心要点、比较多份医疗材料或生成证据可追溯的文档简报时使用。
---

# Professional Document Summarizer

## Procedure

1. 确认输入文件、目标受众、摘要长度、比较范围，以及任务是否只读。默认只读。
2. 按文件类型使用当前可用的文档或 PDF 能力提取内容。需要确定性批处理时，可使用：
   - `scripts/extract_text.py`
   - `scripts/orchestrate_enhanced.py`
3. 对长文档按章节、页码或逻辑单元分片；记录每条结论对应的文件和位置。只有分片可以独立处理且并行能力可用时，才并行提取。
4. 按需要读取 `references/healthcare_ontology.json`，生成业务、技术、政策、合规和商业价值标签。不要把标签当作事实。
5. 汇总核心主张、证据、约束、数字、责任主体和时间条件。对多份文档标出一致、冲突和缺失。
6. 使用 `scripts/medical_standard_checker.py` 检查医疗术语，必要时使用 `scripts/portfolio_audit.py` 做跨文档核验。
7. 抽样回看原文，验证数字、否定词、条件和引用位置。
8. 清理中间产物时先运行 `python scripts/orchestrate_enhanced.py clean` 查看候选；确认后才使用 `clean --apply`。

## Write-back

只有用户明确要求修改源文件元数据时，才运行 `scripts/apply_metadata_enhanced.py`。执行前展示目标文件、拟写字段和备份方案。知识库同步同样需要单独授权。

## Boundaries

- 不把专业文档摘要扩展成临床诊断或治疗建议。
- 脚本若把文档内容发送到外部模型，必须先说明服务、数据范围并取得授权；机密或个人数据默认不外传。
- 提取失败、文件受保护或内容缺页时，报告缺口，不根据文件名补写。
- 临时文件放在当前任务的临时目录；最终文件写入用户指定或当前工作区。
- 脚本依赖见 `scripts/requirements.txt`，不得在未获授权时安装或升级依赖。

## Output

默认交付：

- 100–200 字执行摘要。
- 主题与证据标签。
- 关键数字、时间和责任主体。
- 冲突、缺失与风险。
- 来源位置清单。
