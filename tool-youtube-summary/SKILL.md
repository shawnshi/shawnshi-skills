---
name: tool-youtube-summary
description: "深度知识同构引擎。用于提取YouTube视频或长文的核心变量与逻辑框架，重构为高维全息观点切片矩阵与散文体深度文章。"
---

<strategy-gene>
Keywords: YouTube提取, 深度总结, 观点切片, 同构引擎, 文章渲染
Summary: 从冗长的媒体或文本资源中提取物理内核，执行降噪并渲染出高密度的分析文章与观点矩阵。
Strategy:
1. 通过工具或文本抓取原始内容。
2. 内部开启 `<Thinking>` 完成抽象提纯。
3. 严格读取 `resources/synthesis_prompt.md` 进行核心格式化。
4. 强制使用 `write_to_file` 工具落盘至 `MEMORY/raw/youtube`。
AVOID: 禁止产生中间对话冗余；禁止在交互界面打印完整 Markdown；严禁第三方视点语态（如"视频中提到"）。
</strategy-gene>

# Deep Synthesis Engine (tool-youtube-summary)

用于从高噪音的信息源（如 YouTube 字幕、深度长文）中执行原质提取，生成极其克制、结构化的观点分析资产。

## When to Use
- **Trigger**: 用户发送视频链接、大量文本，并要求“提取观点”、“深加工”、“渲染为文章”、“提取矩阵”或明确提及 `tool-youtube-summary` 技能。
- **Non-trigger**: 日常短讯快报（请使用 `triage` 模式），或者仅需一句话结论的基础问答。

## Resources
- **`resources/synthesis_prompt.md`**: 核心指令场。包含了严苛的散文渲染边界、知识矩阵提取参数和跨学科视角的硬性要求。必须在执行生成前使用 `view_file` 读取。

## Workflow
1. **源数据获取**: 若用户提供的是 URL，优先尝试调用 `read_url_content` 或委托网页抓取技能读取内容。若提供的是纯文本，直接进入处理。
2. **隐性推演室 `<Thinking>`**: 在生成前，必须在思考块中输出破局点 -> 逻辑展开 -> 顶层框架映射 -> 终局拷问的大纲雏形，并拟定文件保存路径和主标题。
3. **协议装载**: 调用 `view_file` 挂载并仔细阅读 `resources/synthesis_prompt.md` 中的所有生成约束。
4. **执行落盘**: 组装完整的 Markdown 内容（包含 Stage 2 和 Stage 3），然后**必须且只能**调用 `write_to_file` 工具，将其保存到物理路径：
   `C:\Users\shich\.gemini\MEMORY\raw\youtube\[生成的强反直觉主标题]-[YYYY-MM-DD].md`
   （请自动替换时间戳和合规的标题名称）。
5. **交互收尾**: 文件写入成功后，回复用户一条简短的、带有文件本地链接的确认消息说明提取已完成，**绝对禁止**在对话框中重复输出长文实体内容。

## Failure Modes
- **链接无法解析**: 如果目标页面需要重度 JS 解析或存在反爬拦截，立即向用户报告并建议降级为手动提供文本，或尝试使用更高权限的浏览器技能。
- **内容密度过低**: 如果原素材实质上是缺乏逻辑的废话大杂烩，中止渲染并询问用户是否强行降级提取短文。

## Output Contract
- **系统层输出**：一个基于提取大纲生成的，物理写入 `C:\Users\shich\.gemini\MEMORY\raw\youtube\` 的完整 Markdown 文件。
- **交互层输出**：一条指向上述新生成文件的原生 Markdown 绝对路径链接反馈（例如 `[文件标题](file:///C:/...)`），且附带一句对本次提取最核心观点的毒舌评价（15字以内）。
