# Intelligence Hub Briefing [{{ date }}]
> Generated: {{ timestamp }} | V8.0 Strategic Briefing System

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
{% endfor %}

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
- **Source**: {{ item.source }} | **Score**: {{ item.score }} | **Level**: {{ item.intelligence_level }} | **Confidence**: {{ item.confidence }}
- **Fact**: {{ item.fact }}
- **Connection**: {{ item.connection }}
- **Deduction**: {{ item.deduction }}
- **Actionability**: {{ item.actionability }}
- **Summary**: {{ item.summary }}
{% if item.reason %}- **Why it matters**: {{ item.reason }}{% endif %}

{% endfor %}

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

---
## Archival
- **Path**: {{ save_path }}
- **Noise filtered**: {{ noise_count }}
- **Runtime dir**: {{ runtime_path }}
