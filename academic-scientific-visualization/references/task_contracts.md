# 任务契约与交付

只在确定任务模式后收集对应信息，不要让用户填写与任务无关的字段。

## 四种模式

| 模式 | 适用情形 | 额外必需输入 |
|---|---|---|
| create | 从原始或汇总数据生成图 | 分析单位、样本量、变量/单位、缺失与排除、变换、误差定义 |
| redesign | 在已有图上重构表达 | 原图、应保留内容、可改变内容；最好同时给数据或脚本 |
| visual_audit | 检查现成文件 | 最终文件、使用场景、目标尺寸或期刊、图注 |
| manuscript_set | 统一一组论文图 | 图号/顺序、共享样式、跨图比较关系、每图来源 |

共同必需输入：来源与敏感级别、科学问题、投稿阶段、目标期刊或 generic-draft、图件类型、全部展示文本、字体、文件名。

## Job 最小结构

    {
      "schema_version": 1,
      "mode": "create",
      "question": "比较两组随时间的响应变化",
      "source": {
        "kind": "raw_data",
        "sensitivity": "unpublished",
        "data_path": "data.csv",
        "package_data": true,
        "package_data_authorized": true,
        "deidentified": true,
        "external_sharing": false
      },
      "target": {
        "profile": "nature-final",
        "submission_stage": "final",
        "figure_type": "combination",
        "column": "single",
        "formats": ["pdf"],
        "requirements": {"color_mode": "RGB", "exact_ppi": 600, "single_frame": true},
        "font": {"family": "DejaVu Sans"},
        "labels": ["Time (h)", "Response (a.u.)", "Control", "Treatment"]
      },
      "analysis": {
        "analysis_unit": "animal",
        "sample_size": {"control": 12, "treatment": 12},
        "missing_data": "none",
        "transformation": "none",
        "uncertainty": "95% CI",
        "variables": [{"name": "time", "unit": "h"}],
        "annotations_requested": false
      },
      "delivery": {"base_name": "figure1"},
      "caption": "Figure 1. ..."
    }

绘图脚本提供 build_figure(job) -> matplotlib.figure.Figure；图组脚本提供 build_figures(job) -> {figure_id: Figure}。预览和终稿命令：

    MPLBACKEND=Agg MPLCONFIGDIR=/tmp/figure-mpl-cache python scripts/figure_pipeline.py \
      --job job.json --plot-script plot.py --stage preview --output figure_bundle

    MPLBACKEND=Agg MPLCONFIGDIR=/tmp/figure-mpl-cache python scripts/figure_pipeline.py \
      --job job.json --plot-script plot.py --stage final \
      --visual-review visual_review.json --output figure_bundle

visual_review.json 必须包含本次 qa/figure_qa.json 对应的 input_hash、检查者和六个 PASS 项：crop、overlap、legibility、glyphs、accessibility、data_alignment。输入、脚本、规则、字体或依赖发生变化后，旧视觉复核自动失效。

visual_audit 也先生成原色、灰度和色觉缺陷预览，再执行 final。final 缺少有效视觉复核时，状态为 NOT_CHECKED，CLI 返回非零；不能仅凭成品文件属性合规就宣称完成审核。

Job 只放元数据和路径，不内嵌观测值。create 模式至少声明一个文件路径和 package_data 布尔值；只有 package_data=true、package_data_authorized=true 且运行期来源完整性门禁通过时，才把非敏感来源复制为去标识的 input_XX 文件。门禁失败时不得打包可能已被脚本改写的来源。manifest 的 reproducibility_level 只有在输入已完整打包时才是 self_contained_inputs，否则为 code_and_hashes_only。input_hash 按内容而非绝对或相对目录名计算，自包含包迁移后重跑应保持一致。

manuscript_set 的每个 figure 项必须包含 id、source_ref、question 和 caption；顶层还必须包含 shared_style、cross_figure_rules 和至少一个可哈希来源路径。流水线逐图写图注。

## 标准交付包

    figure_bundle/
    ├── final/
    ├── preview/
    ├── source/
    ├── captions/
    ├── stats/
    ├── qa/
    │   ├── job_validation.json
    │   ├── source_preflight.json
    │   ├── preflight.json
    │   ├── statistics_validation.json
    │   ├── runtime_figure_checks.json
    │   └── figure_qa.json
    └── manifest.json

原始数据默认不打包。只有数据安全、授权明确且复现确有必要时才单独加入，并在清单中声明。敏感任务不保留流水线缓存。

敏感任务还要求：privacy_review={status: PASS, reviewer: ...}、package_data=false，以及由宿主环境确认出站流量已禁用后设置 ACADEMIC_SCIVIZ_NETWORK_ISOLATED=1。该变量是外部隔离的记录，不是脚本自身的网络沙箱；无法确认时停止运行任意绘图代码。
