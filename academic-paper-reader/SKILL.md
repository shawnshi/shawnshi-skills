name: academic-paper-reader
description: 学术论文透视、溯源与精读 (V4.0: Cognitive Assault & River Lineage Edition)。读论文不是做学术，是猎取思想与观察问题的演化。结合“倒读溯源法”，把别人的发现拆解成问题演化线，剥去复杂的学术外衣，直击第一性原理。强制执行“费曼化”、“毒舌去魅”与“差异驱动叙事”。
triggers:["读论文", "拆解论文", "溯源分析", "paper river", "分析这篇论文的演化", "学术透视"]
---

# SKILL.md: 学术论文透视与精读 (V3.0: Cognitive Assault Edition)

> **核心法则**: 读论文不是做学术，是猎取思想。把别人的发现拆解成自己能用的认知，同时剥去其复杂的学术外衣，直击第一性原理。

## 1. 格式约束 (Format Stack)

### md 语法
- 加粗用 `*bold*`（单星号），禁止 `**bold**`
- 标题层级从 `*` 开始，严格遵循模板不跳级。

### 模板权威性与基准对齐
- 输出结构**必须**严格依据 `resources/template.md`。
- 生成前**必须**参考 `examples/APR-Reference.md` 满分战报，强行拉齐“毒舌”与“费曼化”的冷峻文风。禁止参考其他历史文件。

### Denote 物理归档规范
- 时间戳格式：`YYYYMMDDTHHMMSS` (如 `20260401T103000`)
- 可读时间格式：`YYYY-MM-DD Day HH:MM` (如 `2026-04-01 Wed 10:30`)
- 文件名规范：`paper-{简短标题}--{YYYYMMDDTHHMMSS}.md`
- 输出物理路径：强制使用 `write_file` 写入 `C:\Users\shich\.gemini\MEMORY\wiki\Huggingface-Daily-Papers\`

## 2. 红线 (Mandatory Check)

1. *口语检验* — 你会这样跟朋友介绍一篇论文吗？如果不会，立即重写。学术腔是默认敌人。
2. *锚点撑全文* — 必须找到一个具象的中心隐喻（一张图、一个动作、一个场景），让所有概念围绕它生长。
3. *推理外显* — 模拟“一个人想明白的过程”，而非“呈现结果”。用“既然 A 是这样，那 B 能不能也这样？”带着读者推演。
4. *零术语* — 先用大白话落地，再顺带提术语名。能用两个字不用的四个字（“他们做了个东西” > “本文提出了一种框架”）。
5. *变形替代定义* — 解释概念关系时，优先用“把 A 变形为 B”而非“A 和 B 是 XX 关系”。
6. *不填充* — 删掉所有“值得注意的是”、“近年来随着”等废话。每句都要干活。
7. *落点在能用* — 给出“这意味着你可以___”，而非“这让我们重新思考___”。
8. *问题为轴* — 叙事主线是"问题怎么演化的"，论文只是配角。每篇论文的讲解重心必须是"它和前一篇的差异在哪"，而不是独立介绍。
9. *逻辑不断链* — 从祖师爷到目标论文，因果链条不能断。让读者感受到"前人留下了坑，所以这篇才不得不这么做"。
10. *诚实溯源* — 找不到 5 层就说找到几层。不确定就说不确定，严禁为了凑数编造引用批判关系。

## 3. 写作原则 (Writing Principles)
- **第一性原理透视** — 剥去学术外壳，看其本质。这个解决方案背后的物理/数学/逻辑本质是什么？
- **旧瓶装新酒** — 它是在哪个旧概念上做了什么微调？找出它的原型。
- **推理外显** — 模拟"一个人想明白的过程"，而非呈现"想明白之后的结果"。
- **落点在能用** — 给出"这意味着你可以___"，而非"这让我们重新思考___"。

## 4. 执行工作流 (OODA Pipeline)

###[Step 1: 目标锁定与核心批判提取]
- 获取目标论文：读取本地 PDF 或抓取网页。
- **锁定宿敌**：仔细阅读引言和 Related Work。找到它明确宣称“前人方法 X 有问题 Y”的地方。锁定它作为 Baseline 或主要批判对象的 1-3 篇核心前序论文。

###[Step 2: 逆向递归溯源 (Recursive Traceback)]
- 针对 Step 1 锁定的核心前序论文，调用搜索/阅读工具，**向上递归追溯 3-5 层**（或直到该领域的奠基论文）。
- **每层只抓三个核心**：标题/年份、它的核心解法、它对更前人的批判点。只追最相关的那条主线，严禁发散。

###[Step 3: 前沿延伸 (Forward Extension)]
- 反向搜索：目标论文之后，有没有新论文在批判/改进它？（谁又打了它的脸？）
- 找到最相关的 1-3 篇后续论文，提取同样的 Gap -> Fix 逻辑。

###[Step 4: X-Ray 核心透视与双图构建 (The Blackboard)]
在脑海中完成信息压缩，准备绘制两张纯 ASCII 字符图：
1. **溯源地图 (Traceback Map)**：以时间线展示 `[Paper A] --(问题X)--> [Paper B] --(问题Y)--> [目标论文]` 的演化链。
2. **逻辑拓扑 (Topology)**：针对目标论文，绘制其第一性原理映射图（输入 -> 核心干预 -> 输出）。

###[Step 5: 费曼式演化叙事 (Feynman Evolutionary Narrative)]
- **差异驱动叙事**：从最老的论文开始正向讲述。不要独立拼凑摘要，必须以“上一篇留下了什么坑（场景说明） -> 这一篇怎么填坑（类比说明） -> 这一篇又制造了什么新坑”为模板推进。
- 然后对目标论文进行常规的 V3.0 解剖（方法论、数据、结果、第一性概念拆解）。

### [Step 6: 博导审稿与启发 (Mentat Audit)]
- **博导判决**：结合演化史给出毒舌点评。它究竟是真正推动了河流向前，还是在一条快干涸的支流上自嗨？
- **启发点**：
    - **迁移**：某个零件能升级我的系统吗？
    - **混搭**：能产生化学反应吗？
    - **反转**：它颠覆了我的什么默认假设？该停下什么？

## 5. Telemetry & Metadata (Mandatory)
使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。JSON 结构：`{"skill_name": "academic-paper-reader", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 6. 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
- **[CRITICAL]** 严禁无差别全量通读 PDF。必须强制优先执行基于 `start_line`/`end_line` 或抽取器的 Abstract/Conclusion 获取，仅在遇到关键逻辑断层时，实施局部的文本检索拉取。
- **[CRITICAL]** DO NOT generate invalid Org-mode timestamps. Use EXACTLY `YYYYMMDDTHHMMSS` for `#+identifier:` and `[YYYY-MM-DD Day HH:MM]` for `#+date:`.
- **[CRITICAL]** DO NOT use overly academic language like "The study aims to...". Use direct, active voice like "They built X to fix Y."