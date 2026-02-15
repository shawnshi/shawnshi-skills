---
name: ai-daily-digest
description: "AI-powered strategic news aggregator utilizing native agent reasoning."
---

<!-- 
@Input: RSS URL list (hardcoded), CLI arguments (--hours)
@Output: Structured JSON data (--raw) or Comprehensive Markdown Report
@Pos: Skill Level - Strategic Intelligence Hub
-->

# AI Daily Digest (V2.0 - Native Logic Engine)

## 核心哲学
本技能不只是信息的搬运工，而是 **“逻辑编译器”** 的预处理器。它通过抓取 Karpathy 精选源，为 Agent 提供原始物料，最终生成具备“卫宁健康战略视角”的深度简报。

## 交互流程 (Native Processing Workflow)

### 1. 原始数据抓取
Agent 使用以下命令获取 JSON 原始数据：
```bash
npx -y bun ${SKILL_DIR}/scripts/digest.ts --hours <timeRange> --raw
```

### 2. 战略审计与评分 (Built-in Thought-Refiner)
Agent 必须调用内置推理能力，基于以下 **“战略支点”** 进行评分：
*   **MSL (医疗语义层)**: 是否涉及 T2A、意图映射、语义互操作性。
*   **ACE (智能体协调引擎)**: 是否涉及多智能体协同、慢思考推理、ACI。
*   **HITL (Human-in-the-Loop)**: 是否涉及认知摩擦、自动化偏见防御、责任归因。
*   **二阶护城河**: 是否涉及逻辑湖 (Logic Lake) 建设、意图流资产化。

### 3. 报告生成规范 (Writing-Assistant)
报告必须符合 `coding.md` 的美学与逻辑并重要求：
*   **标题**: 必须带上昨日/今日日期。
*   **分类**: 必须包含 [AI/ML]、[架构/工程]、[战略/观点]。
*   **内容**: 每篇文章必须提供 **【中文摘要】**（3-5句深度拆解）与 **【推荐理由】**（阐述其对用户 2026 年度战役的参考价值）。

### 4. 强制存档 (Hard Archive)
Agent **必须** 将生成的 Markdown 报告保存至以下本地路径，不得仅在终端显示：
`C:\Users\shich\.gemini\news\digest_$(date +%Y%m%d).md`

这是构建个人“逻辑湖”的核心动作，确保所有战略简报均被持久化。

---

## 脚本目录
*   `scripts/digest.ts`: 高并发数据采集器，支持 `--raw` 模式。

## 环境要求
*   `bun` 运行时。
*   网络环境（需能访问全球 RSS 源）。
