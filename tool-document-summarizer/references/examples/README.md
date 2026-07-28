# Document Summarizer 示例

`sample_input.json` 与 `sample_output.json` 是合成数据，仅用于说明字段；其中
的机构、产品、预算、评级和性能数字都不是业务事实，也不得迁入正式报告。
`sample_output.json` 保留为旧版格式示例，当前脚本的真实 Schema 以运行结果
和 `SKILL.md` 为准。

## 默认只读流程

```text
python scripts/orchestrate_enhanced.py all \
  --dir <documents> \
  --output-dir <scratch-output>
```

该命令只生成：

- `extracted_content.json`
- `file_id_mapping.json`
- `document_summaries.json`
- `term_locations.json`
- `portfolio_inventory.json`

它不会修改源文档。外部模型只有在用户已授权具体服务和数据范围后，才使用
`--allow-external-model`；环境变量本身不会触发外传。

## 元数据写回

先预览：

```text
python scripts/orchestrate_enhanced.py apply \
  --summaries <summaries.json> \
  --mapping <mapping.json>
```

用户确认目标、字段和备份位置后，才执行：

```text
python scripts/orchestrate_enhanced.py apply \
  --summaries <summaries.json> \
  --mapping <mapping.json> \
  --apply \
  --backup-dir <backup-dir>
```

已有元数据默认阻断覆盖；确需覆盖时另加 `--overwrite-existing`。

## 解释边界

- 术语命中只定位文本，不证明评级符合、政策价值或合规性。
- 未命中关键词不证明存在战略或能力缺口。
- 摘要长度、标签数量和标题风格是软提示，不是发布门禁。
- 提取读错、来源 ID 重复、字段类型错误和缺失映射会阻断流水线；正文中的
  模板或代码示例不得仅因符号形态被判错。
