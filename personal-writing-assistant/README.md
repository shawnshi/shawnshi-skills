# 专栏写作助手 (personal-writing-assistant)

顶级专栏作家与战略思想领袖引擎 (V4.1)。专为生成高信噪比、高穿透力且具备"反共识叙事美学"的深度文章设计。

## 核心能力
- 严格遵循专有的文字美学哲学：倡导动词骨骼 (Verb-Driven)、拒绝平铺直叙构建暗流感 (Narrative Resonance) 及使用克制冰凉的口吻 (Sincere Coldness)。
- 强制基于 **SCQA 架构**（情境、冲突、问题、答案）产出极简与锋利的文章大纲。
- **破除共识与侦察**：借助搜索工具动态获取真实的财报数据、宏观事件与关键人物发言点，确立冷酷的事实锚点。
- **手术刀级的起草**：摒弃任何形式的"AI 八股文"，应用极度反差感的钩子开头 (Hook) 及留白悬念式收尾。
- **自我残酷审查**：在对外输出文本前，对照 30+ 项检查清单与 15 条反模式逐一筛查，确保符合长短句的波浪交替韵律。

## 快速入门

### 1. 直接对话使用
告诉 Agent 你想写的主题，指定风格和模板即可：
> "写一篇关于医院数字化转型的深度文章，用 provocative 风格，thought-leadership 模板"

### 2. CLI 方式（通过 assistant.py）
```bash
python scripts/assistant.py \
  --topic "医院数字化转型" \
  --mode Deep \
  --role "资深数字健康顾问" \
  --style provocative \
  --template thought-leadership
```

### 3. 质量评分
```bash
pip install -r requirements.txt
python metrics/quality_scoring.py article.md --verbose
```

## 可用风格

| 风格 | 文件 | 特征 |
|------|------|------|
| **Default** | — | 平衡洞察与可读性 |
| **Narrative** | `styles/narrative.md` | 故事驱动，通过场景和人物传递洞察 |
| **Provocative** | `styles/provocative.md` | 挑战主流共识，激进论断，高传播性 |
| **Academic** | `styles/academic.md` | 数据驱动，引用充分，可验证性强 |
| **Balanced** | `styles/balanced.md` | 多视角呈现，寻求共识，政策建议 |

## 可用模板

| 模板 | 文件 | 适用场景 |
|------|------|----------|
| **Thought Leadership** | `templates/thought-leadership.md` | 提出独特观点，挑战主流共识 |
| **Industry Analysis** | `templates/industry-analysis.md` | 行业现状/趋势/竞争格局分析 |
| **Case Study** | `templates/case-study.md` | 具体案例深度剖析 |
| **Product Review** | `templates/product-review.md` | 产品/服务/方案评测 |

## 集成工作流
- **humanizer-zh-pro 润色流水线** (`integrations/humanizer-pipeline.md`)：写作 → 润色去 AI 味
- **planning-with-files 长篇管理** (`integrations/planning-workflow.md`)：复杂项目分段写作
- **research-analyst 研究协同** (`integrations/research-analyst-workflow.md`)：深度研究 → 洞察写作

## 使用场景
当用户期望草拟或创作具有极强深刻度、极高信息穿透力、完全摒弃"水文"废话特质的深度观点表达、评论或反常规逻辑专栏文章时。
