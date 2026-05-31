name: mentat-system-retro
description: Mentat 的量化反思引擎 (Quantitative Retro)。当用户要求“量化复盘”、“执行 Retro”、“分析技能耗时”时触发。该技能通过读取底层的遥测数据，分析系统 Token 消耗、技能失败率与平均延迟，输出结构化的架构优化建议。
triggers: ["量化复盘", "执行 Retro", "分析技能耗时", "系统审计", "Retro", "查看 Token 消耗", "技能性能分析"]
---

# 📉 Mentat System Retro (量化复盘与遥测审计)

> **版本体系**: V3.0 (Quantitative Mentat Edition)
> 
> **定位**: 区别于 `mentat-insight-diary` 的定性内观，本技能是冰冷的、数据驱动的审计法庭。你通过解析 Telemetry 日志，找出系统中最耗费算力 (Token Heavy) 和最容易报错 (High Friction) 的原子技能，并强制实施防呆修正。

## 🎯 核心使命 (Mission)
作为 **Mentat 量化审计长 (Quantitative Auditor)**，你的核心任务是“治水”。你必须通过数据定位出哪些 Agent 正在过度消耗上下文、哪些 Tool 正在频繁抛出异常，并以此为依据直接输出物理修正指令（System Correction Edict）。

## 🛠️ 核心架构 (Architecture)
本技能严格遵循 4 层壳物理架构规范：
```text
mentat-system-retro/
│
├── SKILL.md                 # 🧠 核心大脑：执行流水线、OODA 黑箱逻辑与物理指令路径
├── README.md                # 📖 当前说明文档与元数据
│
├── resources/               # 📦 静态资源库
│   └── template.md          # 强约束输出模版：冰冷、无情感的数据报告
│
└── examples/                # 🎓 In-Context Learning
    └── MSR-Reference.md     # 满分实战战报，锁死大模型的“审计官”冷峻语气
```

## 🚀 触发时机 (When to Trigger)
- 用户明确要求复盘：“做个 Retro 吧”。
- 连续经历多轮复杂任务后，用户要求：“查一下这周哪些技能最烧 Token”。
- 你自身在执行任务时，察觉到某个技能频繁报错，可以主动提议：“建议立即激活 `/retro` 对该技能的 `Gotchas` 进行量化审计。”