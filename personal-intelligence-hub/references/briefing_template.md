# 今日资讯简报｜{{ date }}

> 生成时间：{{ generated_at }}
> 主题：{{ topic }}｜地域：{{ region }}
> 窗口：{{ window.start }}—{{ window.end }}（{{ window.timezone }}，含首尾 {{ window.days }} 个日历日）
> 运行：{{ run_id }}｜模型：{{ model_used }}｜合同：{{ schema_version }}

## 一句话判断

> **{{ punchline }}**

## 关键信号串联

{{ insights }}

## 决策摘要

{{ digest }}

## 行动杠杆

{% for lever in action_levers -%}
- **[{{ lever.domain }}] {{ lever.task }}**
  - 责任角色：{{ lever.owner_type }}
  - 启动条件：{{ lever.trigger }}
  - 检查指标：{{ lever.indicator }}
{% endfor %}
{% if not action_levers %}- 当前没有证据充分的行动项。{% endif %}

## 市场与产业观察

{{ market }}

## 领域配比

- 合同默认：技术 {{ (mix.default_ratio.technology * 100) | round | int }}% / 医疗数字化 {{ (mix.default_ratio.healthcare_digital * 100) | round | int }}%
- 本次请求：技术 {{ (mix.requested_ratio.technology * 100) | round | int }}% / 医疗数字化 {{ (mix.requested_ratio.healthcare_digital * 100) | round | int }}%（{{ mix.ratio_source }}{% if mix.ratio_reason != "none" %}：{{ mix.ratio_reason }}{% endif %}）
- 生效比例：技术 {{ (mix.effective_ratio.technology * 100) | round | int }}% / 医疗数字化 {{ (mix.effective_ratio.healthcare_digital * 100) | round | int }}%
- 目标条数：技术 {{ mix.target_counts.technology }} / 医疗数字化 {{ mix.target_counts.healthcare_digital }}
- 实际条数：技术 {{ mix.actual_counts.technology }} / 医疗数字化 {{ mix.actual_counts.healthcare_digital }}
{% if mix.adjustment.applied %}- 重大资讯调比：{{ mix.adjustment.reason }}{% endif %}
{% if mix.supply_exception.applied %}- 供给例外：{{ mix.supply_exception.reason }}（未用弱资讯补足）{% endif %}

## 技术资讯

{% set technology_items = top_10 | selectattr("primary_domain", "equalto", "technology") | list %}
{% for item in technology_items -%}
### {{ loop.index }}. [{{ item.title_zh }}]({{ item.url }})

- 原文标题：{{ item.title }}
- 来源：{{ item.source }}（{{ item.source_type }}；{{ item.corroboration_status }}）
- 日期：事件 {{ item.event_date }}（{{ item.event_date_source }}）｜发布 {{ item.published_at }}（{{ item.published_at_source }}）｜检索 {{ item.retrieved_at }}
- 访问核验：{{ item.access_check.status }} / {{ item.access_check.method }} / HTTP {{ item.access_check.http_status }}
- 等级：{{ item.intelligence_level }}｜条目置信度：{{ item.confidence }}{% if item.major_signal %}｜重大资讯：{{ item.major_signal_reason }}{% endif %}

- 事实：{{ item.fact }}
- 连接：{{ item.connection }}
- 推断：{{ item.deduction }}
- 动作：{{ item.actionability }}
- 摘要：{{ item.summary_zh }}

{% endfor %}
{% if not technology_items %}- 当前窗口没有通过质量门的技术资讯。{% endif %}
## 医疗数字化资讯

{% set healthcare_items = top_10 | selectattr("primary_domain", "equalto", "healthcare_digital") | list %}
{% for item in healthcare_items -%}
### {{ loop.index }}. [{{ item.title_zh }}]({{ item.url }})

- 原文标题：{{ item.title }}
- 来源：{{ item.source }}（{{ item.source_type }}；{{ item.corroboration_status }}）
- 日期：事件 {{ item.event_date }}（{{ item.event_date_source }}）｜发布 {{ item.published_at }}（{{ item.published_at_source }}）｜检索 {{ item.retrieved_at }}
- 访问核验：{{ item.access_check.status }} / {{ item.access_check.method }} / HTTP {{ item.access_check.http_status }}
- 等级：{{ item.intelligence_level }}｜条目置信度：{{ item.confidence }}{% if item.major_signal %}｜重大资讯：{{ item.major_signal_reason }}{% endif %}

- 事实：{{ item.fact }}
- 连接：{{ item.connection }}
- 推断：{{ item.deduction }}
- 动作：{{ item.actionability }}
- 摘要：{{ item.summary_zh }}

{% endfor %}
{% if not healthcare_items %}- 当前窗口没有通过质量门的医疗数字化资讯。{% endif %}


## 覆盖状态

- 运行状态：{{ coverage.run_status }}｜覆盖置信度：{{ coverage.coverage_confidence }}｜基线状态：{{ coverage.baseline_status }}
- 来源：尝试 {{ coverage.source_attempted }} / 成功 {{ coverage.source_succeeded }} / 失败 {{ coverage.source_failed }}（成功率 {{ (coverage.source_success_rate * 100) | round(1) }}%）
- 有效发布日期候选比例：{{ (coverage.dated_candidate_rate * 100) | round(1) }}%
{% if coverage.required_lane_failures %}- 未完成车道：{{ coverage.required_lane_failures | join("、") }}{% endif %}

{% for reason in coverage.reasons -%}
- 覆盖说明：{{ reason }}
{% endfor %}

## 候选漏斗

- 观察候选：{{ candidate_funnel.observed }}
{% for disposition, count in candidate_funnel.terminal_dispositions | dictsort -%}
- {{ disposition }}：{{ count }}
{% endfor %}

## 流程回执

- 基线 SHA-256：`{{ pipeline.baseline_sha256 }}`
- 补检：{{ pipeline.supplement_status }}
- 语义评估：{{ pipeline.semantic_review.status }}（{{ pipeline.semantic_review.reviewer_kind }}）
- 逻辑红队：{{ pipeline.red_team.status }}

{% if adversarial_audit is defined and adversarial_audit %}
## 反方审查

- 反方案例：{{ adversarial_audit.devil_advocate }}
- 盲点：{{ adversarial_audit.blind_spots }}
{% endif %}
## 数据缺口

{% for gap in data_gaps -%}
- **{{ gap.gap_id }} / {{ gap.lane }} / {{ gap.status }}**：{{ gap.description }}；影响：{{ gap.impact }}
{% endfor %}
{% if not data_gaps %}- 当前没有已知数据缺口。{% endif %}
