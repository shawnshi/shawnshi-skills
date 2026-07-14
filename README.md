# Codex Skills Library

本目录是 Codex 用户技能库。本文档是本库结构、运行边界、门禁和维护流程的权威说明。门禁与本文档冲突时，以本文档为准，并修订门禁实现；不得通过修改 README 掩盖真实缺陷。

## Current baseline

基线日期：2026-07-14。

| 项目 | 当前状态 |
|---|---:|
| 一级用户技能 | 49 |
| `resource-manifest.json` | 49 |
| `skill.json` | 0 |
| `node_modules` | 0 |
| 旧 `gemini.yaml` | 0 |
| 旧 `_DIR_META.md` | 0 |
| Codex 技能校验 | 49/49 |
| 根门禁 | 通过 |
| 单元测试 | 54/54 |

最近一次静态验证覆盖：111 个 Python 文件、87 个标准 JSON 文件、7 个 YAML 文件、7 个 JavaScript 文件、18 个 TypeScript 文件和 4 个 PowerShell 文件。上述数字是带日期的验证快照，不替代当前任务重新运行门禁。

## 1. Runtime contract

- Codex 只以每个技能目录中的 `SKILL.md` 作为运行真相源。
- 不创建、不读取、不生成 `skill.json`。
- 每个技能聚焦一个可描述、可触发、可验证的工作。
- 仓库级规则写在 `AGENTS.md`；技能只保留可复用的专业流程。
- 外部系统能力由真实工具、插件或 MCP 提供。技能不得用散文虚构工具接口。

## 2. Required shape

根目录结构：

```text
skills/
├── <skill-name>/           # 一级用户技能
├── .system/                # Codex 内置技能，不计入用户技能库存
├── scripts/                # 本库门禁、资源索引和共享校验脚本
├── shared/                 # 跨技能协议、Schema 与触发所有权矩阵
├── examples/               # 共享校验样例
└── README.md               # 本文件，库级合同
```

每个一级技能目录必须包含：

```text
skill-name/
├── SKILL.md
├── agents/openai.yaml       # 可选：界面元数据或外部能力声明
├── scripts/                 # 可选：确定性、可重复执行的脚本
├── references/              # 可选：按需读取的领域资料
├── assets/                  # 可选：生成产物使用的模板和素材
└── resource-manifest.json   # 本库门禁使用的资源索引
```

`SKILL.md` 的 frontmatter 只能包含：

```yaml
---
name: skill-name
description: 说明技能做什么，以及用户在什么场景下应使用它。
---
```

约束：

- `name` 必须与目录名一致，只使用小写字母、数字和单连字符，长度不超过 64。
- `description` 必须同时写明能力和触发场景，长度为 1–1024 个字符。
- 不在 frontmatter 中加入 `version`、`tier`、`triggers`、`allowed-tools` 或运行时私有字段。
- 正文使用命令式步骤，写清输入、处理、输出、验证和失败处理。
- 不强制固定章节名。门禁不得因为缺少 `When to Use`、`Workflow`、`Telemetry` 等标题而失败。
- `SKILL.md` 不超过 500 行；大段模板、规范和示例放入 `references/`。
- 所有技能内资源使用相对技能目录的路径引用，避免深层引用链。

## 3. Execution boundaries

- 不要求输出 `<thought>`、`<Thinking>` 或其他内部推理稿。以证据、假设、验证结果和残余风险替代。
- 不硬编码用户目录、`.gemini`、`.kimi`、会话 ID 或 `file:///` 链接。
- 不写入当前 Codex 不存在的工具名。通过自然语言描述所需能力，或在 `agents/openai.yaml` 中声明真实依赖。
- 子代理只在任务可以独立拆分且并行能力可用时采用；必须保留单代理降级路径。
- 联网、安装依赖、控制外部应用、发送消息、发布、合并、删除和永久写入都属于显式授权分支。
- 临时文件放入当前任务可写的临时目录；最终产物写入用户指定或当前工作区的输出位置。
- Vector Lake、MEMORY、日志和用户偏好不默认写入。只有用户明确要求保存或同步时才执行。
- 处理医疗、金融、隐私、凭据和个人数据时，声明数据来源、适用范围、不确定性和升级条件。
- 不承诺 100% 成功、零错误或无法验证的效果。

## 4. Resource and dependency rules

- 优先使用现有脚本；新增脚本必须实际运行代表性测试。
- 外部命令、操作系统、浏览器、桌面应用、Python/Node 包和凭据要求必须在正文的依赖或边界部分写明。
- 不提交 `node_modules`、缓存、日志、临时下载、测试输出或生成音频。
- 不把同一说明同时复制到 `SKILL.md` 和 `references/`。
- `resource-manifest.json` 只记录资源与引用状态，不定义技能语义。

