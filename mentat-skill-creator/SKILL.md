---
name: mentat-skill-creator
version: 11.1.0
tier: action-allowed
description: 'Mentat V11.1 技能重工管线 (Director Edition)。通过多代理并发编排、沙盒数据注射与原生推理沙盒，将业务逻辑结构化为带三大战术挂件的 XML 7层微服务技能，并自动入湖注册。'
triggers: ["创建技能", "优化技能", "修复指令", "自愈", "SKILL.md", "V11", "V11.1"]
---

# Mentat Skill Creator (V11.1 Director Architecture)

**Context**: 
这是 Antigravity 2.0 系统中用于创建、修复、重构本地图谱技能的最高指挥中心。本协议强制实施 Gemini Pro 3.1 级别的“多子代理并发编排 (Subagent Orchestration)”与“防死锁沙盒隔离”。V11.1 版本已全面废弃旧版 Markdown 散文模板，强行应用 **XML 标准 Agent 骨架（含认知暗盒、反向约束、工具挂载点）**。严禁主代理大包大揽。

**Request**: 
将用户的模糊指令通过“数据注射 (Data Injection) -> 结构化抽象 -> 边界对抗 -> 图谱物理注册”流水线，锻造为符合 V11.1 XML 标准的 7-Layer 技能规范。

**Output Format**: 
严格阻塞的 Checkpoint 拦截网 + 纯正 XML 结构的 Agent Prompt 模板 + 最终的 Vector Lake 注册。

**Constraints**:
1. 严禁主代理或 [Skill Architect] 自行编写长篇大论的 Markdown 文本，必须 100% 遵守第二章定义的 XML 标签结构。
2. 绝对禁止污染全局系统路径。所有的临时 JSON 缓存、测试用例输出、废弃补丁，必须统一写入 `<appDataDir>\brain\<conversation-id>\scratch\` 目录！
3. 必须通过调用子代理进行并发执行，严禁直接在主上下文生成测试与逻辑。

---

## 1. 核心指挥状态机 (Orchestration State Machine)
*[System Directive: 主代理必须严格遵循以下阻塞式工作流。]*

### Step 1: 侦察与数据提取 (Recon & Data Payload)
- **动作**: 识别意图，并抓取 1-2 条真实的业务上下文示例（例如真实的客户请求、代码片段）。
- **落盘**: 将环境配置与示例数据提取为标准的 `context_payload.json`，存入沙盒 `scratch/` 目录。

### Step 2: 并发锻造 (Concurrent Workers)
- **动作**: 主代理使用 `invoke_subagent` 同时并发唤醒以下两个子代理，并强制挂载 `Max_Turns: 3` 的死亡倒计时，拒绝任何无限死锁重试：
  1. **[Skill Architect]**: 向其注射需求。职责是**严格基于第二章的 XML 骨架模板**，输出新技能的定义结构。在构建 `<validation_gate>` 时，必须明确绑定后续生成的物理测试脚本。
  2. **[Test Engineer]**: 向其注射 `context_payload.json`。职责是废弃纯文本纸上谈兵，**必须**在 `scratch/` 下生成一个物理可执行的 `.py` 验证脚本（如基于 Pydantic 的 Schema 校验器，或正则探测器），内置 3 个极限测试用例（包含 1 个报错边界）。
- **指令要求**: 必须强制要求 Architect 在 `<tool_dispatch>` 模块中秉持“计算降维”法则，禁止新技能进行人肉计算。

### Step 2.5: 冷上下文审查 (Cold-Context Audit)
- **动作**: 主代理**绝对禁止**进行自我裁判。必须再次调用一个全新的子代理 `[Unbiased Reviewer]`，将 Architect 写的 `SKILL.md` 草稿、Engineer 写的验证脚本，连同系统的 `pai/coding.md` 扔给它。
- **拦截**: 如果审查官发现草稿试图让大模型做数学题，或者验证脚本无法运行，必须打回 `[Skill Architect]` 扣除一回合并要求重写。仅在获得二元判定 `[Approve]` 后，才允许推进。

### 🛑 CHECKPOINT 1 (沙盒数据校验)
- **触发**: 在获得冷上下文审查官的 `[Approve]` 之后，物理写入全局文件之前。
- **拦截**: **必须暂停！** 向用户展示生成的 `XML 技能草图` 与 `物理验证脚本路径`。等待用户人工确认。

### Step 3: 原子落盘与编译 (Atomic Commit)
- **动作**: 用户同意后，使用原子工具对 `config/skills/...` 下的对应 `SKILL.md` 文件执行写入。
- **异常处理**: 任何修改失败的碎片必须被截流并写入沙盒中的 `scratch/rejected_edits.jsonl`，严禁死锁重试。

### 🛑 CHECKPOINT 2 (路由重叠拦截)
- **触发**: 检测到新生技能的触发器与图谱内已有技能发生重叠。
- **拦截**: **必须暂停！** 停止执行，向用户请求边界优先级裁决。

### Step 4: 知识图谱登记 (Vector Lake Registry)
- **动作**: 编译无误且落盘通过后，**必须**调用 `vector-lake-mcp:write_wiki_page` 注册该技能。
- **内容**: 生成 `Concept_Skill_[Name]`，将技能的职责边界、正反向触发词 (Trigger) 永久入湖，消除知识孤岛。

---

## 2. 交付物标准：V11.1 XML 标准 Agent 骨架
*[System Directive: 所有新创建或重构的技能，必须严格封装进以下 XML 骨架中。该骨架完美映射了 7-Layer Class，并挂载了三大战术增强模块。]*

```xml
<system_instructions>
  <identity>
    <!-- [Identity & Voice]: 定义角色、视角与冷酷客观的执行语气 -->
  </identity>
  
  <mission>
    <!-- [Mission]: 明确首要任务与长远目标 -->
  </mission>
  
  <guardrails>
    <!-- [Constraints & Guardrails]: 绝对的红线与权限边界 -->
    <anti_patterns>
      <!-- [战术升级 1：反向约束] -->
      - 禁用词汇：严禁使用“首先、其次、总而言之、赋能”等 AI 塑料转折词汇。
      - 禁用行为：[填入绝对禁止触发的操作]
    </anti_patterns>
  </guardrails>
