---
name: cognitive-book-mirror
description: 个人化认知镜像与伴读引擎。提取长文或书籍核心要点，结合过去14天日记及个人价值观体系，生成高密度的双栏伴读分析。左栏保留原旨，右栏进行毒舌映射，执行极度的交叉检验。
triggers: ["伴读这本书", "认知镜像", "双栏伴读", "结合我的日记分析这本书"]
---

<strategy-gene>
Keywords: 双栏伴读, 认知镜像, 私域映射, 毒舌幕僚
Summary: 将外部知识（EPUB/PDF）切片，在只读沙盒内同高密度私域 Context 结合，实施双栏架构输出。
Strategy:
1. Context 脱水打包：读取最近14天的 `MEMORY/raw/privacy/Diary` 记录及全局 `USER.md`/`SOUL.md`，预先组装。
2. 并发降权与映射：分块章节执行 LLM，约束 LLM 输出双栏表格；严禁 LLM 提供“建议”，只准作事实与逻辑关联。
3. 结构重组：自动合并章节后输出 `<BookName>_personalized_mirror.md`。
AVOID: 严禁将整书直接硬塞给大模型导致 OOM；严禁产生关于用户的幻觉；如果右栏对应不上，必须留空或坦白说明，绝不强行关联。
</strategy-gene>

# Cognitive Book Mirror (Native Edition)

个人化认知镜像与伴读引擎。这是一个将外部世界（书籍/长文）与内心世界（日记/价值观）强行碰撞的高密度分析机器。

## When to Use
- 当你想知道一本畅销书、一本专业书或一篇长篇报告“对我现在的生活/业务到底有什么用”时。
- 当你需要通过特定的战略视角（如过去 14 天的困惑）去穿透一本厚重的书时。

## Workflow

### 1. The Context Packing Phase
主控脚本 `scripts/orchestrate_mirror.py` 会去抓取：
- `C:/Users/shich/.gemini/USER.md`
- `C:/Users/shich/.gemini/pai/SOUL.md`
- `C:/Users/shich/.gemini/MEMORY/raw/privacy/Diary/` (最近 14 天)
打包生成 `context.md`。这绝非 RAG 检索，而是物理文件维度的粗暴组装，具有最高的业务确定性。

### 2. The Sandbox Reading Phase
脚本将目标书籍按章节切分成临时碎片，每读一章碎片，就让 Agent 结合 `context.md` 输出双栏结果。
- **左栏 (Left Column)**: 书籍核心观点、原汁原味的作者语言。
- **右栏 (Right Column)**: 针对左栏内容，从 `context.md` 中抽出用户刚说过的话、做过的决策，进行冷酷的关联或质问。

### 3. Execution
```bash
python scripts/orchestrate_mirror.py --file <PATH_TO_BOOK>
```

## Resources
- `scripts/orchestrate_mirror.py`
- `agents/mirror-agent.md`
- `scripts/requirements.txt`

## Failure Modes
- **[Token_Blackhole_Defense]**: 如果一章长度仍然过大（超过 80,000 tokens），脚本会尝试继续强行降级切断。
- **[Fact_Hallucination]**: 如果右栏（主观映射）虚构了用户没有说过的“朋友”、“家属”或“事件”，属于严重的隔离被击穿。大模型必须保持原教旨主义的毒舌，不知为不知。
- 若无法提取 PDF，提示用户必须准备好纯文本或可提取的 EPUB。

## Output Contract
- 最终只会交付一个 `output/<BookName>_personalized_mirror.md` 的脑图页面。
- 页面核心内容必须被一个庞大的 Markdown Table 统治（双栏结构）。

## Telemetry
- 使用 `write_file` 将执行结果写回本地审查目录。
- 格式: `{"skill_name": "cognitive-book-mirror", "status": "success", "duration_sec": [ESTIMATE]}`
