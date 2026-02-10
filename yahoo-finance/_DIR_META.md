# _DIR_META.md

## Architecture Vision
提供确定性、结构化的全球金融市场数据访问。
作为 Gemini 的“语义金融层”，将自然语言查询（如公司名）转化为精确的代码与数据，支持历史趋势分析、基本面核查及新闻聚合。

## Member Index
- `SKILL.md`: [Required] 技能核心指令、触发逻辑及 Agent 最佳实践。
- `scripts/`: [Bundled Resources] 存放确定性执行脚本。
  - `yf.py`: 基于 yfinance 的核心数据提取引擎。
- `agents/`: [Recommended] 存放 UI 元数据及 IDE 交互配置。
  - `gemini.yaml`: UI 适配与提示词配置。

> ⚠️ **Protocol**: 当 API 架构、依赖项（yfinance）或脚本路径变更时，必须同步更新此文件。
