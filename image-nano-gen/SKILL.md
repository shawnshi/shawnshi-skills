---
name: nanobanana-image-gen
version: 8.1.0
description: 当用户要求“生成图片”、“画图”、“使用 nanobanana 绘画”或提供需要图像生成的 Prompt 时，强制激活此技能。该技能利用 Gemini Imagen 3 引擎，支持 4K 质量与高认知计算模式，自动落盘至指定物理目录。
triggers: ["画一张", "生成图片", "帮我绘制", "使用 nanobanana", "使用 imagen", "生成海报"]
---

<strategy-gene>
Keywords: 生成图片, nanobanana, Imagen, 海报, 插图
Summary: 将用户图像意图 100% 原始透传为可执行的高质量生成提示词和本地物理图像产物。
Strategy:
1. 获取意图：明确主题、比例、风格、主体、背景、文字要求。
2. 零干预透传：严禁擅自润色用户的提示词，必须原汁原味透传给底层脚本。
3. 物理执行：调用原生终端工具运行本地 Python 引擎完成渲染与落盘。
AVOID: 禁止生成与用户意图不符的风格漂移图；禁止漏报输出路径；禁止编造虚假路径。
</strategy-gene>

# Nanobanana Image Generator (图像引擎 V8.1 Native)

> **Vision**: 专为高质量（4K）、高思维深度（thinking_level="HIGH"）的图像生成任务打造。坚守本地逻辑闭环与 100% 意图透传。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Preparation (零干预透传) [Mode: PLANNING]
1. **[Zero-Intervention Policy]**：必须 100% 保持用户提交的原始语句。严禁大模型对用户的提示词进行任何“画蛇添足”的润色、意图扩展、细节补充或高思维扩写。
2. 即使输入是结构化的 Markdown，也必须将其作为**一个完整的 Prompt 字符串**直接透传。

### Phase 2: Action & Rendering (引擎唤醒与渲染) [Mode: EXECUTION]
1. 必须使用系统的 `run_command` 工具调用底层的 `generate.py` 引擎。
2. 必须挂载中文字符集安全锁与绝对物理地址：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\image-nano-gen\scripts\generate.py" "用户的原始Prompt"`
   *(注：若 Prompt 中存在引号，请合理转义并使用双引号将参数严格包裹。)*

### Phase 3: Delivery & Telemetry (物理落盘交付) [Mode: EXECUTION]
1. 脚本执行成功后，读取命令行输出，图片将被强制物理落盘至：
   `C:\Users\shich\.gemini\nanobanana-output`
2. 向用户交付最终结论并展示完整的绝对物理路径。严禁生成虚假路径。
3. 记录遥测：使用 `write_to_file` 工具将执行元数据以 JSON 保存至：
   `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 2. <Contracts> (输出与交付契约)
- **原始透传契约 (Raw Pass-through)**：传给 Python 的 Prompt 必须是一个 100% 未经大模型过滤或扩写的完整字符串参数。用户的意图不容侵犯。
- **物理交付契约 (Physical Delivery)**：交付物必须是物理生成的一张或多张真实图片文件（展示绝对路径）。绝不仅是一段“图片应该长这样”的文字描述。
- **环境韧性契约 (Env Resilience)**：若执行报错提示 `google-genai` 或 `pillow` 未安装，必须首先调用 `run_command` 执行 `pip install google-genai pillow` 修复环境，严禁因环境问题放弃任务。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **沙盒宏塌陷 (Macro Deadlock)**：严禁在调取脚本或声明输出路径时使用旧版宏（如 `{root}` 或 `{SKILL_DIR}`）。必须且只能使用 `C:\Users\shich\.gemini\...`。若发现路径幻觉，直接阻断任务。
- **自作聪明综合征 (Smart-Aleck Syndrome)**：如果被侦测到大模型在生成前，“擅自润色”或强行给用户的词条添加了所谓的“光影、质感、大师级”等虚假标签，将被判定为违背零干预协议并直接打回。
- **虚假接口调取 (Fake API Call)**：绝对禁止大模型使用普通的 HTTP POST 瞎编接口向不存在的服务器发请求，必须且只能调用配套的 `generate.py` 脚本。
- **工具幻觉 (Tool Forgery)**：严禁调用旧版的 `run_shell_command` 或 `write_file`，必须使用符合 Native 规范的 `run_command` 和 `write_to_file`。
