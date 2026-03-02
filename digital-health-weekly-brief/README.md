# 🌐 Digital Health Weekly Brief (数字健康战略侦察兵)

> **版本体系**: V2.1 (架构级优化)
> 
> **定位**: 专为“卫宁健康(Winning Health)战略咨询总经理”打造的高级医疗数字化情报雷达。

---

## 🎯 核心使命 (Mission Statement)
本技能彻底摒弃了传统的“行业新闻聚合”模式。它是一台带有红队约束（Anti-Hallucination）和精准制导能力的战略情报收割机。

它的核心使命是在每周内，自动扫荡全球顶级咨询公司（MBB）、技术智库（Gartner/IDC）与全球宏观卫生组织（WHO/OECD）的最新发布，提炼出真正具备颠覆意义的 **“Signal (信号)”**，并结合国内 DRG 控费、互联互通等国情，输出具有杀伤力的 **“Impact (商业冲击)”** 与 **“Action (卫宁应对指令)”**。

---

## 🛠️ 核心架构与原理解释 (Architecture)

本技能完全遵循 Gemini Skills 的最佳解耦实践，物理架构如下：

```text
digital-health-weekly-brief/
│
├── SKILL.md                 # 🧠 核心大脑：负责触发逻辑、情报分层与 S-I-A 推演模型指令
├── README.md                # 📖 当前说明文档
│
├── resources/               # 📦 静态资源库
│   └── template.md          # 输出模版：内含高管级视觉呈现约束（GitHub Alerts 定制排版）
│
└── examples/                # 🎓 In-Context Learning (Few-Shot 弹药库)
    └── DHWB-Reference.md    # 满分实战战报（2026-03-02），用于强制锁定大模型的冷峻高管文风
```

### 为什么需要 `resources/` 与 `examples/`？
原版单文件（Monolithic）架构容易导致大模型在大段 Prompt 中陷入“指令遗忘”或“幻觉冲突”。通过将模板和实战参考隔离到专用文件夹中，大模型在每次执行分析前都会被强制拉取**基准对齐 (Alignment)**，从而确保了数百份报告在行文风格和业务深度上的绝对一致性。

---

## 🧠 S-I-A 战略推演框架 (The S-I-A Model)

技能的核心在于其硬编码的分析框架，确保产出并非假大空的废话：

*   **📡 Signal (信号去水)**: 强制用最短的篇幅，剥离原报告的公关词汇，提炼底层业务或技术逻辑（下限 300 字）。
*   **💥 Impact (护城河冲击)**: 深度推演该趋势（如 Agentic AI、SaaS转型）将如何“降维打击”传统 HIT（医疗信息化）厂商的卖软件模式，或者如何改变医院的付费意愿。
*   **⚔️ Action (卫宁应对指令)**: 相比于抽象概念，报告必须落位到卫宁的核心资产——如 **MSL (医疗语义层)**、**ACE (Agent协调引擎)** 或 **WiNEX 产品线**上的具体行动指南（与 Impact 合计至少 800 字）。

---

## 🚀 如何使用 (Usage)

1.  **唤醒技能**: 
    在 Gemini 控制台中，输入类似指令：
    - _“执行本周的 Digital Health Weekly Brief”_
    - _“帮我生成本周的医疗行业机构研报”_
    - _“运行数字健康周报技能”_

2.  **静待输出**:
    技能会自动计算本周一至周日的范围，调用互联网搜索工具，横扫各大目标源的官网，执行精炼过滤。

3.  **获取战报**:
    一份结构化、饱含战略深度的 Markdown 报告将被自动生成并存入您的个人知识库归档目录下：
    `C:\Users\shich\.gemini\MEMORY\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`

---
*Developed by Gemini Agentic Reasoning | Framework V2.1*
