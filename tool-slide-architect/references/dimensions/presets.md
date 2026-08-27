# Style presets

优先从 [../styles/index.json](../styles/index.json) 选择一个 `Style_ID`，只读取相应文件。下表与索引一一对应；维度文件用于少量定制，不是默认加载项。

| Style_ID | 精确路径 | 适用场景 |
|---|---|---|
| `anti-gravity` | `references/styles/anti-gravity.md` | 创新、科技主题、发布演讲 |
| `refined-minimal` | `references/styles/refined-minimal.md` | 高管汇报、作品集、战略表达 |
| `pixel-art` | `references/styles/pixel-art.md` | 游戏、少儿教育、创意内容 |
| `vintage` | `references/styles/vintage.md` | 历史、文化、品牌传承 |
| `corporate` | `references/styles/corporate.md` | 商务、提案、管理层汇报 |
| `fantasy-animation` | `references/styles/fantasy-animation.md` | 叙事、教育、创意演示 |
| `scientific` | `references/styles/scientific.md` | 科研、医学、学术内容 |
| `blueprint` | `references/styles/blueprint.md` | 架构、工程、技术评审 |
| `dark-atmospheric` | `references/styles/dark-atmospheric.md` | 主题演讲、品牌叙事 |
| `clinical-deep-blue` | `references/styles/clinical-deep-blue.md` | 医疗、临床、医院高管汇报 |
| `intuition-machine` | `references/styles/intuition-machine.md` | 技术机制、研究、复杂系统 |
| `chalkboard` | `references/styles/chalkboard.md` | 教学、工作坊、教程 |
| `dark-room-standard` | `references/styles/dark-room-standard.md` | 暗场演讲、产品发布 |
| `editorial-infographic` | `references/styles/editorial-infographic.md` | 解释型内容、政策、研究摘要 |
| `notion` | `references/styles/notion.md` | 仪表盘、产品、进展汇报 |
| `watercolor` | `references/styles/watercolor.md` | 健康、教育、温和叙事 |
| `vector-illustration` | `references/styles/vector-illustration.md` | 解释、教育、品牌展示 |
| `logical-light-blue` | `references/styles/logical-light-blue.md` | 架构、路线图、业务规划 |
| `bold-editorial` | `references/styles/bold-editorial.md` | 发布会、主旨演讲、品牌展示 |

## Dimension routing

- 信息量调整：读取 [density.md](density.md)。
- 情绪与色彩调整：读取 [mood.md](mood.md)。
- 背景与表面质感调整：读取 [texture.md](texture.md)。
- 字体与语气调整：读取 [typography.md](typography.md)。

使用 `Style_ID: custom` 时仍需完整填写 `STYLE_INSTRUCTIONS`。任何定制都不得移除必要引用、保密标记、可访问性或经授权品牌元素。
