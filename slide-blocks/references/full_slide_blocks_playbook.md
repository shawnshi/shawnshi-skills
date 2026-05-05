---
name: slide-blocks
description: PPT 智能组装助手。Primary owner for slide-library retrieval and assembly: find existing pages, reuse historical PPT assets, swap templates, and assemble decks from source slides. Prefer presentation-architect when the task is to design a new strategy-deck narrative or chapter architecture from scratch.
Native tools integration: shell execution, file read/write, direct user confirmation
---

# SlideBlocks 组装助手 (V3.0 架构 - Mentat Certified)

## 核心架构与模式
SlideBlocks 采用**逻辑与渲染解耦**的架构：
- `slide_vault/`：负责混合检索、LLM 文本打标、Vision 版式感知与向量存储。
- `engine/`：负责基于 JSON 的 COM 渲染与物理编辑。

根据用户需求判断模式：
- **Mode A（纯工具模式）** **Tool Wrapper**：不依赖素材库，对指定 PPT 直接进行色系转换、删页、插页等物理操作。
- **Mode B（智能组装模式）** **Pipeline**：从素材库检索（Hybrid Search），构建 JSON 配置，驱动 `runner.py` 组装全新的 PPT。
- **Mode C（建库模式）**：扫描新加入的 PPT 并通过 LLM 建立三重索引（文本、视觉、语义向量）。
- **Mode D(跨技能联合编排 )**：当遇到宏大的战略汇报任务时，`slide-blocks` 应退格为底层的“渲染引擎”，与 `presentation-architect` (大脑) 组成联合流水线。

---

<Contracts>
1. **零代码组装契约**：在 Mode B 的**组装阶段**，必须且只能生成 `.json` 文件来驱动 `engine/runner.py`，绝对禁止让 AI 生成临时 Python 脚本用于组装（但允许使用 Python 脚本或 CLI 模块进行纯粹的检索与洞察）。
2. **确认门控契约**：在执行组装（Phase 3 归档阶段）前，必须向用户展示检索结果与方案，获得明确许可后才能执行。
3. **视觉排版契约**：使用浅色商务模板时，必须为过渡页（P2）配置 `"font_size": 40`，防止字号撑破版面。
4. **路径主权契约**：计划文件优先使用 `{materials_dir}` / `{output_dir}` 宏，禁止写死过时盘符。若模板路径未写入 plan，可由 `manifests/*.json` 提供。
5. **编译期校验契约**：进入 COM 组装前，必须先通过 `engine.plan_validator` 或 `engine.runner --dry-run`，不得跳过 plan 校验。
</Contracts>

<Failure_Taxonomy>
1. **API 限流/网络断开 (`429`, `SSL EOF`)**：
   - 路由：`enricher.py` 和 `vector_store.py` 已内建 `@with_retry` 指数退避，保持观察。若持续失败，提示用户检查网络或切换模型配置 (`config.yaml`)。
2. **COM 进程死锁/属性报错 (`AttributeError`, `RPC_E_CANTCALLOUT_INEXTERNALCALL`)**：
   - 路由：`engine/com_helper.py` 会自动执行 `taskkill` 和 `DispatchEx/CLSID` 重载。如果报错，提示用户关闭所有 PPT 窗口后重试。
3. **剪贴板抢占 (`Clipboard is empty`)**：
   - 路由：引擎内置 `_safe_paste` 的 5 次重试机制。若依旧失败，说明系统剪贴板被强行锁定，建议用户暂停其他操作并重试。
</Failure_Taxonomy>

---

## Mode B：智能组装工作流 **GEB-Pipeline**

