---
name: tool-youtube-summary
version: 9.0.0
tier: action-allowed
description: '深度知识同构引擎。用于提取YouTube视频或长文的核心变量与逻辑框架，重构为高维全息观点切片矩阵与散文体深度文章。'
triggers: ["提取观点", "总结视频", "视频转长文", "深度渲染为文章"]
---

<strategy-gene>
Keywords: YouTube提取, 深度总结, 观点切片, 同构引擎, 文章渲染
Summary: 从冗长的媒体或文本资源中提取物理内核，执行降噪并渲染出高密度的分析文章与观点矩阵。
Strategy:
1. 1. 通过工具或文本抓取原始内容。
2. 2. 内部开启 <Thinking> 完成抽象提纯。
3. 3. 严格读取
4. esources/synthesis_prompt.md 进行核心格式化。
5. 4. 强制使用 write_to_file 工具落盘至 MEMORY/raw/youtube。
AVOID: 禁止产生中间对话冗余；禁止在交互界面打印完整 Markdown；严禁第三方视点语态（如"视频中提到"）。
</strategy-gene>

# Deep Synthesis Engine (tool-youtube-summary V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. 
2. ead_url_content / [No Tools] (提取视频字幕或文本内容)
3. iew_file (强制读取 synthesis_prompt.md)
4. write_to_file (将提取渲染完成的 Markdown 完整写入沙盒)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Data Acquisition
- **源数据获取**: 若用户提供的是 URL，优先尝试调用网页抓取技能读取内容。若提供的是纯文本，直接进入处理。

### Phase 2: Synthesis Preparation
- **隐性推演室 <Thinking>**: 在生成前，必须在思考块中输出破局点 -> 逻辑展开 -> 顶层框架映射 -> 终局拷问的大纲雏形，并拟定文件保存路径和主标题。
- **协议装载**: 调用 iew_file 挂载并仔细阅读 
esources/synthesis_prompt.md 中的所有生成约束。

### Phase 3: Drafting & Writeback
- **执行落盘**: 组装完整的 Markdown 内容（包含 Stage 2 和 Stage 3），然后**必须且只能**调用 write_to_file 工具，将其保存到绝对物理路径：
   C:\Users\shich\.gemini\MEMORY\raw\youtube\[生成的强反直觉主标题]-[YYYY-MM-DD].md
   （请自动替换时间戳和合规的标题名称）。

## 2. <Contracts> (输出与交付契约)
- **交互收尾**: 文件写入成功后，回复用户一条简短的、带有文件本地链接的确认消息说明提取已完成，**绝对禁止**在对话框中重复输出长文实体内容。
- **系统层输出**：一个基于提取大纲生成的，完整 Markdown 文件。
- **交互层输出**：附带一句对本次提取最核心观点的毒舌评价（15字以内）。

## 3. <Failure_Taxonomy> (失败分类学)
- **链接无法解析**: 如果目标页面存在反爬拦截，立即向用户报告并建议降级为手动提供文本。
- **内容密度过低**: 如果原素材实质上是废话大杂烩，中止渲染并询问用户是否强行降级提取短文。
