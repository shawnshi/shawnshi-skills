# SKILL.md: Healthcare Industry Radar (医疗行业雷达) V3.0 - Gemini Standard

---
name: healthcare-industry-radar
description: 【战略级特供】用于对特定HIT行业巨头检索本周最新异动，输出自带 S-T-C (Signal-Threat-Countermeasure) 实战分析的战报。**Make sure to use this skill whenever the user asks about HIT competitors, medical software news, or healthcare IT market dynamics (especially regarding Epic, Oracle, InterSystems, Winning Health, Neusoft, Donghua, B-Soft, Yidu, or DHC), even if they don't explicitly explicitly say 'radar' or 'S-T-C'. When asked to summarize recent news for these companies, trigger this skill.**
---

## 1. 触发逻辑 (Trigger)
- **触发指令**: 当用户提及上述核心公司的近期动向、要求行业资讯更新、或直接调用雷达技能时触发。
- **时间范围 (🔴 强约束)**: 严格限定在**本周之内（周一至周日）**。要求 LLM 交叉验证新闻的时间戳。无异动则留白。

## 2. 核心战区与结构化圈层侦察 (The Strat-Scan Workflow)

_指令：必须使用大模型联网搜索能力。针对两大目标阵营进行检索时，必须叠加核心过滤圈层的关键词。_

*请仔细阅读附带的参考文件：针对公司列表、必搜过滤关键词和S-T-C高阶推演标准，请**必须查阅并严格遵循 `references/stc_framework.md`** 中的详尽定义。*

## 3. 输出格式铁律 (Formatting Ironballs)

**ALWAYS use this exact template pattern for the final output.**

```markdown
# 医疗行业雷达 (Adv. Healthcare Industry Radar) - [日期 YYYYMMDD]

> [!IMPORTANT]
> **本周雷达最高预警 (Executive Summary)**
> [用150字概括本周最危险或最具颠覆性的行业动向。必须是基于S-T-C推演出的商业本质。]

---



## 战略深度推演 (The S-T-C Deduction)

### 圈层：[引用 stc_framework.md 中的圈层名称，如：底层产品线重构]

#### [公司名]: [一句话总结其动作核心]
- **Signal**: [事实陈述，去水，如：耗资XX收购了某垂类厂商]
- **Threat (护城河透视)**: [灵魂拷问：踩中了什么宏观杠杆？是否威胁卫宁产品线？]
- **Countermeasure (卫宁反击指令)**: [具体兵力部署，如：加速某个子产品落地，联动大厂防御等。]
```
---
## 核心资讯清单 (Key Intelligence List)

| 资讯分类 (Category) | 标题 (Title) | 一句话概述 (Overview) | 真实来源链接 (Link) |
| :--- | :--- | :--- | :--- |
| [如：资本异动] | [如：某某公司收购某某] | [简明扼要的一句话概括事件] | [链接标题的形式] |

---

## 4. 战报生成与冷冻归档 (Archiving)
1. **物理路径**: 生成结果强制保存在 `C:\Users\shich\.gemini\MEMORY\HealthcareIndustryRadar` 目录中。
2. **文件命名**: 产出的 Markdown 文件名严格为 `DHWB-Radar-YYYYMMDD.md`。

---
*Optimized following Gemini Skill Creator Best Practices.*
