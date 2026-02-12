# notebooklm-skill-master
<!-- Input: Notebook URLs, structured questions. -->
<!-- Output: Grounded knowledge responses, library status reports. -->
<!-- Pos: Knowledge Retrieval Layer (The Connector). -->
<!-- Maintenance Protocol: Update 'auth_manager.py' upon Google login flow changes. -->

## 核心功能
通过 Google NotebookLM 实现基于自有文档库的深度问答。作为“主权 AI”的知识挂载点，确保所有回答均具备证据支撑，杜绝幻觉。

## 战略契约
1. **证据锚定**: 所有回复必须直接来源于上传的文档库，严禁引入外部非验证信息。
2. **库管理自动化**: 支持多笔记本的动态注册与描述发现，实现知识资产的有序组织。
3. **闭环追问**: 若文档提供的信息不足以解决用户问题，必须立即发起针对性的补充追问。
