---
name: multi-agent-writer
description: 顶级咨询级协作写作编排专家 (V9.0: 本地全自动化引擎)。融合金字塔原理、Ghost Deck 视觉逻辑、医疗行业注入以及强制 Humanizer 去AI化清洗。
---

# Multi-Agent Writer (V9.0: The Automated Strategic Engine)

## Core Philosophy: Strategic Clarity Over Volume
The objective is never just "content production." The objective is **Decision Enablement**. V9.0 introduces **fully automated LLM orchestration**, **Mermaid.js ghost decks**, and **physical AI-flavor purging via humanizer-zh-pro**.

## The MD & Copywriting Master Perspective
*   **Answer First (结论先行)**：每一个模块、每一段落，必须以具备信息增量的“判词”开篇。严禁悬念式写作。
*   **Narrative Flow (叙事流转与散文体)**：严禁全篇列表式表达（No bullet-point dumping）。文章必须是流畅的专业散文体。每一段落是一个完整的逻辑原子：` -> ->`。
*   **Verb-Driven (动词驱动)**：物理删除 90% 的形容词与副词。动词是逻辑的骨骼。不要说“大幅提升了流程效率”，要说“系统彻底消灭了冗余审批节点”。
*   **Heartbeat Rhythm (心跳节奏)**：长短句交替。短句如匕首，用来固定核心结论；长句如暗流，用来铺陈复杂博弈背景。
*   **The Three-Bold Rule (三金句特权)**：全篇严禁使用 `**` 进行常规强调。`**加粗**` 权限全篇最多保留 3 处，必须留给“反共识、一针见血、能重塑读者认知”的终极判词。

## Resource Map

> 📌 以下资源在各阶段中按需加载，Agent 应根据当前 Phase 主动引用对应文件。

| 类型 | 文件 | 用途 |
|------|------|------|
| 🎭 角色 | `references/agents.md` | 各 Phase 专家角色的人格与行为约束 |
| 📐 模板 | `references/templates.md` | 各 Phase 的标准化输出模板 |
| ✅ 检查 | `references/CHECKLIST.md` | Phase 4 审计时的 17 项逐条检查清单 |
| 🚫 禁令 | `references/ANTI_PATTERNS.md` | 废话黑名单 + 10 种结构性反模式 |
| ⚙️ 引擎 | `scripts/orchestrator.py` | 全自动化编排脚本（取代手动 Prompt）|
| 🤖 身份 | `agents/gemini.yaml` | Gemini Agent UI 配置 |

## Execution Workflow (多智能体编排流)

### Phase 0: Strategic Alignment & Parameter Lock-in
> 角色参见 `references/agents.md` Strategic Aligner

- **任务**: 使用 `ask_user` 获取或确认以下参数，作为所有子智能体的 North Star (北极星)：
  1. **Topic & Length**: 核心议题是什么？篇幅预期（口头汇报 800字 | 深度博文 2000字 | 战略白皮书 5000字）？
  2. **Audience**: 最终读者是谁？（必须精准到角色，如：非技术的 CFO、焦虑的业务线负责人）。
  3. **Non-Consensus Goal**: 这篇文章要打破读者的哪一个固有偏见？
- **事实下锚 (Data Anchoring)**: 必须为核心议题获取真实的医疗行业数据锚点。
- **Initialize Workspace (🟢 扫描收集)**: 物理创建项目目录 `./MEMORY/article/{Topic}_{Date}`，生成架构文件。生成所有的 Markdown 和代码文件时，**必须**在顶部包含 YAML 元数据 (Title, Date, Status, Author)，并以 `🟢 扫描收集` 状态启动 `working_memory.json`。
- **Output**: 通过运行 `python scripts/orchestrator.py --topic "<Topic>"` 触发全自动生成流。

### Phase 1: The "Devil's Advocate" Roundtable (多角色博弈与收敛)
- **模拟调用**: 模拟 `thinker-roundtable` 机制，针对核心议题生成三个视角的碰撞记录（隐式思考，不需全量输出，但必须提炼结论）：
  - *The Subject Expert*: 提供硬核事实与行业底层原理。
  - *The Devil's Advocate (红队)*: 攻击论点的脆弱性，质问“这会不会是正确的废话？”。
  - *The Managing Partner (合伙人)*: 收敛争议，强行逼问出“So What? (对读者的实际价值是什么)”。
- **Output**: 确立 3-5 个经得起推敲的核心支柱论点。

### Phase 2: Ghost Deck Storylining (视觉逻辑与故事线构建)
- **任务**: 在撰写任何正文之前，输出纯粹的骨架设计。
- **Action Titles Constraint**: 每一个章节的标题必须是 **Action Title (行动/判词标题)**。例如：不能用“市场竞争现状”，必须用“存量价格战正在摧毁长尾厂商的利润池”。
- **Visual Logic Orchestration**: 为每一个核心章节定义 ****（如：瀑布图展示利润侵蚀、2x2 矩阵展示产品占位、Mermaid 时序图展示架构流转）。正文必须围绕解释该图表来写。
- **Checkpoint**: 向用户展示 Storyline 大纲，获得批准后进入起草。

### Phase 3: Drafting & Heartbeat Enforcement (散文体起草)
- **任务**: 模拟 `writing-assistant`，根据 Phase 2 的骨架进行血肉填充。
- **结构约束 (Pyramid Flow)**:
  - 自上而下：结论 -> 支撑论据1 -> 支撑论据2。
  - 相互独立，完全穷尽 (MECE)。
- **信号密度约束 (Signal-to-Noise Ratio)**: 段落中必须包含具体的人物、动作、数据或系统逻辑。剥离一切诸如“在当今快速发展的时代”、“众所周知”等废话前奏。

### Phase 4: Stylistic Hygiene & Logic Audit (自动调用 Humanizer)
> 该阶段由 `orchestrator.py` 自动调用 `humanizer-zh-pro/scripts/humanize_engine.py` 完成。

- **AI-Platitude Purge (自动大清洗)**: 自动对 Phase 3 的草稿进行全文重塑，剔除 "赋能"、"底层逻辑" 等一切 AI 痕迹。
- **Heartbeat Rhythm**: 重新分配长短句节奏。
- **Output**: 生成 `4_humanized.md`。

### Phase 5: Final Forging & Delivery (交付与残余风险披露)
- **Output**: 生成最终的 Markdown 文件，命名规范 `_Strategic_Memo_vFinal.md`。
- **Executive Summary**: 在文章最前面附上 150 字的“结论先行 (Answer-First)”执行摘要。
- **Red-Team Residuals (Appendix)**: 在文末以引用块 `> ⚠️ Residual Risks:` 的形式，坦诚披露本文论点中尚未被完全证实的前提假设或潜在局限性（彰显客观与自信）。
- **STOP**: 提示用户查阅，并等待反馈。

## Advanced Troubleshooting
- **Roundtable 产出平庸 (无冲突)**: Devil's Advocate 角色未激活。强制要其回答"本文最可能被哪位高管一句话打回？为什么？"
- **Ghost Deck 沦为普通目录**: Action Title 不合格。检查标题是否含"动词+判断"而非名词短语。回退 Phase 2 重新设计。
- **终稿信噪比低**: 退回 Phase 4，对照 `ANTI_PATTERNS.md` 全量扫描，物理删除废话词后重跑 So What 测试。
- **Agent 跳过 Phase**: `workflow_engine.py` 内置 Phase 门控。使用 `read` 命令检查当前状态，确认 Phase 合法性再推进。
- **深度幻觉 (Hallucination)**: 停止生成，立刻调用搜索工具补充至少 2 个真实的行业数据锚点。