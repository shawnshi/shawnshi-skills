# 样式与图型矩阵

生成器支持 Style 1–7。名称只描述本技能内的视觉配置，不代表任何第三方提供、认可或维护该样式。

## 快速选择

| Style | 中性名称 | 架构 / 数据流 | 流程 / 时间线 | 密集语义图 | 适合场景 | 主要限制 |
|---:|---|---|---|---|---|---|
| 1 | [Flat Icon](style-1-flat-icon.md) | 优 | 优 | 良 | 默认选择、PPT、一般技术说明 | 色彩较多，不适合极严肃的黑白文件 |
| 2 | [Dark Terminal](style-2-dark-terminal.md) | 优 | 良 | 良 | 开发者文档、深色页面、运维主题 | 打印和投影环境需要检查对比度 |
| 3 | [Blueprint](style-3-blueprint.md) | 优 | 良 | 优 | 正式技术文档、工程审查 | 网格背景不适合表格式或放射式布局 |
| 4 | [Notion Clean](style-4-notion-clean.md) | 良 | 优 | 优 | 内嵌文档、SOP、密集关系图 | 视觉强调较弱，需要靠层级和标签表达重点 |
| 5 | [Glassmorphism](style-5-glassmorphism.md) | 良 | 良 | 差 | 产品演示、少节点概念图 | 透明效果会降低时序、ER、状态等密集图可读性 |
| 6 | [Warm Editorial](style-6-claude-official.md) | 良 | 良 | 良 | 说明性材料、温和的演示风格 | 暖色相不应被用于表达未经定义的业务语义 |
| 7 | [Clean Green](style-7-openai.md) | 优 | 优 | 优 | API 文档、白底报告、精确关系图 | 节点过多时白底细线容易显得拥挤 |

“密集语义图”指 `sequence`、`state-machine`、`er-diagram` 和 `use-case`。样式适配只影响视觉呈现，不扩大这些图型的语义支持范围。

## 推荐规则

1. 没有品牌或媒介要求时使用 Style 1。
2. 正式工程审查优先 Style 3；密集白底文档优先 Style 4 或 Style 7。
3. 深色页面使用 Style 2；Style 5 只用于节点较少、展示优先的图。
4. Style 6、Style 7 分别是本技能自有的暖色编辑风和绿色极简风，仅为设计语言参考，不是任何第三方“官方风格”。
5. 无论选择哪种样式，数据流、控制流、读写和反馈语义都应以标签、线型和图例为准，不能仅依赖颜色。

## Style 8 状态

[Style 8 Dark Luxury](style-8-dark-luxury.md) 是保留的实验性设计参考。`generate-from-template.py` 不接受 Style 8 或 `dark-luxury`，因此：

- 不把 Style 8 列为可生成选项；
- 不在交付承诺中推荐 Style 8；
- 不绕过生成器手工拼接 SVG 来冒充已验证输出。

如未来正式实现 Style 8，应先把它纳入输入校验、安全净化、回归样例和视觉 QA，再更新本矩阵。