### 🟢 Reconnaissance (侦察): 意图收敛、环境侦测与混合检索
1. **环境侦测**：强制读取当前目录下的 `config.yaml`，确认 `materials_dir` 和 `output_dir`。若需要模板角色主权，额外读取 `manifests/*.json`。
2. **参数确认**：直接向用户确认核心参数（已在上下文中明确的直接跳过）：
   - 大致章节结构。
   - 素材倾向（偏管理、偏临床、或是特定案例）。
   - **🚨 模板风格（深色底 / 浅色底？这是硬阻塞节点，不回答不可进入下一步）**。
   结合关键词和语义向量（Vector RAG）寻找最优素材。**强烈推荐直接使用 CLI 模块，避免手写 Python 脚本导致报错**：
   ```bash
   $env:PYTHONPATH='.'
   python -m slide_vault.search --mode hybrid --scene "售前汇报" --layout "对比页" --keywords "智慧医疗" "降本增效" --limit 10
   ```
   **必须**将检索结果以精简的表格展示给用户，包含“来源文件”与“主要内容摘要”。

### 🟡 Synthesis (编译): 固化 JSON 组装计划
在 `tasks/` 目录下创建一个 JSON 文件（如 `tasks/plan_demo.json`）。**必须严格遵循以下 Schema，路径前缀必须基于 `config.yaml` 动态展开，推荐直接使用路径宏。**

```json
{
  "template_path": "{materials_dir}/2025年度PPT素材汇总（浅色底）.pptx",
  "output_path": "{output_dir}/客户汇报_2026.pptx",
  "plan": [
    {
      "template_page": 1, 
      "replace_title": "主标题"
    },
    {
      "src": "{materials_dir}/XXX案例.pptx", 
      "page": 5, 
      "fix_colors": true
    },
    {
      "template_page": 2, 
      "replace_title": "第二章节名称",
      "font_size": 40
    },
    {
      "src": "{materials_dir}/XXX方案.pptx", 
      "page": 12
    },
    {
      "template_page": 5
    }
  ]
}
```
**JSON 组装规则：**
1. `template_path`、`output_path` 和 `src` 推荐使用 `{materials_dir}` / `{output_dir}` 宏；校验器会在执行前统一展开。
2. 封面（P1）后直接接内容页，不加过渡页（P2）。
3. 过渡页（P2）必须配置 `"font_size": 40`。
4. 结尾必须包含 `{"template_page": 5}`。
5. 当源文件是“深色底”而目标是“浅色底”（或反之）时，引擎会自动执行 `swap_theme_colors` 乃至强制 RGB 翻转。如果未自动识别，可通过 `"fix_colors": true` 强制触发深转浅，或 `"fix_colors_dark": true` 强制转深。
6. 若计划中省略 `template_path`，则必须提供 `--manifest`，由 manifest 注入模板路径与模板页角色。

### 🔴 Finalization (归档): 物理执行与交付
执行前，必须先做 dry-run 校验。
**强制操作**：你必须按以下顺序执行 shell 命令：
```bash
$env:PYTHONPATH='.'; python -m engine.plan_validator tasks/plan_demo.json --manifest manifests/light-default.json
$env:PYTHONPATH='.'; python -m engine.runner tasks/plan_demo.json --dry-run --manifest manifests/light-default.json
$env:PYTHONPATH='.'; python -m engine.runner tasks/plan_demo.json --manifest manifests/light-default.json
```
运行期间，直接查看终端输出。如果遭遇 COM 异常或死锁，请参考 `<Failure_Taxonomy>` 重试或提供建议。最后交付给用户组装好的最终文件绝对路径。

---

## Mode A：纯工具模式 (无需素材库) **Tool Wrapper**

用户指定对某文件进行物理编辑时，直接编写临时 Python 脚本，并通过 shell 命令调用 `engine`。

### 色系翻转
```python
from engine.convert_deck import convert

# 深色底 → 浅色底，自动选模板，自动执行色彩反转与底线防御
# 须填充真实绝对路径
convert("C:/真实绝对物理路径/输入文件.pptx", to="light")   
```

### 局部编辑
```python
from engine.edit_pptx import edit

# 须填充真实绝对路径
edit("输出真实路径/xxx.pptx", [
    {"op": "delete",          "pages": [7, 8]},
    {"op": "move",            "pages": [7, 8], "after": 15},
    {"op": "insert_template", "template_page": 2, "after": 5, "title": "新章节", "font_size": 40},
    {"op": "replace",         "page": 12, "src": "真实素材绝对路径/源.pptx", "src_page": 5},
])
```

