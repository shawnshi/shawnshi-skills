---
name: mentat-dream-cycle
description: Mentat 系统的全自动夜间潜意识引擎 (V8.0 Fully Autonomous)。强制挂载于凌晨定时器，实现无人值守的防重知识入湖、垃圾回收和技能源码级自愈。
triggers: ["触发 Dream Cycle", "运行夜间清洗", "清理热记忆", "执行系统清洗", "Run dream cycle"]
---

# Mentat Dream Cycle (潜意识演化与系统清洗) V8.0 Fully Autonomous

> **Vision**: 真正的自治系统不需要在半夜叫醒主脑。Dream Cycle 现已接入 ReAct 底层感官与闭环自愈引擎。

## ⚙️ The Autopilot Mechanism (全自动机制)

该系统已被设置为**凌晨 3:00 的 Cron 守护进程**。
它将在后台静默执行以下三阶进化（无需人类或主代理干预）：

1. **防重热清洗 (Deduplicated Diarization)**：
   Python 引擎会在提取 `hot_facts.md` 的实体时，自动调用 `Query_Vector_Lake` 探针查询历史图谱。
   如果发现该知识点已存在，直接在内存里合并（Merge）更新，而不是无脑制造垃圾节点。

2. **基因级代码自愈 (Autonomous Self-Healing)**：
   当扫描到 `failure_batch.jsonl` 中存在某项技能反复报错时，系统**不再要求主代理手工拉起子代理**。
   它会直接在 Python 底层跨进程拉起 `mentat-skill-creator`，让另一个大模型自己去阅读错误日志并覆盖出故障的 Python 源码。醒来时，破损的技能已经修好。

3. **拓扑压缩 (Orphan GC)**：
   清理死循环与断头图谱，完成一天的认知代谢。

## 🚀 手动唤醒 (Manual Override)

通常您永远不需要阅读这篇文档。但如果经历了剧烈的系统震荡，您可以强行注入指令手动启动清洗：

```bash
$env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/mentat-dream-cycle/scripts/run_dream_cycle.py"
```

*注意：执行后不要等待所谓的“人工核对报告”，系统会自己把一切搞定，您只需继续您的战略工作即可。*
