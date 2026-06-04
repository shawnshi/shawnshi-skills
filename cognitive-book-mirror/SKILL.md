---
name: cognitive-book-mirror
description: 个人化认知镜像与伴读引擎。提取长文或书籍核心要点，结合过去14天日记及个人价值观体系，生成高密度的双栏伴读分析。左栏保留原旨，右栏进行毒舌映射，执行极度的交叉检验。
triggers: ["伴读这本书", "认知镜像", "双栏伴读", "结合我的日记分析这本书"]
---

<strategy-gene>
Keywords: 双栏伴读, 认知镜像, 私域映射, 毒舌幕僚
Summary: 将极净的纯文本或 Markdown 切片，在只读沙盒内同高密度私域 Context 结合，实施双栏架构输出。
Strategy:
1. Format 拦截与降维：技能默认接收 `.txt` 或 `.md`。若输入其它异构文件（PDF, EPUB, MOBI 等），脚本会在底层自动挂载 `markdown-converter` 进行静默的降维清洗。
2. Context 脱水打包：读取最近14天的 `MEMORY/raw/privacy/Diary` 记录及全局 `USER.md`/`SOUL.md`，预先组装。
3. 并发降权与映射：分块章节执行 LLM，约束 LLM 输出双栏表格；严禁 LLM 提供“建议”，只准作事实与逻辑关联。
4. 结构重组：自动合并章节后输出 `<BookName>_personalized_mirror.md`。
AVOID: 严禁将整书直接硬塞给大模型导致 OOM；严禁产生关于用户的幻觉；如果右栏对应不上，必须留空或坦白说明，绝不强行关联。
</strategy-gene>

# Cognitive Book Mirror (Native Edition)

个人化认知镜像与伴读引擎。这是一个将外部世界（书籍/长文）与内心世界（日记/价值观）强行碰撞的高密度分析机器。

## When to Use
- 当你想知道一本畅销书、一本专业书或一篇长篇报告“对我现在的生活/业务到底有什么用”时。
- 当你需要通过特定的战略视角（如过去 14 天的困惑）去穿透一本厚重的书时。

## Workflow

### 1. The Context Packing Phase
主 Agent 首先执行数据脱水与打包脚本 `scripts/extract_and_pack.py`：
```bash
python C:/Users/shich/.gemini/config/skills/cognitive-book-mirror/scripts/extract_and_pack.py --file <PATH_TO_MARKDOWN_OR_TXT>
```
该脚本会执行 Semantic Chunking 切片，并抓取 `USER.md`、`SOUL.md` 以及过去 14 天的日记，统一打包输出到临时目录 `tmp/playgrounds/book_mirror/<book_stem>/` 中，并生成 `manifest.json` 索引文件。

### 2. The Subagent Orchestration Phase
主 Agent 负责蓝图定义与智能调度：
1. **定义子代理**：读取提取出的 `prompt.md` 与 `context.md`，使用 `define_subagent` 定义一个名为 `CognitiveMirrorWorker` 的子代理，将所有私域语境注入其 `system_prompt` 中。
2. **队列式任务派发 (Worker Pool)**：根据 `manifest.json` 中的 `chunks` 数量，**强烈建议使用单实例或 3-5 个实例的特工池（Worker Pool）**。不要一次性并发唤醒几十个特工（避免 Context 冗余与 Token 黑洞）。向 Worker 依次发送需要处理的 Chunk 文本。要求输出严格的双栏结构：
   - **左栏 (Left Column)**: 书籍核心观点、原汁原味的作者语言。
   - **右栏 (Right Column)**: 针对左栏内容，进行冷酷的映射关联与质问。
3. **特工回收**：等待所有子代理返回结果，将结果存入 `results/` 目录下，按 `result_001.md` 命名。
4. **自动化缝合 (Automated Stitching)**：运行以下脚本自动完成无缝重组与落地：
```bash
python C:/Users/shich/.gemini/config/skills/cognitive-book-mirror/scripts/stitch_and_format.py --book_stem <book_stem> --results_dir tmp/playgrounds/book_mirror/<book_stem>/results
```

### 3. Execution & Resources
- **核心脚本**: `scripts/extract_and_pack.py`
- **模型人设**: `agents/mirror-agent.md`
- **依赖列表**: `scripts/requirements.txt`


## Resources
TBD.

## Failure Modes
- **[Token_Blackhole_Defense]**: 如果一章长度仍然过大（超过 80,000 tokens），脚本会尝试继续强行降级切断。
- **[Fact_Hallucination]**: 如果右栏（主观映射）虚构了用户没有说过的“朋友”、“家属”或“事件”，属于严重的隔离被击穿。大模型必须保持原教旨主义的毒舌，不知为不知。
- **[Architecture_Violation]**: 虽支持自动清洗，但若遇到极度异常或损坏的二进制文件，`markdown-converter` 静默挂载失败后，脚本会抛出底层转换错误并退出。

## Output Contract
- 最终只会交付一个 `MEMORY/raw/read/<BookName>_personalized_mirror.md` 的脑图页面。
- 页面核心内容必须被一个庞大的 Markdown Table 统治（双栏结构）。

## Telemetry
主 Agent 在缝合完成后，只需输出一份精简的 JSON 汇报即可，例如：
```json
{"skill_name": "cognitive-book-mirror", "status": "success", "chunks_processed": 65}
```
