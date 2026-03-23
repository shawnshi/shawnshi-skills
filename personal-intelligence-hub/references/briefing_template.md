# Intelligence Hub: 战略情报深度简报 [{{ date }}]
> 生成时间: {{ timestamp }} | V6.5 Lobster Architecture

{% if urgent_signals %}
## 🚨 紧急预警 (Urgent - 10s Read)
{% for signal in urgent_signals -%}
- **{{ signal.title }}**: {{ signal.action }}
{% endfor %}
{% endif %}

## 📝 核心战略判词 (Punchline)
> **{{ punchline }}**

## 💡 二阶洞察与织网 (Weaver Insights)
{{ insights }}

## ⚖️ 战略锚点：二阶推演 (Digest)
{{ digest }}

## 🎯 行动杠杆点 (Action Levers)
{% for lever in action_levers -%}
- **[{{ lever.domain }}]**: {{ lever.task }}
{% endfor %}

## 📈 市场动态 (Market Watch)
{{ market }}

{% if adversarial_audit %}
## 🛡️ 红队博弈审计 (Reviewer Audit)
**[冲突存证]**
{{ adversarial_audit.devil_advocate }}

**[盲点预警]**
{{ adversarial_audit.blind_spots }}
{% endif %}

## 🏆 今日必读 Top 10 (Arbiter Filtered)
{% for item in top_10 -%}
### {{ loop.index }}. [{{ item.title }}]({{ item.url }})
- **来源**: {{ item.source }} | **战略权重**: {{ item.score }}
- **中文摘要**: {{ item.summary }}
{% if item.reason %}- **推荐理由**: {{ item.reason }}{% endif %}

{% endfor %}

## 🗂️ 全量清单与二跳推理
{% for cat_name, items in grouped_list.items() -%}
{% if items -%}
### {{ cat_name }}
{% for item in items -%}
- **[{{ item.title }}]({{ item.url }})** [{{ item.date }}]
{% if item.desc %}  > *简介*: {{ item.desc }}{% endif %}
{% endfor %}

{% endif %}
{%- endfor %}

---
## 📂 认知资产归档
- **路径**: {{ save_path }}
- **过滤**: 已自动拦截 {{ noise_count }} 条低权重/未翻译英文信号，确保简报纯净度。
- **同步**: Vector Lake (Consolidation PENDING)
