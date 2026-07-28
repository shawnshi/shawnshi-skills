# /morphism-add-domain

创建新的领域参考文件属于持久化变更。

## 流程

1. 收集小写英文标识、显示名称、可核验来源和结构原语。
2. 先运行预览：

   `python scripts/domain_manager.py add <name> --source "<source>" --primitives "<objects, relations, constraints>"`

3. 检查预览中的来源、对象、关系、机制、适用条件、反例和标签。
4. 只有用户明确授权写入后，原命令增加 `--apply`；这只创建
   `references/drafts/<name>.md`，不会进入活动路由。
5. 补全草稿的对象、关系、机制、前提、反例和来源；不得保留待填字段。
6. 独立核验后运行 `python scripts/domain_manager.py promote <name>` 预览目标路径、
   来源、SHA-256 和 allowlist 条目。
7. 只有用户明确授权激活后才增加 `--apply`。该命令以同一操作把草稿移动到
   `references/verified` 并更新 allowlist；随后运行 `domain_manager.py list`
   必须通过。
8. 返回实际路径、活动状态并核对文件可读。

## 验证

- 硬错误：名称非法、来源或结构原语缺失、来源仍为待定值、名称或路径重复、
  领域必需字段未补全、文件已存在、SHA 不一致或写入失败。
- 软提示：对象、关系或机制较少，标签不足，章节结构与旧文件不同。
- 人工判断：来源是否可靠、机制是否准确、领域是否值得持久化。

不要求固定数量的基石、对象、关系或定理，也不以固定字数或特定语气作为
发布门禁。
