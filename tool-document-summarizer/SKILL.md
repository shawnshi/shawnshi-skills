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
   批量摘要必须根据本次受众和任务显式传入 `--max-chars`，不得依赖固定默认长度。
3. 对长文档按章节、页码或逻辑单元分片；记录每条结论对应的文件和位置。只有分片可以独立处理且并行能力可用时，才并行提取。
4. 按需要读取 `references/healthcare_ontology.json`，生成业务、技术、政策、合规和商业价值标签。不要把标签当作事实。
5. 汇总核心主张、证据、约束、数字、责任主体和时间条件。对多份文档标出一致、冲突和缺失。
6. `scripts/medical_standard_checker.py` 只定位术语及其文档证据，不判断合规、评级符合或政策价值；`scripts/portfolio_audit.py` 只生成描述性资产清单，不把未命中关键词写成战略盲区。
7. 抽样回看原文，验证数字、否定词、条件和引用位置。
8. 清理中间产物时先运行 `python scripts/orchestrate_enhanced.py clean` 查看候选；确认后才使用 `clean --apply`。

## Write-back

只有用户明确要求修改源文件元数据时，才运行 `scripts/apply_metadata_enhanced.py`。先不带 `--apply` 预览；确认目标文件、拟写字段和备份目录后，再提供 `--apply --backup-dir <dir>`。知识库同步同样需要单独授权。`orchestrate_enhanced.py all` 只执行提取、摘要、术语定位和资产清单，绝不自动写回源文件。

## Boundaries

- 不把专业文档摘要扩展成临床诊断或治疗建议。
- 摘要脚本默认使用本地抽取式方法。只有用户同意具体服务和数据范围后才加 `--allow-external-model --external-max-chars <范围>`；仅有环境变量不得触发外传。
- 提取失败、文件受保护或内容缺页时，报告缺口，不根据文件名补写。
- 临时文件放在当前任务的临时目录；最终文件写入用户指定或当前工作区。
- 脚本依赖见 `scripts/requirements.txt`，不得在未获授权时安装或升级依赖。

## Validation levels

- 硬错误：文件不存在或不可读、JSON/字段类型错误、来源 ID 缺失或重复、编号错误、显式长度或外传范围无效、输出写入失败。正文中的模板或代码示例不得仅因符号形态被阻断。
- 软提示：摘要较短、标签较少、章节可能重叠、关键词未命中、未出现数字、标题不够动作化。
- 人工判断：摘要是否忠实、方案逻辑、产品适配、合规结论、承诺风险和商业价值。关键词、字数、章节相似度和“是否有数字”不得作为发布阻断条件。

## Output

默认交付：

- 按用户目标和原文信息密度确定长度的执行摘要。
- 主题与证据标签。
- 关键数字、时间和责任主体。
- 冲突、缺失与风险。
- 来源位置清单。
