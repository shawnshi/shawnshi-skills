---
name: slide-blocks
description: PPT 智能组装助手。用于从素材库中挑选幻灯片、拼装成一份完整的、风格统一的 PPT。当用户说"帮我做一个PPT"、"组装一份汇报"、"从素材里选几页拼一下"、"我需要一个售前演示"、"选几张幻灯片"、"从历史PPT里找内容"、"做行业会议/售前汇报"、"换个模板风格"，或提到具体章节主题和来源文件时，使用此 skill。也适用于：搜集/汇总PPT素材（如"帮我搜集XXX的页面"、"汇总一下XXX相关素材"）、查询素材库（如"有没有关于XXX的页面"、"查一下素材库"）、对已有组装方案做调整、或将已有 PPT 转换为浅色底/深色底的场景。**只要消息里涉及 PPT 内容检索、素材搜集、幻灯片组装、模板套用，就必须主动触发，不要等用户明确说"用 slide-blocks"。**
Native tools integration: run_command, write_file, view_file, ask_user
---

# SlideBlocks 组装助手 (V3.0 架构 - Mentat Certified)

## 核心架构与模式
SlideBlocks 采用**逻辑与渲染解耦**的架构：
- `slide_vault/`：负责混合检索、LLM 文本打标、Vision 版式感知与向量存储。
- `engine/`：负责基于 JSON 的 COM 渲染与物理编辑。

根据用户需求判断模式：
- **Mode A（纯工具模式）** [Tool Wrapper]：不依赖素材库，对指定 PPT 直接进行色系转换、删页、插页等物理操作。
- **Mode B（智能组装模式）** [Pipeline]：从素材库检索（Hybrid Search），构建 JSON 配置，驱动 `runner.py` 组装全新的 PPT。
- **Mode C（建库模式）**：扫描新加入的 PPT 并通过 LLM 建立三重索引（文本、视觉、语义向量）。
- **Mode D(跨技能联合编排 )**：当遇到宏大的战略汇报任务时，`slide-blocks` 应退格为底层的“渲染引擎”，与 `presentation-architect` (大脑) 组成联合流水线。

---

<Contracts>
1. **零代码组装契约**：在 Mode B 下，必须且只能生成 `.json` 文件来驱动 `engine/runner.py`，绝对禁止让 AI 生成临时 Python 脚本。
2. **确认门控契约**：在执行组装（Phase 3 归档阶段）前，必须向用户展示检索结果与方案，获得明确许可后才能执行。
3. **视觉排版契约**：使用浅色商务模板时，必须为过渡页（P2）配置 `"font_size": 40`，防止字号撑破版面。
4. **路径防幻觉契约**：必须通过 `view_file` 读取 `config.yaml` 获取 `materials_dir` 与 `output_dir` 绝对路径，禁止使用硬编码盘符虚构路径。
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

## Mode B：智能组装工作流 [GEB-Pipeline]

### 🟢 Reconnaissance (侦察): 意图收敛、环境侦测与混合检索
1. **环境侦测**：强制使用 `view_file` 读取当前目录下的 `config.yaml`，提取 `materials_dir` 和 `output_dir` 了解绝对路径前缀。
2. **参数确认**：通过 `ask_user` 向用户确认核心参数（已在上下文中明确的直接跳过）：
   - 大致章节结构。
   - 素材倾向（偏管理、偏临床、或是特定案例）。
   - **🚨 模板风格（深色底 / 浅色底？这是硬阻塞节点，不回答不可进入下一步）**。
3. **Hybrid Search 检索**：
   结合关键词和语义向量（Vector RAG）寻找最优素材。通过建立临时 python 脚本，调用 `run_command` 在终端执行 `search_hybrid` 模块进行搜索：
   ```python
   # 范例：你可以创建并执行一段检索代码
   from slide_vault.search import search_hybrid, print_results

   results = search_hybrid(
       scene="售前汇报",           # 可选
       content_type="解决方案",    # 可选
       layout_type="对比页",       # 可选，视觉版式（封面, 纯文字页, 逻辑架构图, 对比页, 时间轴/流程, 等）
       keywords=["智慧医疗", "降本增效"], # 会自动匹配文本并计算向量相似度
       quality_min=4,
       use_vector=True,
       limit=10
   )
   print_results(results)
   ```
   **必须**将检索结果以精简的表格展示给用户，包含“来源文件”与“主要内容摘要”。

