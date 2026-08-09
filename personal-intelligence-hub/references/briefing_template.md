# Intelligence Hub Briefing [{{ date }}]
> Generated: {{ generated_at }} | Topic: {{ topic }} | Region: {{ region }}
> Window: {{ window.start }} — {{ window.end }} ({{ window.timezone }})

{% if urgent_signals %}
## Urgent Signals
{% for signal in urgent_signals -%}
- **{{ signal.title }}**: {{ signal.action }}
{% endfor %}
{% endif %}

## Punchline
> **{{ punchline }}**

## Weaver Insights
{{ insights }}

## Strategic Digest
{{ digest }}

## Action Levers
{% for lever in action_levers -%}
- **[{{ lever.domain }}]** {{ lever.task }}
  - Owner type: {{ lever.owner_type }}
  - Trigger: {{ lever.trigger }}
  - Indicator: {{ lever.indicator }}
{% endfor %}
{% if not action_levers %}- 暂无证据充分的行动项。{% endif %}

## Market Watch
{{ market }}

## 领域配比
- **默认比例**：技术 {{ (mix.default_ratio.technology * 100) | round | int }}% / 医疗数字化 {{ (mix.default_ratio.healthcare_digital * 100) | round | int }}%
- **当日比例**：技术 {{ (mix.effective_ratio.technology * 100) | round | int }}% / 医疗数字化 {{ (mix.effective_ratio.healthcare_digital * 100) | round | int }}%
- **实际条数**：技术 {{ mix.actual_counts.technology }} / 医疗数字化 {{ mix.actual_counts.healthcare_digital }}
{% if mix.adjustment.applied %}- **调整原因**：{{ mix.adjustment.reason }}{% endif %}
{% if mix.supply_exception.applied %}- **候选缺口**：{{ mix.supply_exception.reason }}（未用弱资讯补足比例）{% endif %}

{% if adversarial_audit %}
## Adversarial Audit
**Counter-Case**
{{ adversarial_audit.devil_advocate }}

**Blind Spots**
{{ adversarial_audit.blind_spots }}
{% endif %}

## 技术资讯
{% set technology_items = top_10 | selectattr("primary_domain", "equalto", "technology") | list %}
{% for item in technology_items -%}
### {{ loop.index }}. [{{ item.title }}]({{ item.url }})
- **Source**: {{ item.source }} | **Event**: {{ item.event_date }} | **Published**: {{ item.published_at }} | **Retrieved**: {{ item.retrieved_at }}
- **Level**: {{ item.intelligence_level }} | **Confidence**: {{ item.confidence }}
- **领域**：技术{{ (" | **高影响触发依据**：" ~ item.major_signal_reason) if item.major_signal else "" }}
- **Fact**: {{ item.fact }}
- **Connection**: {{ item.connection }}
- **Deduction**: {{ item.deduction }}
- **Actionability**: {{ item.actionability }}
- **Summary**: {{ item.summary }}
{% if item.reason %}- **Why it matters**: {{ item.reason }}{% endif %}

{% endfor %}
{% if not technology_items %}- 当前窗口内没有通过来源核验的技术信号。{% endif %}

## 医疗数字化资讯
{% set healthcare_items = top_10 | selectattr("primary_domain", "equalto", "healthcare_digital") | list %}
{% for item in healthcare_items -%}
### {{ loop.index }}. [{{ item.title }}]({{ item.url }})
- **Source**: {{ item.source }} | **Event**: {{ item.event_date }} | **Published**: {{ item.published_at }} | **Retrieved**: {{ item.retrieved_at }}
- **Level**: {{ item.intelligence_level }} | **Confidence**: {{ item.confidence }}
- **领域**：医疗数字化{{ (" | **高影响触发依据**：" ~ item.major_signal_reason) if item.major_signal else "" }}
- **Fact**: {{ item.fact }}
- **Connection**: {{ item.connection }}
- **Deduction**: {{ item.deduction }}
- **Actionability**: {{ item.actionability }}
- **Summary**: {{ item.summary }}
{% if item.reason %}- **Why it matters**: {{ item.reason }}{% endif %}

{% endfor %}
{% if not healthcare_items %}- 当前窗口内没有通过来源核验的医疗数字化信号。{% endif %}

{% if grouped_list %}## Extended Watchlist
{% for cat_name, items in grouped_list.items() -%}
{% if items -%}
### {{ cat_name }}
{% for item in items -%}
- **[{{ item.title }}]({{ item.url }})** [{{ item.date }}]
{% if item.desc %}  > {{ item.desc }}{% endif %}
{% endfor %}

{% endif %}
{%- endfor %}
{% endif %}

## Data Gaps
{% for gap in data_gaps -%}
- {{ gap }}
{% endfor %}
{% if not data_gaps %}- 无已知数据缺口。{% endif %}
