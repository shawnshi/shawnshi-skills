# Layout Patterns (版式与修饰库)

本表定义了 PPT 的绝对坐标/网格版式标准。通过组合 `Primary` (主结构) 和 `Modifier` (修饰层)，创造出视觉变化丰富但不杂乱的演示文稿。
**在 `spec_lock.md` 阶段，必须从下表中挑选组合，例如 `#Primary-Split + #Mod-FloatCard`，Executor 必须按这些标识符对应的 HTML 结构生成代码，放弃原生的 relative 流水账排版。**

## 1. Primary 主结构骨架 (The Grids)
依赖 CSS Grid 实现高精度坐标。使用 `style="display: grid; grid-template-columns: ..."` 或预设的 Layout Class。

* `#Primary-Hero` (全屏主视觉): 
  包含大背景图 (100vw, 100vh) 与正中或左对齐的巨型文字块。用于封面或极具冲击力的过渡页。必须应用 `position: relative` 与内容层的绝对对齐。
* `#Primary-Split` (左右绝对分割): 
  `grid-template-columns: 1fr 1fr;`。一边是 100% 填充的出血图片，另一边是文字组。严格居中对齐，要求网格占据 100vh。
* `#Primary-TriGrid` (三分画廊):
  `grid-template-columns: repeat(3, 1fr); gap: 2rem;`。适用于列举三项并列的核心数据或观点，高度对齐，等宽分布。
* `#Primary-Focus` (黄金分割居中):
  `grid-template-columns: 1fr 2fr 1fr;` 居中的 `2fr` 用于展示单张关键图表或产品截图，两侧留白极大，文字仅作侧边或下方轻量注解。
* `#Primary-KpiScene` (全屏场景 + KPI悬浮): 
  由一张 `background-size: cover` 的满屏图像作为底宽，并在其上方绝对定位（`position: absolute`）3-4个高对比度的数据指标卡。适用于大屏汇报。
* `#Primary-ZPattern` (Z字形图文交替):
  将页面分为2到3行（Row），图文左右位置在相邻行交替（例如：第一行图左文右，第二行图右文左）。引导视线呈 Z 字形向下阅读。
* `#Primary-Gallery` (多图阵列复读):
  严格的 `grid-template-columns: repeat(4, 1fr);`。适用于展示团队成员、系列产品或竞品对比，每个格子必须保持完全相同的 DOM 结构。
* `#Primary-Architecture` (企业级分层架构):
  由下至上或由上至下排列的一系列全宽模块层 (`flex-direction: column`)，用于展示复杂的 IT 架构（如 IaaS、PaaS、SaaS、医疗大模型层）。
* `#Primary-Pathway` (临床/数据工作流):
  水平延展的流程图布局 (`display: flex; align-items: center`)，中间通过绝对定位或原生的箭头图标连接，用于展示患者就诊旅程或数据流转。
* `#Primary-Comparison` (痛点对标矩阵):
  不对称的 2 列或多列对比。通常左侧为“改造前/痛点”（红色/灰色调），右侧为“改造后/方案”（品牌蓝/高亮色）。用于凸显医疗数字化转型的 ROI。
* `#Primary-CDSSMatrix` (临床决策拦截矩阵):
  专用网格结构，底层对应 `.cdss-workflow-matrix`，用于映射临床阶段（门诊、住院、出院）与 AI 干预（预警、拦截）。
* `#Primary-EMRRadar` (电子病历评级对标):
  包含中心雷达图容器的特殊骨架，底层对应 `.emr-level5-radar`，用于呈现医院当前水平与评级要求的五维/六维雷达图对标。
* `#Primary-DataLakeFunnel` (数据湖提纯漏斗):
  倒三角式的层级归流版式，底层对应 `.data-lake-funnel`，展示 HIS/PACS/LIS 杂乱源头向下清洗汇聚成标准 CDR/ODR 的过程。
* `#Primary-PolicyGrid` (合规过级对标网格):
  双栏对齐的严密矩阵，底层对应 `.policy-compliance-grid`，将政策条款（如互联互通、国考）严丝合缝地对标至信息化系统功能点。
* `#Primary-MultiCampus` (一院多区云管边拓扑):
  轴幅式星形或分支树状版式，底层对应 `.multi-campus-topology`，中心是算力集群，边缘是各个物理分院区节点。
* `#Primary-TriTerminal` (医护患三端齐发瀑布流):
  极其严格的三等分纵向瀑布流，底层对应 `.tri-terminal-view`，隔离并列展示 Doctor、Nurse、Patient 的独占业务流。
* `#Primary-RAGTraceability` (大模型医疗可信血缘图):
  左中右穿透式网格，底层对应 `.rag-traceability-flow`。左侧为自然语言 Query，中间穿透双重知识边界透镜，右侧汇聚为带强引用的可信输出。
* `#Primary-DRGMatrix` (DRG/DIP 控费盈亏沙盘):
  四象限或双向柱状对抗网格，底层对应 `.drg-cost-matrix`，用于映射高临床价值与低消耗之间的病种结余点。
* `#Primary-HL7Bus` (集成平台与 ESB 消息总线拓扑):
  横贯页面的粗壮中央总线结构，底层对应 `.hl7-integration-bus`，上下密集挂载独立的业务子模块容器，凸显解耦能力。
* `#Primary-PDCALoop` (单病种临床质控闭环):
  环形或对称闭环网格，底层对应 `.pdca-quality-loop`，映射 P-D-C-A 四节点的闭环质控拦截流程。
* `#Primary-PatientJourney` (全生命周期慢性病时间轴):
  非线性延展的蜿蜒时间标尺，底层对应 `.patient-journey-timeline`，承载健康、发病、治疗、康复的多态视觉容器。

## 2. Modifier 修饰层 (The Decorators)
附加在 Primary 结构之上，增加视觉层次。禁止一页使用超过 2 个修饰层。

* `#Mod-FloatCard` (悬浮毛玻璃卡片):
  在全屏图或分割图上方，叠加一个带有 `backdrop-filter: blur(20px); background: rgba(255,255,255,0.7);` 的绝对定位卡片 (`position: absolute; z-index: 10;`)，放置点睛之笔的文案。
* `#Mod-HugeQuote` (超大符号底纹):
  在文字块底层放入一个透明度仅为 `0.05` 的超大引号或数字，通过绝对定位 `top: -20px; left: -10px; font-size: 200px;` 作为底纹，增加排版纵深感。
* `#Mod-DataBadge` (关键数据徽章):
  漂浮在主图表右下角的圆形或高对比度方块 (`border-radius: 50%` 或 `padding: 1rem; background: var(--brand);`)，凸显单一核心数字。
* `#Mod-Duotone` (双色调滤镜):
  对背景图片应用 `mix-blend-mode: multiply` 或使用 CSS Filter，使其融入品牌色底色中。
* `#Mod-Scrim` (平滑渐变遮罩):
  为了让大图上方的白色文字清晰可见，在图片层与文字层之间插入一层 `background: linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,0.8) 100%)`。永远优于死板的全屏半透明黑色。

## 3. 组合运用范例
在 `spec_lock.md` 的 Slide Map 中应该如此声明：
`Layout: #Primary-Split + #Mod-FloatCard`

这告诉 Executor：这页是左半边图右半边文，但在图上要再绝对定位悬浮一张半透明注解卡。 Executor 收到该指令后，必须精确翻译出对应的 DOM 层级与行内/全局 CSS grid 代码。
