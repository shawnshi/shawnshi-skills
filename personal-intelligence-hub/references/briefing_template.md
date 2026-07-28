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

{% if adversarial_audit %}
## Adversarial Audit
**Counter-Case**
{{ adversarial_audit.devil_advocate }}

**Blind Spots**
{{ adversarial_audit.blind_spots }}
{% endif %}

## Top 10 Signals
{% for item in top_10 -%}
### {{ loop.index }}. [{{ item.title }}]({{ item.url }})
- **Source**: {{ item.source }} | **Event**: {{ item.event_date }} | **Published**: {{ item.published_at }} | **Retrieved**: {{ item.retrieved_at }}
- **Level**: {{ item.intelligence_level }} | **Confidence**: {{ item.confidence }}
- **Fact**: {{ item.fact }}
- **Connection**: {{ item.connection }}
- **Deduction**: {{ item.deduction }}
- **Actionability**: {{ item.actionability }}
- **Summary**: {{ item.summary }}
{% if item.reason %}- **Why it matters**: {{ item.reason }}{% endif %}

{% endfor %}
{% if not top_10 %}- 当前窗口内没有通过来源核验的高价值信号。{% endif %}

## Extended Watchlist
{% for cat_name, items in grouped_list.items() -%}
{% if items -%}
### {{ cat_name }}
{% for item in items -%}
- **[{{ item.title }}]({{ item.url }})** [{{ item.date }}]
{% if item.desc %}  > {{ item.desc }}{% endif %}
{% endfor %}

{% endif %}
{%- endfor %}

## Data Gaps
{% for gap in data_gaps -%}
- {{ gap }}
{% endfor %}
{% if not data_gaps %}- 无已知数据缺口。{% endif %}
