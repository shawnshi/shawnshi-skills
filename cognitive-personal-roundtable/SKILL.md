---
name: cognitive-personal-roundtable
description: A high-density dynamic analytical framework (V8.0) that orchestrates real-world historical or contemporary figures into a "tension network" to scrutinize any topic. Now powered by Python-driven isolated LLM calls (True Persona Isolation) without subagent I/O locks.
---

<strategy-gene>
Keywords: 圆桌, 多人物辩论, tension network, 思想碰撞
Summary: 组织历史或当代人物张力网络，对议题进行多视角攻防。
Strategy:
1. 锁定议题、人物和辩论轮数。
2. 调用底层 Python Orchestrator 触发内存级独立调用，彻底避免多角色融合崩溃。
3. 获取最终合成的结论和拓扑图。
AVOID: 禁止主代理亲自写对话；禁止手动写临时碎片文件；严禁跨进程拉起子代理。
</strategy-gene>

# Cognitive Personal Roundtable (V8.0: Atomized Orchestrator Edition)

“所有的执行偏差，本质上都是认知的偷懒。在这里，我们通过真实思想维度的对抗，萃取决策的晶核。”

## 🛑 核心架构升级告警 (V8.0)
**注意**：曾经依赖主代理手动分发文件、手动合并、或在一个 Prompt 中分饰多角的模式已**全面废弃**。
现在，所有的对抗逻辑均已下沉到 `run_roundtable.py` 中。脚本会在后台为每一位入座人物开辟独立的 LLM 推理序列，以保证 100% 的人格锋芒和算力纯净度。

## Workflow

### 1. 确认开题 (Initialization)
当用户要求“开启圆桌”或“引入视角”时：
- 与用户确认【核心议题】。
- 挑选 3-4 位极具张力的历史/现实人物（例如：马斯克 vs 查理·芒格 vs 斯大林）。

### 2. 执行真·内存圆桌 (Execute Engine)
你只需通过命令行启动底层的管线脚本，将舞台彻底交给它：
```bash
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-personal-roundtable\scripts\run_roundtable.py" --topic "你的议题" --personas "人物A, 人物B, 人物C" --rounds 2
```

### 3. 宣读判词 (Archiving)
- 脚本执行完毕后，读取输出的临时 Markdown 文件，向用户呈递最终的主持人判词与 ASCII 拓扑结构。
- 可选：向用户询问是否需要加入新的人物并开启下一轮。

## Output Contract
不要长篇大论地将所有人的发言全部重复打印。你只需要把最核心的分歧点、拓扑图，以及最终决策呈现给用户。
