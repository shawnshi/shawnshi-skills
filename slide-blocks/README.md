# SlideBlocks V3 — 语义化 PPT 智能组装引擎

SlideBlocks 是一个基于“幻灯片积木化”思路构建的 PPT 资产管理与智能组装系统。它能够将海量 PPT 解析为原子化的幻灯片素材，并通过 LLM 语义标签、视觉版式感知和向量搜索实现精准检索与高质量组装。

---

## 核心架构

项目采用 **“逻辑与渲染分离”** 的双层架构：

- **`engine/` (物理渲染层)**：负责 PPT 的底层操作（COM 进程守护、形状克隆、主题色递归映射、预览图导出）。
- **`slide_vault/` (资产管理层)**：负责幻灯片资产的索引、LLM 业务语义打标、Gemini Vision 视觉版式识别、语义向量检索。

---

## 快速开始

### 1. 环境准备
- Windows 10/11
- Microsoft PowerPoint (推荐) 或 WPS
- Python 3.9+
- 设置环境变量 `GEMINI_API_KEY`

```bash
pip install google-genai python-pptx pyyaml pywin32 numpy Pillow
```

### 2. 初始化配置
编辑 `config.yaml`，设置您的素材目录与输出路径。

### 3. 选择模板主权来源

现在支持两种模板路径来源：

- 在计划 JSON 中直接写 `template_path`
- 通过 `manifests/*.json` 提供模板路径和模板页角色

推荐优先使用 manifest，并在任务计划中使用 `{materials_dir}` / `{output_dir}` 宏。

---

## 素材库构建工作流 (Mode C)

现在只需两步即可构建具备“视觉”与“灵魂”的素材库：

### 第一步：扫描素材
提取文本并自动导出高清预览图。
```bash
python slide_vault/scanner.py
```

### 第二步：智能增强
一键完成 **文本语义打标** + **视觉版式识别** + **语义向量化**。
```bash
python slide_vault/enricher.py --all
```
*注：亦可使用 `--text`, `--vision`, `--vector` 进行单项增强。*

---

## 组装执行链路

V3 的推荐执行顺序是：

1. 写 plan JSON
2. 运行 `engine.plan_validator`
3. 运行 `engine.runner --dry-run`
4. 运行正式 `engine.runner`

示例：

```bash
python -m engine.plan_validator tasks/ai_strategy_plan.json --manifest manifests/light-default.json
python -m engine.runner tasks/ai_strategy_plan.json --dry-run --manifest manifests/light-default.json
python -m engine.runner tasks/ai_strategy_plan.json --manifest manifests/light-default.json
```

若计划文件省略 `template_path`，则必须通过 `--manifest` 提供模板来源。

---

## 商业语义层

V3 现在支持面向医疗售前与高层汇报的商业标签：

- `buyer_personas`
- `deal_stage`
- `objection_tags`
- `proof_type`
- `evidence_tier`

这些标签可以通过两种方式写入：

- 文本增强时由模型生成
- 对已有素材库执行本地规则回填

回填命令：

```bash
python -m slide_vault.enricher --commercial
```

---

## 使用模式

### Mode A：纯工具模式 (无需素材库)
直接处理本地 PPT，无需数据库支持。

| 功能 | 调用脚本 | 核心能力 |
|------|------|------|
| **色系转换** | `convert_deck.py` | 深色底 ↔ 浅色底一键转换，主题色自适应修复 |
| **局部编辑** | `edit_pptx.py` | 批量删页、移页、插入模板页、替换指定页内容 |

### Mode B：智能组装模式
告诉 AI 您的需求，它将从库中检索素材并根据模板组装。
> "帮我做一个售前汇报，需要关于‘医院数字化转型’的背景，以及一个‘三栏对比’格式的解决方案页面。"

任务计划现在支持路径宏：

```json
{
  "template_path": "{materials_dir}/2025年度PPT素材汇总（浅色底）.pptx",
  "output_path": "{output_dir}/客户汇报_2026.pptx",
  "plan": [
    {"template_page": 1, "replace_title": "主标题"},
    {"src": "{materials_dir}/XXX案例.pptx", "page": 5},
    {"template_page": 2, "replace_title": "第二章节", "font_size": 40},
    {"src": "{materials_dir}/XXX方案.pptx", "page": 12},
    {"template_page": 5}
  ]
}
```

默认 manifest 位于：

- `manifests/light-default.json`
- `manifests/dark-default.json`

商业检索示例：

```bash
python -m slide_vault.search --mode hybrid --persona cio --deck-mode cio_architecture --no-vector --limit 5
python -m slide_vault.search --mode hybrid --persona chairman --proof-type quantitative_outcome --no-vector --limit 5
python -m slide_vault.search --mode hybrid --objection data_security --deck-mode cio_architecture --no-vector --limit 5
```

商业规划示例：

```bash
python -m slide_vault.planner --title "致北大医疗集团 CIO 的 AI 架构汇报" --deck-mode cio_architecture --source "北大医疗AI规划交流20260303" --keywords AI 架构 治理 私有部署
python -m slide_vault.planner --title "致集团董事长的 AI 战略汇报" --deck-mode board_strategy --source "北大医疗AI规划交流" --keywords AI 战略 回报率 治理 --objection roi_unclear data_security
```

`planner` 会同时生成两份文件：

