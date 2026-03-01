# Changelog

本文件记录 Personal Writing Assistant 技能的版本演进历史。

---

## V4.1 (2026-02-21)

### 架构优化
- **统一工作流**：SKILL.md 重写为 5 阶段协议（Phase 0-4），解决了与 GUIDELINES.md 的阶段编号冲突
- **GUIDELINES.md 重定位**：从独立工作流定义降级为 SKILL.md 的参考扩展材料，添加 Phase 交叉引用
- **清理 create-plan/**：删除了与写作无关的通用规划子技能残留

### 功能增强
- **Resource Map**：SKILL.md 新增资源索引表，列出所有可用的 styles / templates / references / tools
- **assistant.py 重写**：清理代码噪音，新增 ANTI_PATTERNS 加载与注入，添加 YAML 元数据头
- **requirements.txt**：新增 Python 依赖声明（jieba）
- **评估维度对齐**：EVALUATIONS.md 新增人工评估 vs 自动评估的维度映射表

### 文档打磨
- **gemini.yaml 丰富化**：添加版本号、instructions 字段、多行 default_prompt
- **README.md 扩展**：新增快速入门、风格/模板表格、集成工作流说明
- **EXAMPLES.md 扩充**：从 2 个增至 4 个范例，覆盖 Narrative + Provocative 风格和非医疗领域
- **_DIR_META.md 完善**：完整的 Member Index 和 Setup 说明
- **CHANGELOG.md 新增**：版本管理历史记录

---

## V4.0 (初始版本)

### 核心特性
- SCQA 架构驱动的文章骨架生成
- 5 项核心美学哲学（Verb-Driven / Narrative Resonance / Rhythm / Three-Bold / Sincere Coldness）
- 4 种风格（narrative / provocative / academic / balanced）
- 4 种模板（thought-leadership / industry-analysis / case-study / product-review）
- 30+ 项质控检查清单与 15 条反模式库
- 量化质量评分器（quality_scoring.py）
- 3 个跨技能集成工作流
