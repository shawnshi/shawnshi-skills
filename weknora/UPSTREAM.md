# UPSTREAM

上游来源与本副本差异记录。维护本目录时先读本文件，避免把本地护栏当成上游内容。

## Source

- Registry: ClawHub (`https://clawhub.ai/lyingbug/skills/weknora`)
- Publisher: `lyingbug`
- Version: `1.0.1` (published 2026-06-30, upstream changelog: added `_meta.json`)
- Bundle download: `GET https://clawhub.ai/api/v1/download?slug=weknora` → `weknora-1.0.1.zip`
- Bundle `sha256`: `9bcf52b705a9dbeb520f057517d6bc9e79df70e908f60a4a71d4748f79568a27`
- Bundle contents: `SKILL.md`, `_meta.json`, `skill-card.md`
- Upstream `SKILL.md` `sha256`: `a41fa279b09e4fde83365e002cebd75a8560dc29b91b5f1db787e42bc70d7203`
- Installed `SKILL.md` `sha256`: `b5c9fadaa25f7afe0f4a6a7c9291710753f9ad9ab0dd43bc56e3e27e5b7517bd`
- Local install date: 2026-09-16
- Local install target: Pi 本地技能库 `weknora/`（相对技能库根目录）

## Local deltas

本副本相对上游 v1.0.1 只有三处差异，其余正文按字节保留。去掉下列差异后，`SKILL.md` 正文哈希与上游一致（`e42668d2815fefd27bbce9db8c7123c65e36254f6b8f101aa9fb90daf2e114fc`，仅对正文段计算，不含 frontmatter）。

1. **frontmatter 归一化**：上游 `description` 使用 YAML 折叠块（`>` + 多行），本地改为单行双引号字符串，文本内容与上游完全一致（366 字符），以满足本地技能库门禁按行解析 frontmatter 的规则。
2. **frontmatter `metadata` 改写**：上游为 `{"openclaw": {"requires": {"env": [...]}}}`，本地改为 `{"source": "clawhub", "publisher": "lyingbug", "version": "1.0.1"}`。原因是本地运行时并不消费 `openclaw` 键；所需环境变量改由正文 Setup 与本地护栏声明。
3. **追加本地安全护栏**：`SKILL.md` 末尾新增「本地安全护栏（Pi 本地安装附加，非上游内容」一节，针对删除/编辑确认、写入落点、凭据处理、内容外发、失败重试和证据边界给出本地约束。上游正文未包含这些边界。

新增文件：`UPSTREAM.md`（本文件）与 `resource-manifest.json`（由本地技能库脚本 `scripts/generate_resource_manifests.ps1` 生成，schema v3，不属于上游 bundle）。上游附加的 `_meta.json` 与 `skill-card.md` 原样保留，未修改。

## Registry scan at install time

`GET /api/v1/skills/weknora/scan`，查询于 2026-09-16：

- 综合判定：`suspicious`，`hasWarnings: true`
- VirusTotal：`clean`
- SkillSpector：`suspicious`，score 51，severity `HIGH`，建议 `DO_NOT_INSTALL`，5 项问题
- 语义审查：`suspicious`（confidence high）；摘要指出该技能基本是 WeKnora API 指南，但低估了编辑与删除权限，且缺少相应护栏
- 具体问题：正文列出 `DELETE /knowledge/:id` 但未要求确认目标、未提示可能不可逆；`metadata` 侧描述偏导入与检索，正文却包含编辑与删除；建议把凭据写入 shell 启动文件且未强制 HTTPS
- 未发现可执行文件、持久化驻留、后门或权限提升；怀疑点集中在指令范围与凭据处理，不是恶意代码

本地护栏第 1、3、4 条即对应上述第 1、3 项问题；`metadata` 侧描述与正文范围差异作为已知偏差保留，不通过改写上游正文消除。

## Update procedure

1. 重新下载目标版本的 bundle 并核对 `sha256`，记录新的上游哈希。
2. 对照本文件的三处差异重新施加，不整文件覆盖，避免丢掉本地护栏。
3. 运行资源清单生成脚本，仅在检查通过后刷新 `resource-manifest.json`。
4. 复核 registry 扫描结论与本次差异是否仍成立，更新本文件对应字段与日期。

## Local validation (2026-09-16)

- 资源清单：`scripts/generate_resource_manifests.ps1 -Root . -IncludeSkills weknora -Check` → checked 1，stale 0。
- 限定范围门禁：`scripts/repair_skills.ps1 -Mode Gate -Root . -IncludeSkills weknora` → frontmatter 失败 0、清单缺失 0、清单无效 0、行数超限 0、触发所有权冲突 0。唯一非零项 `ValidatorIntegrationFailures: 1`，原因是技能库缺少 `scripts/validate_openai_yaml.py`；安装前后同为 1，与本次安装无关。
- 全库 Audit 安装前后对比：仅新增本技能一行（189 行、frontmatter 合法、清单存在）与库存数 51 → 52；其余阻断项计数不变（清单缺失 50、frontmatter 失败 5 均为既有状态）。
- 新会话探测：临时 Pi 会话读取可用技能列表时能列出 `weknora`。
- 未验证：未调用任何 WeKnora 端点，端到端导入与检索行为未测试；本技能的自动路由选择未验证。