- `tasks/*_candidates.json`：按章节分组的候选页与备选页，供审阅
- `tasks/*_plan.json`：可直接交给 `engine.plan_validator` / `engine.runner` 的组装计划

如需兼容历史 `tasks/search_results.json` 工作流，可额外输出 legacy 分组报告：

```bash
python -m slide_vault.planner --title "致集团董事长的 AI 战略汇报" --deck-mode board_strategy --source "北大医疗AI规划交流" --keywords AI 战略 回报率 治理 --objection roi_unclear data_security --legacy-results-file tasks/search_results.json
```

推荐链路：

```bash
python -m slide_vault.planner --title "致北大医疗集团 CIO 的 AI 架构汇报" --deck-mode cio_architecture --source "北大医疗AI规划交流20260303" --keywords AI 架构 治理 私有部署
python -m engine.plan_validator tasks/cio_architecture_致北大医疗集团_CIO_的_AI_架构汇报_plan.json --manifest manifests/light-default.json
python -m engine.runner tasks/cio_architecture_致北大医疗集团_CIO_的_AI_架构汇报_plan.json --dry-run --manifest manifests/light-default.json
```

`presentation-architect` 联动链路：

当上游已经产出 `outline.md` 时，可直接桥接到 SlideBlocks 计划层：

```bash
python -m slide_vault.outline_bridge C:\Users\shich\.gemini\slide-deck\Epic_AI_Strategy_20260403\outline.md --source Epic --manifest manifests/light-default.json
python -m engine.plan_validator tasks/Epic_AI_Strategy_20260403_slideblocks_plan.json --manifest manifests/light-default.json
python -m engine.runner tasks/Epic_AI_Strategy_20260403_slideblocks_plan.json --dry-run --manifest manifests/light-default.json
```

桥接配置与规则主权现在分成两层：

- `references/source-clusters.json`：来源簇、proof/layout/content 偏好与负面词
- `references/outline-bridge-config.json`：搜索降采样、缓存、评分权重、默认置信阈值

`source-clusters.json` 会按 `references/source-clusters.schema.json` 做加载时校验；缺字段或字段类型错误会直接失败，而不是静默降级。

桥接器会：

- 解析 `outline.md` 的页级叙事结构
- 从 `Audience` 推断 `buyer_persona` 与 `deck_mode`
- 从 `references/source-clusters.json` 读取来源簇规则
- 支持来源簇内的 `preferred_proof_types`、`preferred_layouts`、`preferred_content_types` 与负面惩罚规则
- 会优先按 `preferred_content_types` 发起检索，并在进入 rerank 前过滤 `negative_content_types`
- 按页检索最匹配素材
- 对候选页执行二次 rerank，并输出 `bridge_confidence`
- 低于阈值时自动退化为模板占位页，同时保留备选页供人工复核
- 默认输出到 `slide-blocks/tasks` 下的 `*_slideblocks_candidates.json`、`*_slideblocks_plan.json` 和 `*_slideblocks_review.md`

`*_slideblocks_review.md` 现在会额外显示：

- `Manual Queue`：需要人工复核的中置信命中页与 placeholder 页
- `Filter Audit`：总过滤轮次、剔除的负面内容页数量、回退次数、缓存命中/未命中、去重与降采样统计
- `Selected Type`：选中页的 `content_type / proof_type / layout_type`
- `Alternates`：备选页的同类语义信息，便于人工复核
- `Decision / Top Candidate Audit`：为什么接受、为什么降级，以及最接近命中的那一页是谁

判读建议：

- `placeholder` 不代表失败，而是桥接器判断“硬匹配会误导”，选择保守退回模板占位
- `fallbacks` 高，说明负面内容过滤较激进，来源簇或内容类型偏好需要继续调参
- `downsampled` 高，说明搜索变体较多，优先检查 `outline-bridge-config.json` 的搜索上限

---

## 测试与回归

桥接层提供了本地 `unittest` 回归，覆盖：

- `source-clusters` schema 校验
- `negative_content_types` 过滤
- 低置信命中退化为 placeholder
- 搜索去重与降采样

运行方式：

```bash
python -m unittest discover -s tests -p "test_*.py"
```

建议每次修改以下任一文件后都跑一遍：

- `slide_vault/outline_bridge.py`
- `references/source-clusters.json`
- `references/outline-bridge-config.json`

## 进阶功能：Hybrid Search (混合检索)
V2 版本引入了混合检索算法：
- **关键词权重 (40%)**：精准匹配业务名词。
- **语义向量 (60%)**：基于 `gemini-embedding-2-preview` 捕捉逻辑相关性。
- **视觉版式过滤**：支持按 `layout_type` (如：对比页、逻辑图、时间轴) 进行物理版式筛选。

---

## 常见问题
- **组装时 PPT 窗口弹出？** 正常现象，系统正在通过 COM 接口进行高保真渲染，请勿手动操作窗口。
- **标签生成失败？** 检查网络环境及 `GEMINI_API_KEY` 是否有效。
- **为什么现在不建议写死 `D:/OneDrive/...`？** V3 已把路径主权收口到 `config.yaml` 和路径宏，历史绝对路径样例已不再是推荐方式。
- **为什么要先跑 validator？** 它会在 COM 执行前拦截模板缺失、源文件缺失、过渡页字号错误、结尾页缺失和页码越界。 
