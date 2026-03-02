# Strategic Deduction & TRL Evaluation Framework

This reference document defines the specific logic and high-level evaluation criteria that the `digital-health-lectures-scout` skill must adhere to when analyzing front-line medical research.

## 1. 技术成熟度剥离标准 (Technology Readiness Level - TRL Extraction)

大模型在阅读底层《Nature》或《JAMA》等文献时，禁止使用笼统的溢美之词。必须如同顶级审核员一般，从中抽取**硬性数据指标**，并将其强制锚定为以下三大成熟度阶段之一：

- **阶段一：纸面概念 (Conceptual & Pre-clinical)**
  - *特征*: 动物实验（In-vivo/In-vitro）、极小样本的回顾性数据测试、纯理论推演架构。
  - *判定*: 距离临床落地遥遥无期，但在科学层面上可能改变未来范式。

- **阶段二：算法打榜 (Algorithm Benchmarking / Retrospective Hit)**
  - *特征*: 往往具备较高的 AUC/F1-Score，但仅在特定医院的**单一数据集**（或公开的 MIMIC 数据集）上进行过封闭的回顾性测试（Retrospective study）。
  - *判定*: 存在极高的过拟合（Overfitting）和泛化能力灾难风险，短期不具备铺开价值。

- **阶段三：临床可用 (Clinical Deployment Ready / Prospective Validation)**
  - *特征*: **前瞻性双盲实验 (Prospective, double-blind)**，或者跨机构的**多中心大样本量验证 (Multi-center validation)**。
  - *判定*: 这种级别的 AI 突破或数字化研究，属于即刻可以进入医疗器械审批或医院真实采购清单的标准。

## 2. 中国医疗重力场测试 (China Localization Test)

任何海外顶级的方案，若要在卫宁健康 (Winning Health) 的版图内产生价值，必须经过以下三道“重力场”压测：

### 2.1 医保控费杠杆 (DRG/DIP 2.0 Impact)
- *追问*: 医院当前的核心痛点是“在医保总额预算下不亏本”。这个 AI 技术是增加医院的检查成本（如昂贵的创新早筛），还是能大幅降低平均住院日（ALOS）、精准预测并发症以避免医保扣款？

### 2.2 合规准入与数据孤岛 (Compliance & Data Silos)
- *追问*: 该研究是否极其依赖跨院区的明文数据互通？如果是，在《数据安全法》和当前中国严苛的医疗数据不出院出省政策下，其部署难度如何？
- *追问*: 具备辅助诊断级别的 AI 需要国家药监局 (NMPA) 的三类器械证。这项研究的技术链路是否满足国内临床验证的标准？

### 2.3 商业模式与卫宁映射 (OpEx vs. CapEx / MSL & ACE)
- *追问*: 当前卫宁推动的是基于 WiNEX 的订阅制（OpEx）、统一数据底座与代理矩阵（ACE）。这项新技术如果是碎片化的（单点跑在科室的一体机上），那么它对于大集成商是威胁还是并购标的？
- *追问*: 我们是否应该迅速将其概念抽取为“语义层标签 (MSL)”，纳入 `Logic Lake` 作为底层资产，让卫宁的 Copilot 具备类似的能力壁垒？