## 5. Skill inventory

当前库存为 49 个用户技能，不包含 `.system`、`scripts`、`shared`、`examples` 和 `reports`。

### Academic and cognitive research

- `academic-paper-reader`
- `academic-scientific-visualization`
- `automate-github-issues`
- `cognitive-book-mirror`
- `cognitive-ceo-review`
- `cognitive-deep-reader`
- `cognitive-hv-analysis`
- `cognitive-ideation-brainstorming`
- `cognitive-logic-adversary`
- `cognitive-morphism-mapper`
- `cognitive-personal-roundtable`
- `cognitive-storm-research`

### Healthcare strategy

- `hit-customer-analyst`
- `hit-digital-strategy-partner`
- `hit-industry-radar`
- `hit-lectures-scout`
- `hit-solution-architect`
- `hit-weekly-brief`

### Image and system workflows

- `image-promp-gen`
- `image-studio-architect`
- `mentat-collaboration-audit`
- `mentat-dream-cycle`
- `mentat-insight-diary`
- `mentat-skill-creator`

### Personal workflows

- `personal-cognitive-auditor`
- `personal-cognitive-prescription`
- `personal-diary-writer`
- `personal-health-analysis`
- `personal-intelligence-hub`
- `personal-investment-advisor`
- `personal-musicbee-dj`
- `personal-travel-research`
- `personal-write-humanizer`
- `personal-writing-assistant`

### Meetings and utility workflows

- `tencent-meeting-mcp`
- `tool-archive-crawler`
- `tool-blogger-publisher`
- `tool-concept-synthesis`
- `tool-document-summarizer`
- `tool-drawio`
- `tool-markdown-converter`
- `tool-slide-architect`
- `tool-smart-latex`
- `tool-text-forger`
- `tool-tts`
- `tool-tuanbiao-downloader`
- `tool-url-markdown`
- `tool-web-slide`
- `tool-youtube-summary`

## 6. Trigger ownership

相近技能按产物区分：

- 原创长文：`personal-writing-assistant`
- 忠实润色：`tool-text-forger`
- 去机器腔：`personal-write-humanizer`
- 演示文稿蓝图：`tool-slide-architect`
- 单页网页演示：`tool-web-slide`
- 位图提示词：`image-promp-gen`
- 位图生成或编辑：`image-studio-architect`
- 系统结构图：`tool-drawio`
- 单篇论文：`academic-paper-reader`
- 多源横纵研究：`cognitive-hv-analysis`
- 多视角证据研究：`cognitive-storm-research`
- 医疗文档摘要：`tool-document-summarizer`
- 通用文件转 Markdown：`tool-markdown-converter`

详细所有权由 `shared/trigger-ownership-matrix.json` 维护；其中引用的技能必须真实存在。

## 7. Gate

刷新资源索引：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/generate_resource_manifests.ps1 -Root .
```

运行阻断门禁：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/repair_skills.ps1 -Mode Gate -Root .
```

脚本还支持：

- `-Mode Audit`：只输出检查结果，不写报告。
- `-Mode Report`：在报告目录生成 `skills-audit.json`。
- `-Mode Gate`：发现任一阻断项时返回非零退出码。

门禁必须检查：

- 一级用户技能数与 README 库存一致。
- frontmatter 仅含 `name` 和 `description`。
- 名称、描述、行数和本地引用有效。
- 每个用户技能存在 `resource-manifest.json`，且没有缺失依赖。
- 不存在 `skill.json`。
- 对 `SKILL.md`、脚本、参考资料、配置和界面元数据执行一致检查；不存在旧运行时工具令牌、外部运行时路径、思维稿指令、硬编码模型版本、强制子代理或强制持久化。
- 触发所有权矩阵不存在未知技能和重复信号。

关键失败必须返回非零退出码；报告模式不得代替门禁。

## 8. Maintenance sequence

1. 读取目标技能及其直接引用资源。
2. 以小批次修改 `SKILL.md` 和必要资源。
3. 运行代表性脚本或静态验证。
4. 运行 `scripts/generate_resource_manifests.ps1` 刷新资源索引。
5. 运行 Gate。
6. 对修改过的脚本运行语法检查、代表性正向测试和相关单元测试。
7. 只有验证结果真实变化时，才同步本 README 的库存和基线数字。

禁止在维护流程中重新生成 `skill.json`。旧工具如果仍依赖该文件，应修订或移除该工具，不得恢复双重真相源。

Last updated: 2026-07-14
