# Intelligence Hub: 战略情报深度简报 [{{ date }}]
> 生成时间: {{ timestamp }} | 数据源: Intelligence Hub V5.0

## 📝 今日核心洞察
{{ insights }}

## 核心判词 (Punchline)
{{ punchline }}

## 战略锚点：二阶推演 (Digest)
{{ digest }}

## 📈 市场动态 (Market Watch)
{{ market }}

{% if adversarial_audit %}
## 🛡️ 对抗性红队审计 (Adversarial Audit)
**[Devil's Advocate]**
{{ adversarial_audit.devil_advocate }}

**[Blind Spots]**
{{ adversarial_audit.blind_spots }}

*Confidence Score: {{ adversarial_audit.confidence_score }}/100*
{% endif %}

## 🏆 今日必读 Top 10
{% for item in top_10 -%}
### {{ loop.index }}. [{{ item.title }}]({{ item.url }})
- **来源**: {{ item.source }} | **战略权重**: {{ item.score }}
- **中文摘要**: {{ item.summary }}...
{% if item.reason %}- **推荐理由**: {{ item.reason }}{% endif %}

{% endfor %}

## 🗂️ 全量分组资讯清单
{% for cat_name, items in grouped_list.items() -%}
{% if items -%}
### {{ cat_name }}
{% for item in items -%}
- **[{{ item.title }}]({{ item.url }})**
{% if item.desc %}  > *简介*: {{ item.desc }}...{% endif %}
{% endfor %}

{% endif %}
{%- endfor %}

## 📊 数据概览
| 数据源 | 状态 | 抓取数量 |
| :--- | :--- | :--- |
{% for row in data_table_rows -%}
| {{ row.source }} | {{ row.status }} | {{ row.count }} |
{% endfor %}


---
## 📂 归档记录
- **归档路径**: {{ save_path }}
- **状态**: Persistent (Awaiting Meta-Analysis)
