---
name: personal-health-analysis
description: 分析用户授权访问的 Garmin 本地数据，生成睡眠、HRV、心率、压力、身体电量、运动负荷、Markdown 报告和 HTML 趋势面板。用于“分析睡眠”“查看 HRV/心率/压力”“评估身体状态”“生成健康报告或趋势图”等请求；仅提供非诊断性健康信息，不替代医生诊断或急救服务。
---

# Garmin 健康数据分析

## 环境与授权

- 需要 Windows 或兼容的 Python 环境、可用的 Garmin 本地数据库及已完成的账户授权。
- 先确认用户允许读取相关健康数据和时间范围。不要扩大到未请求的指标、活动轨迹或历史周期。
- 需要指标解释时按需读取 `references/health_analysis.md`、`references/api.md` 或 `resources/clinical_guidelines.json`。后者只是可选的方法配置，不是临床事实库；配置未启用或缺少来源、日期、地区、人群和用途时，只做未分类观察，不使用硬编码回退阈值。

## 工作流程

1. 明确问题、时间范围和期望输出：单项指标、日度摘要、趋势分析或图表。
2. 使用相对路径运行最小必要脚本：
   - 单项或汇总：`python scripts/garmin_data.py <sleep|hrv|heart_rate|body_battery|stress|summary> --days <N>`
   - 描述性准备度或基线变化：`python scripts/garmin_intelligence.py <readiness|baseline_change|insight_cn> --days <N>`
   - 长期图表：`python scripts/garmin_chart.py dashboard --period <PERIOD>`
3. 在 Windows 控制台乱码时设置 `PYTHONIOENCODING=utf-8`。不要自动安装依赖、登录账户或修改数据库。
4. 检查数据采集时间、缺失率、设备佩戴空档和脚本错误。数据陈旧时说明快照日期；只有用户明确授权后才运行 `scripts/sync_health_data.py`，并说明同步会访问外部服务。
5. 将观察值、可能解释和不能判断的事项分开。`baseline_change` 只描述相对个人基线的变化，不对应疾病风险；`readiness` 在没有启用且可追踪的配置时不生成分数。任何脚本结果都不得决定训练、补剂、日程或重要决策。
6. 仅在指标多、周期长且任务可独立拆分时使用子代理；传递最小化、去标识的数据。未经用户许可不得把健康数据发送给外部服务。
7. 用户要求生成持久化报告或面板时，先运行 `python scripts/report_output.py --days <N>`，取得同一批次的 `markdown` 和 `html` 绝对路径。
8. 将最终 Markdown 正文写入返回的 `markdown` 路径；生成面板时把返回的 `html` 路径传给 `garmin_chart.py --output <HTML_PATH>`。返回实际存在的本地绝对路径链接。

## 报告归档契约

- Garmin 分析产出的 `.md` 和 `.html` 默认保存在当前工作区的 `output/personal-health-analysis`。
- `GARMIN_REPORT_DIR` 可覆盖默认目录；`GARMIN_OUTPUT_DIR` 仅作为旧版兼容项。用户显式指定的输出路径优先。
- 同一次分析的 Markdown 和 HTML 必须共享文件名主干，例如 `health_analysis_7days_20260727_093045.md` 与 `.html`。
- 临时 JSON、数据库副本、FIT/GPX 活动文件、认证令牌和调试日志不得写入报告归档目录；中间文件放入当前会话的 `scratch`。
- 普通问答或单项指标查询不自动落盘。用户提出“生成报告、面板、大屏”即授权保存该次请求的 MD/HTML，不扩大为数据同步、外部分享或长期洞察注册。

## 输出

- 数据范围、来源和新鲜度
- 关键指标及变化
- 可能解释与证据限制
- 可选的一般性恢复或训练考虑事项，由用户结合主观感受和专业意见决定
- 需要升级处理的风险
- 持久化任务的 Markdown 与 HTML 绝对路径

避免伪精确评分。比较个人基线时说明基线窗口和算法；没有足够历史数据时，不给出趋势结论。不得推荐药物、补剂或剂量，不得要求强制训练、停止训练、取消会议、修改闹钟或禁止决策。

## 医疗安全边界

- 不诊断、不开药、不调整处方，也不把穿戴设备数据称为临床级证据。
- 不根据消费级设备分数推断感染、炎症、免疫状态、认知能力或职业表现；评分与分区只能作为明确标注方法和来源的实验性描述。
- 出现胸痛、严重呼吸困难、晕厥、疑似中风、持续极端心率或用户描述的其他急症信号时，停止常规分析并建议立即联系当地急救服务。
- 对持续异常、明显症状或影响生活的变化，建议咨询合格医疗人员，并携带原始数据。
- 不自动保存、同步或注册健康洞察。长期存储或共享必须说明数据、目的和目标位置，并取得明确授权。
