name: academic-paper-reader
description: 学术论文透视与精读 (V3.0: Cognitive Assault Edition)。读论文不是做学术，是猎取思想。把别人的发现拆解成自己能用的认知，剥去其复杂的学术外衣，直击第一性原理。强制执行“费曼化”和“毒舌去魅”。
triggers: ["读论文", "拆解论文", "解析这篇paper", "总结arxiv", "提取论文洞察", "学术透视"]
---

# 📖 Academic Paper Reader (学术论文透视与精读)

> **版本体系**: V3.0 (Cognitive Assault Edition)
> 
> **定位**: 专为剥离学术黑话、提取第一性原理设计的论文精读引擎。

## 🎯 核心使命 (Mission)
读论文不是做学术，是猎取思想。本技能强制大模型扮演冷酷的“知识拆解者”：
1. **剥除学术外壳**：拒绝“本文提出了一种基于XXX的框架”，强制翻译为“他们做了一个什么东西”。
2. **第一性原理透视**：找出解决方案背后的物理/数学/逻辑本质，以及它是哪个旧概念的微调（旧瓶装新酒）。
3. **落点在能用**：给出“这意味着你可以___”，而非“这让我们重新思考___”。

## 🛠️ 核心架构 (Architecture)
```text
academic-paper-reader/
│
├── SKILL.md                 # 🧠 核心大脑：触发逻辑、工作流与格式约束
├── README.md                # 📖 当前说明文档
│
├── resources/               # 📦 静态资源库
│   └── template.md          # 强约束输出模版：Denote Org-mode 语法头 + Markdown 正文
│
└── examples/                # 🎓 In-Context Learning
    └── APR-Reference.md     # 满分实战战报，锁死“毒舌”与“费曼化”的冷峻文风
```

## 🚀 如何使用 (Usage)
输入包含 arXiv 链接或 PDF 路径的指令，例如：
- _“帮我拆解这篇论文：https://arxiv.org/abs/xxxx.xxxxx”_
- _“读一下这篇 PDF，重点看它的实验部分。”_