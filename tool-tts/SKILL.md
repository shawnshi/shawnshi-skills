---
name: tool-tts
version: 8.1.0
description: 军工级播报系统 (Gemini 3.1 Director Edition)。当系统检测到“逻辑死锁”、进入“反熵增攻坚协议”或用户明确要求“朗读文本”、“语音提醒”时，务必激活。该技能支持 Gemini 原生“导演模式”、多角色对话与本地 SAPI5 双轨切换。
triggers: ["朗读这段话", "语音提醒我", "用语音说", "播放这段文本", "导演模式播报"]
---

<strategy-gene>
Keywords: 朗读文本, 语音提醒, TTS, 播报, 导演模式
Summary: 将文本转化为具备极致情感张力的语音，并保障原生终端环境下的降级发声闭环。
Strategy:
1. 获取意图：确定播报内容、情绪场景和分发模式（标准/导演/多角色）。
2. 环境锁定：必须使用原生 `run_command` 调用并强制挂载中文字符集安全锁与物理绝对路径。
3. 双轨回退：神经网络调用失败时允许自动切回物理 SAPI5 进行降级播报。
AVOID: 禁止直接给出一段 Python 代码让用户自己去跑；禁止擅自改动多角色剧本或剥离原有的 Audio Tags。
</strategy-gene>

# Tool TTS (高保真导演级播报系统 V8.1 Native)

> **Vision**: Gemini CLI 高保真混合播报中枢。利用 Gemini 3.1 Flash TTS Preview 引擎，通过 Audio Tags 矩阵实现精准到[叹气]与[嘶吼]的情绪表达。绝不仅是文字的机器诵读。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Context & Mode Selection [Mode: PLANNING]
- 判断播报等级，根据任务性质从 `<Contracts>` 中选择音色与模式（Standard, Director, Multi-Speaker）。

### Phase 2: Engine Execution (引擎激活与上锁) [Mode: EXECUTION]
- **[HARD LOCK]**：必须使用 `run_command` 执行任务。为防止 Windows 终端因中文字符集而闪退截断，必须强行加挂 `$env:PYTHONIOENCODING="utf-8"` 与完整的绝对物理路径。

#### Mode A: 标准指挥官简报
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-tts\scripts\tts_engine.py" "正在执行本周生理审计报告..."
```

#### Mode B: 导演模式 (极致表现力定制)
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-tts\scripts\tts_engine.py" "[excited] 升级成功！[laughs] 效果非常出色。" --scene "在空旷的音乐厅" --notes "带有明显的混响，语速稍快，充满激情"
```

#### Mode C: 多角色对话阵列
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-tts\scripts\tts_engine.py" "Commander: 检测到异常。Expert: [serious] 正在分析数据流。"
```

### Phase 3: Verification (降级回退验证) [Mode: VERIFICATION]
- 监听控制台输出。若出现 `[!] Gemini 引擎调用失败`，系统自带脚本将自动执行指数退避重试，并最终切回 Win32 SAPI5 物理链路。大模型只需静默等待其完成或向用户汇报降级情况即可。

## 2. <Contracts> (输出与交付契约)

### Voice Gallery 契约 (Gemini 3.1 核心音色表)
- `Charon`: 沉稳、权威 (强制用于：战略汇报、错误阻断、审计通报)
- `Aoede`: 轻快、空灵 (强制用于：日常成功交互、灵感反馈)
- `Puck`: 活泼、高能量 (强制用于：动态提醒、环境警示)
- `Kore`: 坚定、中立 (强制用于：大段技术审查、代码通读)
- `Fenrir`: 兴奋、压迫感 (强制用于：紧急警报、逻辑死锁告警)

### Audio Tags 矩阵与导演语法 (Director Protocol)
支持在需要被播报的**文本字符串中直接嵌入**以下高维表情符号，脚本底层会自动将其映射为神经元发声：
- **生理反应**: `[laughs]`, `[sighs]`, `[coughs]`, `[gasps]`, `[clears throat]`, `[yawn]`
- **语气强制**: `[whispers]`, `[shouts]`, `[slowly]`, `[fast]`, `[monotone]`
- **情感映射**: `[admiration]`, `[agitation]`, `[amazed]`, `[angry]`, `[confidence]`, `[hope]`

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)

- **沙盒迷失 (Pathing Deadlock)**：绝对禁止大模型在终端中使用 `python scripts/tts_engine.py` 等相对路径。必须使用 `C:\Users\shich\.gemini\config\skills\tool-tts\...` 绝对物理地址，否则终端必定向系统抛出寻址异常。
- **中文断流 (Encoding Failure)**：未挂载 `$env:PYTHONIOENCODING="utf-8"` 即强行发送带中文字符的语音指令，将被视为重大系统纪律违规，这会导致生成的音频出现半句卡顿。
- **幻觉越权 (Bypass Execution)**：当用户要求朗读时，严禁大模型仅仅在聊天窗口输出一段 `这是一段为您准备的脚本`。大模型必须通过终端原生命令驱动脚本物理出声。
- **洗稿与消音 (Tags Stripping)**：严禁大模型自作主张清洗掉用户原始指令或系统剧本中的 `[laughs]` 等 Audio Tags，必须 100% 原始透传以保障导演级表现力。
