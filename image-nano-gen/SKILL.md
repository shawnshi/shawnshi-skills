---
name: image-studio-architect
description: '端到端视觉资产工厂 (V9.0)。合并了“提示词炼金”与“物理出图”。支持路由：当用户给的是模糊短句时，自动经由 Mondo 脚本升格为丝网大师级提示词并全自动生成图片；当用户给出精细 Prompt 时，执行零干预透传物理生成。'
---

<strategy-gene>
Keywords: 生成图片, 画图, Mondo风格, 海报设计, nanobanana, 端到端绘图
Summary: 视觉资产的无缝生成闭环。打通了 image-promp-gen 与 image-nano-gen。
Strategy:
1. 意图路由：根据用户输入长度与复杂度，决定是走 [Alchemy Mode] 还是 [Raw Mode]。
2. Alchemy Mode（炼金模式）：遇到模糊指令（如“画个赛博朋克海报”），必须先调用 Mondo 脚本生成大师级提示词，然后拿到返回值**无缝直接送入**物理生成引擎，中间严禁停顿询问。
3. Raw Mode（透传模式）：遇到成熟的 Prompt，严格遵守 100% 零干预底线，不加任何废话，直连生成引擎。
4. 物理闭环：最终产物必须落盘于本地指定目录，并返回物理绝对路径供用户点击。
AVOID: 严禁在炼金模式生成提示词后停下来反问用户“您看这样可以吗？”；严禁编造虚假的文件路径。
</strategy-gene>

# Image Studio Architect (端到端视觉资产工厂 V9.0 Native)

> **Vision**: 告别断裂的“先写提示词再画图”流程。不管用户输入的是一句模糊的梦话，还是一段硬核的咒语，系统都会全自动将其转化为最终的物理图片产物。

## 0. 模式路由 (Mode Routing)
When invoked, instantly evaluate the user's prompt:
- **[Raw Mode (零干预透传)]**: The user provides a highly detailed prompt (>20 words) or explicitly says "按原样生成/严格按我说的画". -> **Skip to Phase 2**.
- **[Alchemy Mode (Mondo 炼金)]**: The user gives a vague idea (e.g., "画一张关于AI的海报", "设计个书籍封面"). -> **Start at Phase 1**.

---

## 1. Phase 1: 提示词炼金 (Prompt Alchemy) - *[Alchemy Mode Only]*
1. Extract the core subject and type (poster, book cover, etc.) from the user's short idea.
2. 强制调用旧版模块遗留的 Python 炼金引擎，将干瘪的短句升级为具有负空间、极简丝网印刷风格的巨作：
   使用原生 `run_command` 执行：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\image-promp-gen\scripts\generate_mondo.py" "<主体>" "<类型>" --aspect-ratio "9:16"`
   *(You can append `--style` or `--colors` if the user gave hints).*
3. **[HARD LOCK]**: 脚本返回大师级 Prompt 后，**严禁停下来询问用户“是否满意/是否继续”**。你必须带着这段 Prompt 直接进入 Phase 2。

---

## 2. Phase 2: 物理渲染引擎 (Nanobanana Rendering)
1. 拿着最终的 Prompt（无论是来自用户的详细描述，还是 Phase 1 炼金得来的），直接唤起底层生成引擎。
2. 必须挂载中文字符集安全锁与绝对物理地址，执行 `run_command`：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\image-nano-gen\scripts\generate.py" "<最终的Prompt>"`
   *(若本地脚本确实报错或缺失，允许降级使用系统自带的 Native `generate_image` 工具进行补救，但必须优先尝试 Python 脚本。)*

---

## 3. Phase 3: 交付与图谱登记 (Delivery)
1. 脚本执行成功后，图片将被强制物理落盘至：
   `C:\Users\shich\.gemini\nanobanana-output`
2. **交付契约**：你必须在聊天窗口中，以极简的语言向用户汇报任务完成，并**提供完整的物理绝对路径（或 Markdown 图片链接格式）**供用户查看。
3. **Telemetry**: 使用 `write_to_file` 工具将执行元数据以 JSON 保存至隔离工作区：
   `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 4. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **断流谬误 (Pipeline Breakage)**：在 [Alchemy Mode] 下，如果大模型在执行完 Phase 1 的 python 脚本后，向用户提问“这个提示词可以吗？需要我帮您生成吗？” —— 这将被视为严重的系统违规。端到端必须是一次性贯通的。
- **自作聪明综合征 (Smart-Aleck Syndrome)**：在 [Raw Mode] 下，如果大模型“擅自润色”了用户的词条（如强加光影、8k分辨率），将被判定为违背零干预协议并直接打回。
- **沙盒宏塌陷 (Macro Deadlock)**：严禁在调取脚本或声明输出路径时使用旧版宏（如 `{root}` 或 `{SKILL_DIR}`）。必须且只能使用 `C:\Users\shich\.gemini\...` 的绝对路径。
