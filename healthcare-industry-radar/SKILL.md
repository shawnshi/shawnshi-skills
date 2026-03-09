# SKILL.md: Healthcare Industry Radar (医疗行业雷达) V3.0 - Gemini Standard

---
name: healthcare-industry-radar
description: 用于检索全球及本土特定 HIT 行业巨头本周最新异动。主Agent将作为 Orchestrator，并发调度 3 个雷达哨兵 (global_hit_scout, china_hit_scout, winning_health_baseline) 扫描国际巨头、国内竞对及卫宁自身动态。汇总后，严格依据 `references/stc_framework.md` 输出自带 S-T-C (Signal-Threat-Countermeasure) 实战分析的商业战报。
tools: [china_hit_scout, global_hit_scout, winning_health_baseline, write_to_file]
triggers:["卫宁健康最新动向", "东软近期中标", "Epic行业新闻", "调用雷达扫描", "扫描竞争对手新闻", "HIT市场动态", "本周医疗IT战报"]
---

## 1. 触发逻辑 (Trigger)
- **触发指令**: 当用户提及上述核心公司的近期动向、要求行业资讯更新、或直接调用雷达技能时触发。
- **时间范围 (🔴 强约束)**: 严格限定在**本周之内（周一至周日）**。要求 LLM 交叉验证新闻的时间戳。若无重大异动，则针对目标厂商的存量优势执行“模拟攻击推演”。


## 2. 核心战区与并发雷达侦察 (Parallel Radar Recon Workflow)

_指令：你现在是 Orchestrator。当前系统时间是 `{{current_date}}`，你必须以此准确计算出过去 7天的精确日期范围（如 YYYY-MM-DD 至 YYYY-MM-DD），然后利用并行函数调用机制（Parallel Tool Calling），**同时触发**以下 3 个 Subagents，将精确的日期窗口作为参数（绝不可模糊）传给它们。_

### 第一阶段：多维度并发扫描 (Multi-Agent Dispatch)
1. **调用 `global_hit_scout`**: 侦察 Epic, Oracle,intersystem 等海外巨头的降维打击技术或商业并购。
2. **调用 `china_hit_scout`**: 侦察国内友商（东软、东华、创业、医渡等）的中标、专利、人事、股权及大模型试点。
3. **调用 `winning_health_baseline`**: 侦察卫宁健康自身的最新动作，建立己方防线基石。

### 第二阶段：交叉验证与逻辑对齐 (Data Validation & Alignment)
- 等待 3 个哨兵的数据回传。
- 🔴 **红队约束**: 检查每一条资讯的时间戳是否属于“7天窗口”。
- **逻辑对齐 (Logic Alignment)**: 强制将 `global_hit_scout` 发现的国际趋势与 `china_hit_scout` 的本土动态进行关联。判断国内厂商是否在进行“同态映射”或“降维模仿”。

### 第三阶段：S-T-C 战略推演 (The S-T-C Deduction)
*指令：本阶段极其重要。你必须读取缓存中的 `references/stc_framework.md`。结合搜集到的真实情报，代入卫宁健康高管视角进行推演。*

- **Signal (信号)**: 剥离公关词汇，用一句话还原商业实质。若无新闻，则标记为“存量固化信号”。
- **Threat (威胁/防御性想象力)**: 剖析该动作对卫宁 WiNEX 的实质威胁。若无新闻，则模拟：若对手在当前宏观红利（如医保新规）下发起突袭，卫宁的护城河是否存在漏洞？
- **Countermeasure (反制建议)**: 给出具体的战术应对建议。禁绝废话，必须包含具体的子产品阻击或算力/生态联合策略。


## 3. 输出格式铁律 (Formatting Ironballs)

**ALWAYS use this exact template pattern for the final output.**

```markdown
# 医疗行业雷达 (Adv. Healthcare Industry Radar) - [日期 YYYYMMDD]

> [!IMPORTANT]
> **本周雷达最高预警 (Executive Summary)**
> [用500字概括本周最危险或最具颠覆性的行业动向。必须是基于S-T-C推演出的商业本质。]

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

| 资讯分类 (Category) | 标题 (Title)           | 一句话概述 (Overview)      | 真实来源链接 (Link) |
|:--------------------|:-----------------------|:---------------------------|:--------------------|
| [如：资本异动]      | [如：某某公司收购某某] | [简明扼要的一句话概括事件] | [链接标题的形式]    |

---

## 4. 战报生成与冷冻归档 (Archiving)
1. **物理路径**: 生成结果强制保存在 `{root}\MEMORY\HealthcareIndustryRadar` 目录中。
2. **文件动作 (🔴 强约束)**: 你必须调用 `write_to_file` 工具，将最终生成的 Markdown 战报物理写入到上述目录。文件名严格为 `DHWB-Radar-YYYYMMDD.md`。

---
*Optimized following Gemini Skill Creator Best Practices.*
