---
name: tencent-meeting-mcp
description: '腾讯会议智能助手，支持会议管理、成员管理、录制、转写与智能纪要查询等功能。'
---

<strategy-gene>
Keywords: Tencent Meeting, MCP, tmeet, CLI, Meeting Management, Smart Minutes
Summary: 腾讯会议官方整合中枢，支持通过 tmeet CLI 与底层 MCP 协议管理会议生命周期。内置 OAuth2 安全鉴权、V1.0.5+ 标准分页范式及智能纪要提取管线。
Strategy:
1. 1. 时间锚定：处理时间需求时，必须以 Asia/Shanghai 为基准转换时间戳，禁止模型凭空推测系统时间。
2. 2. 分页迁移：全面采用 --page-token 与 --page-size 的现代游标分页模式，弃用传统的 pos/limit 偏移量模式。
3. 3. 破坏性操作门控：创建、更新或取消会议等写操作前，必须拦截并向用户输出关键要素（如时间、主题）进行二次确认。
4. 4. 内容提取优先级：当用户询问会议讲了什么时，严格遵循：智能纪要 (smart-minutes) > 转写详情 (transcript) > 录制文件下载 (record address) 的下行回退链。
AVOID: 禁止在未经用户二次确认前取消或修改会议；禁止在分页遍历中陷入死循环死锁；禁止保留 300 行以上的无意义说明书冗余。
</strategy-gene>

# 腾讯会议全景智能管线 (Tencent Meeting CLI / MCP)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. 执行 `tmeet auth status` 确认本地凭证处于就绪态
2. 捕获用户请求实体（时间、会议号、参与人范围）
3. 若涉时间推断，经由标准化时间引擎或 CLI 本地校验计算出精确 ISO8601 或 Unix 戳
4. 经由 `tmeet` 命令树（如 `meeting list`, `record smart-minutes`）发起安全调用
5. 对分页响应（如 next_page_token）进行循环组装
6. 洗脱冗余 JSON，仅交付核心结论（如智能摘要文本或会议日程）

## 运行资产与鉴权网关
推荐使用 `@tencentcloud/tmeet` 命令行载体。
- **设备鉴权**：执行 `tmeet auth login`。无桌面环境时追加 `--no-browser`。Token 采用 AES-256-GCM 物理落地加密。
- **全局参数**：推荐在代理检索时附带 `--compact` 截断噪音；数据层交互强制指定 `--format json`。

## 生命周期与录制控制 (Command Tree)
**会议调度**：
- `tmeet meeting create`（可配置 `--recurring-type` 创建周期会议，`--waiting-room` 开启等候室）
- `tmeet meeting list` / `list-ended` 分别查询进行中与历史快照。

**内容提纯**：
- `tmeet record smart-minutes`：直击会议灵魂的智能纪要生成。
- `tmeet record transcript-search`：对转写底稿执行精确的字符级检索。

## 游标分页协议 (V1.0.5+)
自 `v1.0.5` 起，全面弃用 `--pos`、`--page` 等参数：
1. 首轮请求不携带 Token。
2. 截取响应体中的 `next_page_token`，挂载于下一轮的 `--page-token` 参数中。
3. 当 `next_page_token` 返回空字符串时，表示游标触底，终止遍历。
默认 `--page-size` 通常为 20-30，可根据流控进行限流微调。
