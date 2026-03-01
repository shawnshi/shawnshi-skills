# _DIR_META.md

## Architecture Vision
战略思想工厂 (Strategic Thought Factory)。
通过"逻辑-灵魂-校验"的三阶流水线，将原始信息加工为具有穿透力的深度文章。

## Member Index
- `SKILL.md`: [Manifest] 核心工作流定义（唯一入口，V4.1）。
- `scripts/assistant.py`: [Engine] 上下文组装引擎，负责聚合策略、模板与反模式库。
- `metrics/quality_scoring.py`: [Engine] 量化质量评分器（依赖 jieba）。
- `requirements.txt`: [Config] Python 依赖声明。
- `references/`: [Knowledge] 写作规范、检查清单、反模式库与评估体系。
  - `GUIDELINES.md`: 深潜推演与灵魂合成的详细指导（SKILL.md 的参考扩展）。
  - `CHECKLIST.md`: 30+ 项质控检查清单。
  - `ANTI_PATTERNS.md`: 15 种反模式失败案例库。
  - `EXAMPLES.md`: 标杆文章范例。
  - `EVALUATIONS.md`: 评分标准与测试用例。
- `templates/`: [Assets] 文章结构模板（thought-leadership / industry-analysis / case-study / product-review）。
- `styles/`: [Assets] 风格调性配置（narrative / provocative / academic / balanced）。
- `integrations/`: [Workflow] 跨技能集成工作流文档。
- `agents/`: [UI] Gemini Agent 身份定义。

## Setup
```bash
# 安装量化评分依赖
pip install -r requirements.txt

# 运行上下文组装引擎
python scripts/assistant.py --topic "主题" --mode Standard --role "角色" --style narrative

# 运行质量评分
python metrics/quality_scoring.py article.md --verbose
```

> ⚠️ **Protocol**: 任何新的写作规范必须添加到 `references/GUIDELINES.md`，并在 `scripts/assistant.py` 中确认引用。
