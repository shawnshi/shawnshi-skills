---
name: tool-web-slide
description: 将演示内容构建为可在浏览器运行、验证和交付的 HTML 幻灯片。用于网页演示、交互叙事、电子杂志式幻灯片、离线演示包或单文件 HTML；不用于原生 .pptx 或仅需故事线的任务。
---

# Web Slide Builder

## 交付边界

- 产物是 HTML 演示，不得称作或冒充原生 PowerPoint。用户明确需要可编辑 `.pptx` 时，使用 `Presentations`；只需要叙事结构或逐页蓝图时，使用 `tool-slide-architect`。
- HTML 可以按需导出 PDF；PDF 是静态快照，不保留网页交互。
- 默认使用可移交的 `bundle`：`index.html` 加本地资产。只有用户明确要求单文件，或交付环境需要时，才使用 `standalone`，并将运行所需 CSS、JavaScript、字体和图像内联或嵌入。

## 开工前锁定契约

先读取 [references/delivery-contract.md](references/delivery-contract.md)，再用用户已经提供的信息建立 `deck.config.json`。以下选择会实质改变结果，缺失且无法可靠推断时才询问：

- 受众、使用场景、核心决策、语言、标题、页数或内容范围；
- 画布比例、目标浏览器与操作系统、演示分辨率；
- `bundle` 或 `standalone`、联网或离线、交互和 PDF 要求；
- 品牌、模板、可复用素材及素材使用权；
- 数据敏感级别、脱敏要求、允许的数据处理边界；
- 证据策略、引用格式、事实截止日期和客户验收要求。

没有相反要求时，采用 16:9、当前操作系统上的 Chromium、1920×1080 验证、`bundle`。外部客户材料默认按“标准客户”交付；明确为内部低风险草稿时可用“快速内部”；投标、政府/董事会汇报、受控内网、正式留档或高风险数据使用“高保障”。三种模式的必做项和验收条件以交付契约为准。高保障必须设置 `offlineRequired: true`、`evidencePolicy: required`，逐页完成视觉 QA，并验收 PDF。

将不明来源的患者信息、个人信息和内部材料视为受限数据：不上传外部服务，不引用远程资产，不擅自改变用途。只有 `offlineRequired: false` 且用户允许时才可使用远程资源，并在交付说明中列出依赖域名。事实、假设和建议应可区分；医疗、政策、商业和量化结论按契约记录来源与日期，未核实内容不得包装成事实。

## 按需读取

- 只读取选定主题：`built-in-skills/style-magazine.md`、`built-in-skills/style-swiss.md` 或 `built-in-skills/style-winning-clinical.md`。
- 需要规划多种页面骨架时读取 `references/layout-patterns.md`。
- 用户明确要求继承既有设计系统时读取 `built-in-skills/use-design-system.md`，并只复用获准的令牌和资产。
- 随技能发布的 `references/layouts.json`、`references/components.json` 和实际 CSS 是可实现能力的真源；文档示例不得覆盖这些约束。

## 标准流程

1. **依赖预检**：在技能目录运行 `npm run preflight -- <index.html>`（新项目可省略路径；需要提前把浏览器能力作为硬门禁时增加 `--require-browser`）。使用现有依赖；不得自动执行 `npm install`、`npx playwright install`、关闭浏览器沙箱或修改系统。Node 必须为 18 或更高版本；Playwright 只在视觉 QA 和 PDF 导出时需要。快速内部和标准客户缺浏览器时预检给出能力警告，高保障、显式 `--require-browser` 或最终交付验证仍会阻断；应说明缺项和受影响步骤，等待用户授权或交付明确标注未完成的结果。root 环境中的 Chromium 若不能以沙箱启动，应改用非 root 运行环境；不得自动设置 `WEB_SLIDE_ALLOW_NO_SANDBOX=1`，只有用户理解并明确接受风险后才可临时使用。
2. **初始化**：运行 `npm run init -- <projectDir> --title "..." --theme <theme> --aspect <aspect> --mode <bundle|standalone> --profile <profile> --target-browser <browser> --target-os <os> --width <pixels> --height <pixels>`。已有项目只有在目标明确且使用 `--force` 不会覆盖用户文件时才允许覆盖。
3. **分片设计**：先锁定内容地图、设计令牌、导航和页面契约，再实现页面。只有页面组相互独立时才并行；每个分片必须有唯一文件或页码所有权，公共样式、配置和导航只由主线合并。
4. **构建**：运行 `npm run build -- <projectDir>`。每页保留一个主要结论，标题、证据、图表和讲稿形成清楚层级；只使用选定主题已实现的组件和规范布局。`bundle` 必须复制全部本地运行资产；`standalone` 不得留下本地文件引用。
5. **静态 QA**：运行 `npm run check -- <output/index.html>`，生成 `qa-report/qa-report.json`。不得以警告替代阻断性错误。页面身份、画布、布局、标题、资源引用、离线约束和证据标记必须满足交付契约；禁止内联事件处理器及页面片段中的不受信任脚本。`standalone` 只允许内容与技能内 canonical asset 一致、由构建器以 `data-web-slide-asset` 标记并转义的内建运行时脚本。
6. **视觉 QA**：运行 `npm run visual -- <output/index.html> <output/qa-report>`。脚本按档位自动执行代表页、每类布局或全页覆盖，并为截图和报告记录内容哈希。默认只允许当前本地静态服务器、`data:`、`blob:` 和 `about:` 请求，检查文字溢出、遮挡、对比度、图表与图片、导航、动画、目标分辨率和缩放。只有配置明确为 `offlineRequired:false`、档位不是高保障且用户明确授权联网时，才可增加 `--allow-network`，并记录依赖域名。发现问题后重新构建并重复静态与视觉 QA。
7. **PDF**：用户要求或交付模式规定时，运行 `npm run export -- <output/index.html> <output/deck.pdf>`；成功时同时生成 `qa-report/pdf.json`。联网规则与视觉 QA 相同；`offlineRequired:true` 或高保障档位不得用 `--allow-network` 绕过。确认字体与图片加载完成、页数与 HTML 一致、无空白页、控制栏或裁切，并抽查复杂页。
8. **最终门禁与交付**：运行 `npm run verify -- <output/index.html>`。该命令把当前 HTML、清单、静态报告、视觉覆盖、截图和 PDF 的哈希、目标环境及网络策略交叉核对，并生成 `qa-report/delivery.json`；退出非零时不得宣称档位验收完成。技能本身发生变化时另运行 `npm test` 和 `npm run manifest -- . --check`。最终链接必须指向实际文件，并明确未通过或未执行的门禁，不能把“脚本已运行”表述成“页面已验收”。

## 交付物

按交付模式提供：

- `index.html` 与所需本地资产，或单一自包含 `index.html`；
- `deck.config.json` 与 `delivery-manifest.json`；
- `qa-report/` 中的静态、视觉、PDF 与最终交付验证报告，以及档位要求保留的截图；
- 按需生成并验收的 PDF；
- 面向接收方的简短交付说明，记录启动方式、目标浏览器、比例、联网条件、证据缺口和已知限制。只有成套交付确实需要时才创建说明文件，不在技能目录新增通用 README。
