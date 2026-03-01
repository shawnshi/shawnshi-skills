---
name: notebooklm-skill-master
description: 使用 Google NotebookLM 深度查询自有文档。支持浏览器自动化、库管理、持久化认证及自动化资产打包生成（如信息图核心内容与幻灯片框架）。场景：基于文档的深度问答、研究分析、内容创作。
---

# 🧠 NotebookLM 知识引擎专家 (NotebookLM Knowledge Engine Expert)

## 🎯 系统定位 (System Positioning)
通过 Google NotebookLM 提供具备“证据支撑”的确定性知识查询。作为核心智能体，深度查询自带文档，确保问答直接来源于用户上传的内容，从根本上杜绝大模型幻觉。

## ⚙️ 核心架构与能力 (Core Architecture & Capabilities)
*   **Source-Grounded (信源溯源)**: 所有回答均被强制约束为直接来源于用户上传的 NotebookLM 文档，提供高度可靠的事实依据。
*   **Auto-Environment (自动化沙箱)**: 内置虚拟环境隔离管理，自动处理各项依赖包与前端浏览器驱动，确保开箱即用。
*   **Library Logic (知识库路由)**: 支持多子笔记本 (Notebooks) 单独注册、精准发现与一键路由激活，满足多维度项目并行需求。

## 🔄 执行流 (Execution Workflow)

### 阶段 1 (Phase 1): 认证与启动 (Auth & Setup)
> ⚠️ **前置条件与协议**: 首次执行特定环境或 Token 失效时强制执行。此步会**调起可见浏览器窗口**，Agent 须指引用户手动完成 Google 账户授权登录。
```bash
python scripts/run.py auth_manager.py status
```
*若判定为未登录状态，自动发起:*
```bash
python scripts/run.py auth_manager.py setup
```

### 阶段 2 (Phase 2): 知识库管理 (Manage Library)
> 列出已有的笔记本清单，或根据需要添加新知识维度。
```bash
python scripts/run.py notebook_manager.py list
```
*   **注册新库 (Add)**:
```bash
python scripts/run.py notebook_manager.py add --url "[URL]" --name "[名称]" --description "[描述]"
```
*   **自动同步云端库 (Sync All)**:
> 自动查询所有在线的知识库，并将尚未关联的知识库一键注册到本地，默认使用在线的名称。
```bash
python scripts/run.py notebook_manager.py sync
```

### 阶段 3 (Phase 3): 数据源注入 (Add Source)
> 为指定的 Notebook 知识库上传文件或添加网页链接。
```bash
# 上传本地文件到知识库
python scripts/run.py add_source.py --notebook "[库名称/ID]" --type "file" --path "/绝对路径/document.pdf"

# 添加网页链接到知识库
python scripts/run.py add_source.py --notebook "[库名称/ID]" --type "link" --path "https://example.com"
```

### 阶段 4 (Phase 4): 深度检索问答 (Ask Questions)
> 核心交互环节：基于已激活或选定的 Notebook 发起深度询问。
```bash
python scripts/run.py ask_question.py --question "在此输入你的问题"
```

### 阶段 5 (Phase 5): 结构化资产生成 (Structured Asset Generation)
> 扩展能力：在指定的知识库 (Notebook) 中，基于上传的文档全量或针对性提取，生成可视化资产与研报的核心结构数据。例如，一键生成信息图 (Infographic) 的视觉大纲、幻灯片 (Slide Deck) 的分页结构与演讲词，或深度战略研报 (Report)。
```bash
# 生成信息图 (Infographic) 核心数据节点与文案
python scripts/run.py generate_asset.py --type "infographic" --notebook "[库名称]" --topic "[可选: 具体聚焦主题]"

# 生成幻灯片 (Slide Deck) 分页结构、核心要点与配套演讲词
python scripts/run.py generate_asset.py --type "slide_deck" --notebook "[库名称]" --topic "[可选: 具体聚焦主题]"

# 生成深度研报 (Report) 高管简报与分析
python scripts/run.py generate_asset.py --type "report" --notebook "[库名称]" --topic "[可选: 具体聚焦主题]"
```

## 🛠️ 最佳实践与行为准则 (Best Practices & Behavioral Protocols)
1.  **Smart Discovery (智能探索)**: 若用户提供的需求仅包含一个笔记本 URL 却缺少内容描述，Agent 应首先调用 `ask_question.py` 询问 NotebookLM：“请告诉我这个笔记本涵盖了什么内容”，获取摘要后再执行 `add` 操作。
2.  **Follow-up Policy (追问验证)**: Agent 必须在每次提取回答后，反思检查是否完全满足了用户的原始查询需求。若识别出信息断层或不全，应主动发起相关追问补齐拼图。
3.  **Visible Browser (静默优先)**: 常规的问答查询默认在后台静默执行 (headless)。仅在用户认证 (Auth) 流程或深度诊断日志报错时，方可启用可视化浏览器。

## 🚨 维护红线 (Maintenance Protocol)
*   **Always use run.py (防穿透执行)**: 严禁直接经由 `python` 直接调用内部子脚本。所有的调用树必须经过入口包装器 `scripts/run.py`，以确保具备一致的虚拟运行时与上下文注入。
*   **依赖刚性 (Dependency Sync)**: 任何涉及 `.venv` 虚拟环境变更或外部依赖包 (pip) 的调整，必须确保 `scripts/run.py` 内部检测逻辑被同步更新。

## 📚 附属资源 (Resources)
*   **CLI 操作详编**: `references/cli-reference.md`
*   **故障排查矩阵**: `references/troubleshooting.md`
