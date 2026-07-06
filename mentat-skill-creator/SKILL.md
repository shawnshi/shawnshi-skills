---
name: mentat-skill-creator
version: 11.0.0
tier: action-allowed
description: 'Mentat V11 技能重工管线 (Director Edition)。通过多代理并发编排、沙盒数据注射与原生推理沙盒，将业务逻辑结构化为 7层微服务技能，并自动入湖注册。'
triggers: ["创建技能", "优化技能", "修复指令", "自愈", "SKILL.md", "V11"]
---

# Mentat Skill Creator (V11 Director Architecture)

**Context**: 
这是 Antigravity 2.0 系统中用于创建、修复、重构本地图谱技能的最高指挥中心。本协议强制实施 Gemini Pro 3.1 级别的“多子代理并发编排 (Subagent Orchestration)”与“防死锁沙盒隔离”。严禁主代理大包大揽。

**Request**: 
将用户的模糊指令通过“数据注射 (Data Injection) -> 结构化抽象 -> 边界对抗 -> 图谱物理注册”流水线，锻造为符合 7-Layer 标准的 V11 技能。

**Output Format**: 
严格阻塞的 Checkpoint 拦截网 + 最终的 Vector Lake 注册。

**Constraints**:
1. 严禁主代理自行编写长篇大论的 Markdown 文本。
2. 绝对禁止污染全局系统路径。所有的临时 JSON 缓存、测试用例输出、废弃补丁，必须统一写入 `<appDataDir>\brain\<conversation-id>\scratch\` 目录！
3. 必须通过调用子代理进行并发执行，严禁直接在主上下文生成测试与逻辑。

---

## 1. 核心指挥状态机 (Orchestration State Machine)
*[System Directive: 主代理必须严格遵循以下阻塞式工作流。]*

### Step 1: 侦察与数据提取 (Recon & Data Payload)
- **动作**: 识别意图，并抓取 1-2 条真实的业务上下文示例（例如真实的客户请求、代码片段）。
- **落盘**: 将环境配置与示例数据提取为标准的 `context_payload.json`，存入沙盒 `scratch/` 目录。

### Step 2: 并发锻造 (Concurrent Workers)
- **动作**: 主代理使用 `invoke_subagent` 同时并发唤醒以下两个子代理：
  1. **[Skill Architect]**: 向其注射需求。职责是设计符合“7层微服务类定义”的 `skill.json` 草图。
  2. **[Red Team Evaluator]**: 向其注射 `context_payload.json`。职责是基于真实数据，设计 3 个极限测试用例（包含 1 个必然触发拒绝的边界）。
- **指令要求**: 必须强制要求 Red Team 在生成 JSON 测试用例前，使用 `<thought>` 块进行红蓝对抗自我博弈 (Self-Debate)，排查漏洞。

### 🛑 CHECKPOINT 1 (沙盒数据校验)
- **触发**: 在收到所有子代理返回的数据之后，但在物理写入任何全局文件之前。
- **拦截**: **必须暂停！** 向用户展示 `skill.json` 草图与 `3 个红队测试用例`。等待用户人工确认。

### Step 3: 原子落盘与编译 (Atomic Commit)
- **动作**: 用户同意后，使用原子工具对 `config/skills/...` 下的文件执行写入。
- **动作**: 执行 `$env:PYTHONIOENCODING="utf-8"; python scripts/render_skill.py skill.json`。
- **异常处理**: 任何修改失败的碎片必须被截流并写入沙盒中的 `scratch/rejected_edits.jsonl`，严禁死锁重试。

### 🛑 CHECKPOINT 2 (路由重叠拦截)
- **触发**: 检测到新生技能的触发器与图谱内已有技能发生重叠。
- **拦截**: **必须暂停！** 停止执行，向用户请求边界优先级裁决。

### Step 4: 知识图谱登记 (Vector Lake Registry)
- **动作**: 编译无误且测试通过后，**必须**调用 `vector-lake-mcp:write_wiki_page` 注册该技能。
- **内容**: 生成 `Concept_Skill_[Name]`，将技能的职责边界、正反向触发词 (Trigger) 永久入湖，消除知识孤岛。

---

## 2. 交付物标准：V11 7-Layer Class Definition
所有生成的 `skill.json` 最终被渲染成的 `SKILL.md`，必须符合以下七层契约：

1. **Identity (身份)**: 技能核心定义（V11 标识）。
2. **Mission (目标)**: Frontmatter 中的 `description` 强制 <50 字，且包含明确的反向阻断条件。
3. **Workflow (工作流)**: 摒弃模糊的过程描述，使用 Milestone 与 JSON RPC 契约定义流水线。
4. **Deliverables (交付物)**: 限定最终交付物是 UserFacing Artifact 还是特定结构文件。
5. **Guardrails (护栏)**: 以绝对的 `Constraints` (约束) 替代大写的呼喊。业务逻辑溢出部分必须强制智能左移至 `scripts/` 脚本目录。
6. **Metrics (指标)**: 客观的静态门禁条件与失败分类学。
7. **Voice (语气)**: 维持 Winston 式的极致精干、非客服体控制台语言。

## 3. Telemetry & Post-Mortem
如果在图谱审计中发现技能退化，启动“自愈”模式时，必须携带之前运行失败的 `crash.log` 并在 `<thought>` 中推演根因，进行精确单点基因突变。
