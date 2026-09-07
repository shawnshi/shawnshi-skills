---
name: personal-health-analysis
description: 用于本地优先分析 Garmin 睡眠、HRV、心率、压力与多维健康趋势，生成报告或零外联面板，检查数据质量及按显式请求管理同步。仅提供非诊断信息；登录、同步、轨迹下载等动作需独立授权。
metadata:
  version: "11.6.2"
---

# Garmin 健康数据分析

提供请求窗口内、非位置化、非诊断性的个人健康观察；不生成健康总分或训练、医疗、日程决策。

## 关键权限与失败边界

- 本目录是唯一健康运行时权威。个人日记或认知复盘调用时，先运行 `<SKILL_PYTHON> scripts/runtime_authority.py --config runtime-authority.json`；仅 `ok=true` 才继续。权威、入口哈希或代理绑定漂移返回 `HEALTH_RUNTIME_AUTHORITY_MISMATCH`，停止读取、同步与回退，禁止运行代理目录脚本。
- 显式调用仅授权本次请求窗口和用途所需健康指标；默认最近 14 天（`N=14`），用户缩小时从其要求，不为分析资格扩窗。普通面板默认五组件；综合分析默认全面画像。详细指标、最小字段及新鲜度单条记录例外见运行前提与本地分析合同，默认不读位置、活动标识/名称/描述、原始轨迹或认证材料。
- 本地优先、只读、失败关闭。本地 `no_data` 后、同窗口、同组件仅有一次受限云只读回退；`partial` 继续本地，数据库变化、Schema 或其他 `read_error` 不得当作无数据回退。不得跳过本地、扩大组件或削弱数据库/WAL/SHM 前后全量哈希门。
- `--allow-health-data` 与回退时的 `--allow-network` 是本次命令能力门，不可删除或跨命令/窗口/用途复用。登录、认证探测、令牌写入、同步、轨迹下载及额外持久化需独立明确授权，保留 `--allow-token-write`、`--allow-sync`、`--allow-download`。日记/复盘新鲜度与持续自动同步只沿已有授权门，不由分析授权推导。
- 数据命令前按[运行前提](references/workflow_contract.md#运行前提)绑定同一解释器并通过对应模式预检；仅 `RUNTIME_READY` 继续，否则 `RUNTIME_DEPENDENCY_UNAVAILABLE`，不安装、不联网补包、不静默切换解释器。清单不是签名，不能替代权限或内容哈希校验。

## 按请求逐步披露

只读命中的分支；不把所有参考资料设为必读。

| 请求 | 执行前读取 |
| --- | --- |
| 单指标、摘要、健康画像、个人趋势/睡眠规律 | [本地分析](references/workflow_contract.md#本地分析)；解释指标时读 [health_analysis.md](references/health_analysis.md)，全面画像时读 [health_profile.md](references/health_profile.md) |
| 数据质量、缺失、覆盖或设备时期核验；任何分析结果解释 | [数据质量](references/workflow_contract.md#数据质量)：设备/固件/厂商与分析算法时期、样本资格、缺失不补零、非独立指标与非诊断边界 |
| 离线 HTML 趋势面板或持久化 Markdown 报告 | [离线可视化与报告](references/workflow_contract.md#离线可视化与报告)及数据质量节；HTML 必须为 `garmin_chart.py` 直接输出且零外联，不用通用渲染器包装或重写 |
| 本地明确无数据后的回退，或明确要求实时来源 | [受限实时回退](references/workflow_contract.md#受限实时回退)与 [api.md](references/api.md)；扩展指标、点时查询、活动文件才读 [advanced_tools.md](references/advanced_tools.md) |
| 明确同步、启用自动同步、只读诊断同步状态或已授权新鲜度请求 | [显式同步管理](references/workflow_contract.md#显式同步管理)与 [api.md](references/api.md)；如果用户要求仅诊断、预览、不保存、试运行、不同步、禁用或移除自动同步，则保持只读，不注册或运行任务，也不写入数据库或状态文件 |
| FHIR 研究输出或外部验收 | [研究输出](references/workflow_contract.md#研究输出)、[advanced_tools.md](references/advanced_tools.md) 与 [external_acceptance.md](references/external_acceptance.md)；仅显式本地 JSON、研究确认，不联网、不宣称临床互操作 |

## 真实完成条件

- 回显实际请求/观测日期、来源、新鲜度、逐项覆盖、样本与资格、失败关闭原因；观察、解释与不能判断的事项分开，不把末日缺失写成整个窗口无数据。
- 报告含“整体评价”“后续建议”；仅用户请求报告/面板才保存同批次 MD/HTML 并返回绝对路径，默认拒绝覆盖。普通问答不自动落盘，状态目录不是保存授权；完整输出/归档及单一脱敏自动同步状态例外见对应分支。
- 同步不能仅凭退出码报成功，须完成目标库指纹与请求窗口覆盖复核；FHIR 本地包装/调用方材料一致不等于外部验收。未验证真实链路时明确说明，不以合成测试或 dry-run 代替。

避免伪精确评分。比较个人基线时说明基线窗口和算法；没有足够历史数据时，不给出趋势结论。不得推荐药物、补剂或剂量，不得要求强制训练、停止训练、取消会议、修改闹钟或禁止决策。

## 医疗安全边界

- 不诊断、不开药、不调整处方，也不把穿戴设备数据称为临床级证据。
- 不根据消费级设备分数推断感染、炎症、免疫状态、认知能力或职业表现；只可按来源描述厂商已有分数，不自行合成准备度总分或行动分区。
- 出现胸痛、严重呼吸困难、晕厥、疑似中风、持续极端心率或用户描述的其他急症信号时，停止常规分析并建议立即联系当地急救服务。
- 对持续异常、明显症状或影响生活的变化，建议咨询合格医疗人员，并携带原始数据。
- 不自动保存、同步或注册健康洞察。长期存储或共享必须说明数据、目的和目标位置，并取得明确授权。
