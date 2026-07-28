# /morphism-config

## list

运行 `python scripts/domain_manager.py list`。只返回
`references/verified_domains.json` 中来源完整且 SHA-256 匹配的活动领域。
需要审计隔离资产时可以增加 `--include-quarantined`；隔离列表不可用于映射。

## add-domain

按照 [add-domain.md](add-domain.md) 先预览、再经授权创建非活动草稿。草稿
不会覆盖同名领域，也不会自动进入 allowlist。

## validate

`domain_manager.py list` 的确定性硬检查包括：

- allowlist Schema 和必需字段；
- 路径必须位于本技能 `references` 边界内；
- 文件存在、可读且 SHA-256 匹配；
- 来源字段非空。

章节数量、字数、标签数量、案例丰富度和措辞只做软提示；机制正确性、来源
质量和映射价值由人工判断。
