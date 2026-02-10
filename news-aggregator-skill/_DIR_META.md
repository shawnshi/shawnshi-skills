# _DIR_META.md

## Architecture Vision
全球新闻情报枢纽 (The Intelligence Hub)。
实时采集、过滤并深度解析 8 大主流渠道（HN, GitHub, 36Kr, etc.）的高价值信息。通过“二阶洞察”将原始动态转化为具备战略参考价值的简报。

## Member Index
- `SKILL.md`: [Manifest] 核心工作流 SOP、触发词与 Fetch 策略。
- `scripts/`: [Engine]
  - `fetch_news.py`: 核心采集引擎（支持 Deep Fetch）。
- `reports/`: [Archive] 存放生成的历史情报简报。
- `references/`: [Knowledge]
  - `menu.md`: 快捷指令菜单定义。
  - `responses.md`: 情报输出格式规范。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 每次 Fetch 结束后，必须将结果异步存档至 `reports/`。