### 🟡 Synthesis (编译): 固化 JSON 组装计划
使用 `write_file` 在 `tasks/` 目录下创建一个 JSON 文件（如 `tasks/plan_demo.json`）。**必须严格遵循以下 Schema，路径前缀必须基于前一步读取的 config.yaml 真实环境构建**。

```json
{
  "template_path": "{materials_dir 的真实绝对物理路径}/模板/蓝色商务（浅色底）.pptx",
  "output_path": "{output_dir 的真实绝对物理路径}/客户汇报_2026.pptx",
  "plan": [
    {
      "template_page": 1, 
      "replace_title": "主标题"
    },
    {
      "src": "{materials_dir 的真实绝对物理路径}/XXX案例.pptx", 
      "page": 5, 
      "fix_colors": true
    },
    {
      "template_page": 2, 
      "replace_title": "第二章节名称",
      "font_size": 40
    },
    {
      "src": "{materials_dir 的真实绝对物理路径}/XXX方案.pptx", 
      "page": 12
    },
    {
      "template_page": 5
    }
  ]
}
```
**JSON 组装规则：**
1. `template_path` 和 `output_path` 必须是基于 `config.yaml` 动态组合的绝对路径。
2. 封面（P1）后直接接内容页，不加过渡页（P2）。
3. 过渡页（P2）必须配置 `"font_size": 40`。
4. 结尾必须包含 `{"template_page": 5}`。
5. 当源文件是“深色底”而目标是“浅色底”（或反之）时，引擎会自动执行 `swap_theme_colors` 乃至强制 RGB 翻转。如果未自动识别，可通过 `"fix_colors": true` 强制触发深转浅，或 `"fix_colors_dark": true` 强制转深。

### 🔴 Finalization (归档): 物理执行与交付
执行前，自检 JSON 格式是否正确无误。
**强制操作**：你必须主动调用 `run_command` 工具运行以下命令，完成物理组装：
```bash
$env:PYTHONPATH='.'; python engine/runner.py tasks/plan_demo.json
```
运行期间，通过 `command_status` 观察输出。如果遭遇 COM 异常或死锁，请参考 `<Failure_Taxonomy>` 重试或提供建议。最后交付给用户组装好的最终文件绝对路径。

---

## Mode A：纯工具模式 (无需素材库) [Tool Wrapper]

用户指定对某文件进行物理编辑时，直接使用 `write_file` 编写临时 Python 脚本，并通过 `run_command` 工具调用 `engine`。

### 色系翻转
```python
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path("engine").resolve()))
from convert_deck import convert

# 深色底 → 浅色底，自动选模板，自动执行色彩反转与底线防御
# 须填充真实绝对路径
convert("C:/真实绝对物理路径/输入文件.pptx", to="light")   
```

### 局部编辑
```python
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path("engine").resolve()))
from edit_pptx import edit

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

当用户加入新 PPT 素材或要求更新素材库时，你必须主动调用 `run_command` 工具运行以下脚本：

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
2. **居中降维 (Agent Routing)**：你作为居中 Agent，读取 Markdown 骨架中的视觉意图，并将其转换为 `slide-blocks` 能理解的 `search_hybrid` 参数（例如：`[Visual_Intent: 对比]` -> `layout_type="对比页"`，核心论点 -> `keywords`）。
3. **双手渲染**：利用 `search_hybrid` 寻获最匹配的原生幻灯片，动态获取物理路径后装填进 `plan.json`，强制唤醒 `run_command` 行组装命令。

---

## 历史失效先验 (Gotchas)
- 🚫 **严禁在 PowerShell 中使用 `&&` 连接符**。
- 🚫 **严禁在组装时生成 `.py` 脚本并修改全局变量**。必须且只能使用 `write_file` 生成 `JSON` 计划文件，驱动 `engine/runner.py`。
- 🚫 **严禁在未确认“深色/浅色”模板且未通过 `config.yaml` 明确输出与素材绝对物理路径时盲目组装**，极易导致幻觉失效与色系冲突反工。
