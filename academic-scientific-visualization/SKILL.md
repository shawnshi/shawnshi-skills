---
name: academic-scientific-visualization
description: 设计、生成、重构和严格审查科研论文图表，覆盖多面板布局、统计证据门禁、误差与显著性标注、防色盲编码、期刊尺寸、字体、矢量或光栅导出及成品 QA。用户要求科研作图、论文插图、投稿图、统计图重构、现成图质量审查或整套 manuscript figures 时使用；不用于商业仪表板、一般演示排版、普通图片生成或对证据图像做生成式编辑。
---

# 学术科学可视化

交付可追溯的科研图，而不是只生成一个能打开的文件。所有认证基于成品文件和明确证据；缺信息、缺工具或规则过期时保持 NOT_CHECKED。

## 1. 先确定任务模式

选择且只选择一个主模式：

- create：从原始或汇总数据生成图。
- redesign：重构已有图，明确应保留与可改变内容。
- visual_audit：只审查现成成品，不重算数据。
- manuscript_set：统一多张论文图和跨图编码。

读取 [references/task_contracts.md](references/task_contracts.md) 获取该模式的最小输入契约。只询问会改变设计或认证结果的缺失项。目标期刊未定时使用 generic-draft，并明确它不能获得 journal_verified。

## 2. 在绘图前设置门禁

### 数据与统计

确认来源、变量、单位、分析单位、样本量、缺失与排除规则、变换和不确定性定义。不要猜测数据、检验、误差类型、效应量、p 值或校正方法。

需要推断性标注时读取 [references/design_and_statistics.md](references/design_and_statistics.md)，并先运行 [scripts/statistics_gate.py](scripts/statistics_gate.py)。只接受结构化统计证据；禁止接受裸星号或手写 p 值作为输入。复杂统计模型只消费外部已验证结果，本技能不替代统计分析。

### 隐私与图像完整性

处理敏感、未发表、患者或原始科研图像时读取 [references/research_integrity.md](references/research_integrity.md)：

- 最少字段、去标识、本地处理；直接标识不得进入标签、文件名、清单或缓存。
- 敏感任务要求人工去标识复核、package_data=false、一次性缓存，以及宿主级出站网络隔离。只有外部运行环境已确认隔离时才设置 ACADEMIC_SCIVIZ_NETWORK_ISOLATED=1；脚本自身不是网络沙箱。
- 原始显微图、凝胶和印迹图只读；只做完整记录的全局调整、裁切、旋转、通道映射和经校准比例尺。
- 禁止选择性擦除、克隆、局部增强、未声明拼接和生成式证据编辑。
- 示意图明确标记为 schematic。

不把受限数据发给外部服务或无必要的子代理。需要扩大共享范围时先取得用户明确授权。

### 环境与字体

在导入 Matplotlib 前设置无头后端和任务级可写缓存：

    MPLBACKEND=Agg MPLCONFIGDIR=/tmp/figure-mpl-cache

运行 [scripts/font_preflight.py](scripts/font_preflight.py) 检查依赖、外部工具、字体解析和已声明字形。流水线构图后还会从实际 Figure 重新提取标题、轴标签、分类刻度、图例和注释；未在 target.labels 声明的文字或缺字形均为 FAIL。存在中文、日文或韩文时读取 [references/fonts_and_cjk.md](references/fonts_and_cjk.md)。静默字体回退不是通过。缺包、字体、TeX 或系统工具时只报告缺口；未经授权不要安装。

## 3. 设计信息编码

读取 [references/design_and_statistics.md](references/design_and_statistics.md) 选择与科学问题匹配的图型。优先展示原始点、效应量和区间；柱形图不能替代分布。

读取 [references/encoding_accessibility.md](references/encoding_accessibility.md) 设计配色与冗余编码：

- 颜色、形状、线型和面板标签都有固定语义，类别不能只靠颜色区分。
- 每个轴写变量与单位；对数轴、截断、归一化和平滑显式说明。
- 多面板统一字体、刻度、图例、比较尺度和阅读顺序。
- 误差棒在图注中定义为 SD、SEM、CI 或其他量。

配色、样式、期刊规则只从 [assets/visual_profiles.json](assets/visual_profiles.json) 读取。使用 [scripts/style_presets.py](scripts/style_presets.py) 的 publication_style 上下文，避免污染 Notebook 或并发任务的全局 rcParams。不要在新脚本中复制规则表或色值。

## 4. 固定两阶段流水线

### Preview

先用 [scripts/figure_pipeline.py](scripts/figure_pipeline.py) 生成 150 DPI PNG 预览。保持与终稿相同的物理画布和布局，同时生成灰度与三类色觉缺陷近似预览。预览不获得期刊认证。

对本地预览执行真实视觉检查，至少确认：

