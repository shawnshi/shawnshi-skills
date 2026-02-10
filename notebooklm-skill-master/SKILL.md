---
name: notebooklm-skill-master
description: 使用 Google NotebookLM 深度查询自有文档。支持浏览器自动化、库管理与持久化认证。场景：基于文档的深度问答、研究分析。
---

# Research Assistant (NotebookLM Connector)

通过 Google NotebookLM 提供具备“证据支撑”的确定性知识查询。

## Core Capabilities
*   **Source-Grounded**: 所有回答均直接来源于用户上传的文档，杜绝幻觉。
*   **Auto-Environment**: 内置虚拟环境管理，自动处理依赖与浏览器驱动。
*   **Library Logic**: 支持多笔记本注册、检索与一键激活。

## Execution Workflow

### 1. Check Auth (首次必选)
```bash
python scripts/run.py auth_manager.py status
```
*   若未登录，运行 `python scripts/run.py auth_manager.py setup`。
*   **Protocol**: 此步会打开可见浏览器窗口，用户必须手动完成 Google 登录。

### 2. Manage Library
```bash
python scripts/run.py notebook_manager.py list
```
*   若要添加新笔记本：`python scripts/run.py notebook_manager.py add --url "[URL]" --name "[名称]" --description "[描述]"`。
*   详细命令见 `references/cli-reference.md`。

### 3. Ask Questions
```bash
python scripts/run.py ask_question.py --question "在此输入你的问题"
```
*   **Follow-up Policy**: 每个回答后，Agent 必须检查是否满足用户需求。若信息不全，立即发起追问。

## Best Practices
1.  **Always use run.py**: 严禁直接调用子脚本，必须使用包装器以确保环境正确。
2.  **Smart Discovery**: 若用户只给了一个笔记本 URL 却没给描述，先用 `ask_question.py` 问它“这个笔记本涵盖了什么内容”，再执行 `add` 操作。
3.  **Visible Browser**: 仅在认证或调试时显示浏览器。常规查询默认静默执行。

## Resources
*   **CLI 手册**: `references/cli-reference.md`
*   **故障排查**: `references/troubleshooting.md`

!!! Maintenance Protocol: 任何涉及 .venv 或依赖的变更，必须同步更新 scripts/run.py。