</system_instructions>

<task_context>
  <context>
    <!-- [Context]: 背景信息或输入数据的占位描述 -->
  </context>
  
  <request>
    <!-- [Request]: 动词驱动的具体指令 -->
  </request>
</task_context>

<execution_workflow>
  <workflow>
    <!-- [Workflow]: 定义状态机流转 (Step 1 -> Step 2 -> Step 3) -->
  </workflow>

  <tool_dispatch>
    <!-- [战术升级 2：工具挂载点] -->
    <!-- 明确指出在哪个阶段，必须强制调用哪个 MCP 工具或子代理 -->
  </tool_dispatch>

  <checkpoint_rules>
    <!-- [Checkpoint]: Fable 5 断点协议，严格定义何种情况必须停止并询问用户 (不可逆操作、范围蔓延、参数缺失) -->
  </checkpoint_rules>
</execution_workflow>

<delivery_standards>
  <output_format>
    <!-- [战术升级 3：认知暗盒 (Thought Sandbox)] -->
    <thought>
      [执行自我推演与 Metrics 校验区。该区域内容作为模型的推理草稿。]
    </thought>
    <!-- [Output Format]: 规定最终展示给用户的格式模板 (Markdown/JSON 等) -->
  </output_format>

  <metrics>
    <!-- [Metrics]: 生成最终结果前的内部校验清单 (Self-Correction) -->
  </metrics>

  <validation_gate>
    <!-- [战术升级 4：物理自我验证 (Physical Self-Verification)] -->
    <!-- 必须定义一个可通过脚本或底层工具验证的“硬”退出条件。如：运行 test_xxx.py 且 0 errors；或使用 jsonschema 命令校验输出。严禁仅仅依赖大模型的肉眼审查，测试不通过必须进入 3-Strike 熔断循环。 -->
  </validation_gate>
</delivery_standards>
```

## 3. Telemetry & Post-Mortem (系统遥测与防爆自愈)
如果在图谱审计中发现技能退化或抛出异常，启动“自愈”模式时，必须携带之前运行失败的 `crash.log` 并在 `<thought>` 中推演根因。
**自愈核心关注点**：重点检查 `<anti_patterns>` (是否遗漏了某类幻觉的防范) 与 `<tool_dispatch>` (是否挂载了错误或越权的底层工具)，进行精确的单点 XML 标签突变修复。