- 裁切、遮挡、留白和标签密度；
- 最终尺寸下字体、线宽、点和图例可读；
- 乱码、缺字形和面板顺序；
- 灰度及色觉缺陷预览中的可区分性；
- 图中数值、排序、聚合和标注与数据或统计证据一致。

将六项结果和本次 input_hash 写入 visual_review.json。输入、脚本、规则、字体或依赖变化后必须重新复核；旧记录不能复用。近似色觉模拟不是自动可访问性认证。

### Final

视觉修正后再运行 final。final 缺少与本次 input_hash 绑定的六项视觉复核时必须返回 NOT_CHECKED，命令行以非零状态退出。导出使用 [scripts/figure_export.py](scripts/figure_export.py)，默认：

- 不使用 tight 裁切改变画布物理尺寸；
- 向量文件不把内嵌光栅 DPI 降到 300；
- 多格式先写同目录临时文件，全部验证通过后原子替换；
- 导出报告用 artifacts_committed 区分本轮已提交成品与校验失败后保留的旧文件，失败轮次不得把旧文件登记为本轮产物；
- 父目录不存在时显式失败，除非调用者明确 create_dirs；
- 不覆盖已有文件，除非调用者明确 overwrite；
- TIFF 按 Profile 扁平化为 RGB 或灰度、移除 Alpha 并使用 LZW。
- target.requirements 可叠加比期刊更严格的 RGB、精确 PPI 和单帧要求。

成品 QA 读取实际文件而非 Figure 对象：

- 文件签名、非零大小和页数；
- PDF 页面框、字体嵌入、非 Type 3 字体和内嵌光栅有效 PPI；
- PNG/TIFF 像素、DPI、物理尺寸、颜色模式和 Alpha；
- TIFF 压缩和单帧；
- Profile 格式、宽度、高度、文件大小和规则新鲜度。

PDF 字体或内嵌图像检查工具不可用时返回 NOT_CHECKED。EPS/SVG 无法证明字体嵌入时也保持 NOT_CHECKED；不要伪报通过。

## 5. 期刊规则

需要期刊终稿时读取 [references/journal_profiles.md](references/journal_profiles.md)。Profile 必须精确匹配期刊、投稿阶段和图件类型，未知项禁止回退。规则过期、官方来源缺失或目标栏目另有要求时，查询当前官方作者指南，并记录链接与核验日期；不要依赖二手博客或搜索摘要。

当前机器 Profile 只覆盖 nature-final、plos-one-final、ieee-journal 和 generic-draft。其他期刊先按 generic-draft 设计，除非已用当前官方指南建立并验证新 Profile。

## 6. 状态语义

只使用以下交付状态：

- draft：尚未完成视觉检查，或使用通用/未认证规则。
- visually_checked：六项视觉检查全部 PASS，但不满足完整期刊认证。
- journal_verified：当前官方 Profile、任务契约、环境/字体、统计门禁、全部成品必检项和视觉检查均 PASS。

聚合规则固定：任一必检项 FAIL 即 FAIL；无 FAIL 但存在必检 NOT_CHECKED 即 NOT_CHECKED；只有全部必检项 PASS 才通过。不得用一个笼统 compliant 布尔值掩盖未检查项，也不保证期刊接收。

## 7. 交付

按 [references/task_contracts.md](references/task_contracts.md) 输出标准目录：

- final：终稿；
- preview：原色、灰度、色觉缺陷预览和图组联系表；
- source：可复现脚本与去路径化 Job；
- captions：逐图图注；
- stats：获准打包的结构化统计证据；
- qa：契约、预检、统计和成品逐项 PASS/FAIL/NOT_CHECKED；
- manifest.json：Profile 哈希、输入哈希、成品/被审文件哈希、来源哈希和复现级别。

Job 不内嵌观测值。原始数据默认不打包；只有明确授权且运行期来源完整性门禁通过时才复制为去标识文件，门禁失败不得把可能已变更的来源写入交付包。只有 manifest 的 reproducibility_level=self_contained_inputs 才能称为输入自包含，否则应称为代码与哈希包。input_hash 绑定规则、脚本、依赖、字体和输入内容，不绑定文件所在目录；移动自包含复现包不应改变它。说明数据变换、分析单位、样本量、误差定义、统计检验与校正、关键设计选择、状态及所有未满足项。

## 能力边界

本技能适合常规二维统计图、多面板图、基于源数据或脚本的重构和文件 QA。它能用前后哈希发现运行期间的来源改写，但不能防止恶意脚本先改再还原，也不替代只读挂载和宿主网络隔离。它不能从位图可靠恢复原始数据、鉴定科研图像真实性、替代复杂统计建模、保证期刊接收，也不能用生成式编辑修改证据图像。超出边界时明确报告并建议合适的人工或专业复核。
