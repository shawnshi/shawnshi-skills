---
name: cognitive-book-mirror
version: 9.0.0
tier: action-allowed
description: '个人化认知镜像与伴读引擎。提取长文或书籍核心要点，结合过去14天日记及个人价值观体系，生成高密度双栏伴读分析。左栏保留原旨，右栏毒舌映射。禁止产生关于用户的幻觉或强行关联。'
triggers: ["伴读这本书", "认知镜像", "双栏伴读", "结合我的日记分析这本书"]
---

<strategy-gene>
Keywords: 双栏伴读, 认知镜像, 私域映射, 毒舌幕僚
Summary: 将极净的纯文本或 Markdown 切片，同高密度私域 Context 结合，实施双栏架构输出。
Strategy:
1. 1. Format 拦截：默认接收 `.txt` 或 `.md`。若输入异构文件，挂载 `markdown-converter` 进行降维。
2. 2. Context 脱水：读取最近 14 天的日记及全局 `USER.md`/`SOUL.md`，预先组装。
3. 3. 并发映射：分块章节执行子代理，约束输出双栏表格；只作事实与逻辑关联。
4. 4. 结构重组：自动合并章节后输出 `<BookName>_personalized_mirror.md`。
AVOID: 将整书硬塞给大模型；虚构用户背景；强行关联无关内容。
</strategy-gene>

# Cognitive Book Mirror (Native Edition V9.0)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (提取打包脚本 extract_and_pack.py)
2. `view_file` (加载镜像代理人设)
3. `define_subagent` (注册 CognitiveMirrorWorker 特工)
4. `invoke_subagent` (分块并发分析)
5. `write_to_file` (双栏数据片段落盘)
6. `run_command` (自动合并章节 stitch_and_format.py)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: The Context Packing
主代理执行数据脱水与打包脚本：
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-book-mirror\scripts\extract_and_pack.py" --file <PATH_TO_MARKDOWN_OR_TXT>
```
该脚本会执行 Semantic Chunking 切片，并抓取 `USER.md`、`SOUL.md` 以及过去 14 天日记，统一打包输出到 `<appDataDir>\brain\<conversation-id>\scratch\book_mirror\<book_stem>\` 中，并生成 `manifest.json` 索引文件。

### Phase 2: The Subagent Orchestration
主代理负责蓝图定义与智能调度：
1. **人设挂载**: 使用 `view_file` 工具加载本目录下的 `agents/mirror-agent.md`。
2. **定义子代理**: 将人设内容作为 `system_prompt`，结合 `prompt.md` 与 `context.md`，使用 `define_subagent` 注册名为 `CognitiveMirrorWorker` 的子代理。
3. **任务派发**: 根据 `manifest.json` 中的 `chunks` 数量，使用并发池模式调用 `invoke_subagent`。
   - 明确指示子代理：“分析完成后，将结果封装为双栏结构 JSON，使用 `send_message` 回传主代理”。
   - **左栏**: 书籍核心观点。
   - **右栏**: 针对左栏内容，进行映射关联与质问。
4. **特工回收**: 主代理在上下文中提取双栏数据，按顺序使用 `write_to_file` 工具存入 `<appDataDir>\brain\<conversation-id>\scratch\book_mirror\<book_stem>\results\` 目录下，命名为 `result_001.md`, `result_002.md` 等。

### Phase 3: The Stitching
自动合并章节后输出：
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-book-mirror\scripts\stitch_and_format.py" --book_stem <book_stem> --results_dir "<appDataDir>\brain\<conversation-id>\scratch\book_mirror\<book_stem>\results"
```

## 2. <Failure_Taxonomy> (失败分类学)
- **Token_Blackhole_Defense**: 若单章长度过大，脚本会尝试强制切断以保证超高密度的“逐段质问”细节。
- **Fact_Hallucination**: 右栏（主观映射）虚构了用户没有说过的“事件”或“人际关系”。大模型必须保持毒舌且不知为不知。
- **Architecture_Violation**: 遇到损坏的二进制文件，`markdown-converter` 静默挂载失败，底层转换错误。主代理解析错误并上报即可。
- **Tool_Hallucination**: 试图使用过期的 `write_file` 而非原生的 `write_to_file` 保存碎片。

## 3. <Contracts> (输出与交付契约)
- **最终交付**: 仅交付一个 `MEMORY/raw/read/<BookName>_personalized_mirror.md` 的脑图页面。
- **视觉契约**: 页面核心内容由一个包含双栏结构的 Markdown Table 组成。
- **交付链接契约**: 最终伴读生成后，必须通过聊天向用户输出包含绝对物理路径的可点击 Markdown 链接（例如：`[《<BookName>》私域认知镜像](file:///C:/Users/shich/.gemini/MEMORY/raw/read/...)`）。
- **遥测汇报**: 缝合完成后，输出简略 JSON 汇报：`{"skill_name": "cognitive-book-mirror", "status": "success", "chunks_processed": N}`。