---

## Mode C：从零建库 / 增量更新

当用户加入新 PPT 素材或要求更新素材库时，你必须主动执行以下脚本：

1. **扫描与视觉提取** (提取文本并生成 JPG 预览图)
   ```bash
   $env:PYTHONPATH='.'; python -m slide_vault.scanner
   ```
2. **全能打标流水线** (利用 Gemini API 进行文本打标、Vision版式识别与 Embedding 向量化)
   ```bash
   $env:PYTHONPATH='.'; python -m slide_vault.enricher --all
   ```

---

## Mode D：跨技能联合编排 (Cross-Skill Orchestration)
当遇到宏大的战略汇报任务时，`slide-blocks` 应退格为底层的“渲染引擎”，与 `presentation-architect` (大脑) 组成联合流水线：

1. **大脑定调**：由 `presentation-architect` 主导 OODA 推演，输出带有 `[Visual_Intent]` 标记的 Markdown 骨架。
2. **居中降维 (Agent Routing)**：你作为居中 Agent，读取 Markdown 骨架中的视觉意图，并将其转换为 `slide_vault.search` 的 CLI 参数。
   * **Visual_Intent 映射表**:
     - `[Visual_Intent: 封面, title: X]` -> `--layout "封面" --keywords "X"`
     - `[Visual_Intent: 痛点/洞察]` -> `--layout "图表页" --keywords "政策" "痛点"`
     - `[Visual_Intent: 顶层架构]` -> `--layout "逻辑架构图"`
     - `[Visual_Intent: 方案/对标]` -> `--layout "对比页"`
     - `[Visual_Intent: 实施路径]` -> `--layout "时间轴/流程"`
3. **闭环组装 (Hands-on Assembly)**：如果找到了匹配素材，将 `src` / `page` 装入 json。如果**未找到匹配素材（回退降级）**，使用 `{"template_page": 3, "replace_title": "预期标题"}`（占位），并直接向用户说明该处缺失原生素材骨架，让用户后期手绘。最后先跑 `engine.plan_validator`，再调用 `runner.py`。
---

## 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Execute PowerShell"] THEN [Halt if Command contains "&&"]`
- `IF [Mode == "Assembly"] THEN [Halt if Generating ".py" script] AND [Require persisted("JSON plan") -> Execute "engine.plan_validator" -> Execute "engine/runner.py"]`
- `IF [Action == "Assembly"] THEN [Require confirmed("Template Color Theme") AND Require path_macros_or_manifest()] ELSE [Halt Execution]`

## When to Use
- 当用户需要检索 PPT 素材、组装汇报、套模板或从历史页面中挑选内容时使用。
- 素材选择、JSON 计划和 runner 执行方式仍以本文件既有协议为准。

## Workflow
- 遵循本文件已有的素材检索、匹配、组装和回退流程。
- 不跳过模板颜色确认、路径宏或 manifest 配置、JSON 计划生成和 dry-run 校验。

## Resources
- 使用本技能引用的素材库、`engine/plan_validator.py`、`engine/runner.py`、`manifests/*.json`、配置文件和示例计划。
- 若正文中点名 `config.yaml`、manifest、模板页或 runner 路径，以那些物理资源为准。

## Failure Modes
- 将本文件中的装配禁令、PowerShell 约束和 `NLAH Gotchas` 视为失败模式。
- 若找不到匹配素材，必须显式回退为占位方案并告知缺口，不能伪造原生页面。

## Output Contract
- 最终交付必须包含可执行的组装计划或完成的素材拼装结果，并标明缺失骨架。
- 若进入 Assembly 模式，必须通过 JSON plan 驱动现有引擎，而不是临时生成新脚本。
- 计划文件应优先使用路径宏；若省略 `template_path`，必须显式提供 manifest。

## Telemetry
- 按本文件上方定义的 telemetry 规则记录元数据。
