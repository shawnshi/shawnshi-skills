---
name: text-to-speech
description: 军工级播报系统 (Gemini 3.1 Director Edition)。当系统检测到“逻辑死锁”、进入“反熵增攻坚协议”或用户明确要求“朗读文本”、“语音提醒”时，务必激活。该技能支持 Gemini 原生“导演模式”、多角色对话与本地 SAPI5 双轨切换。
---

# Text-to-Speech (TTS 3.1 Director Engine)

Gemini CLI 高保真混合播报系统。采用 **Gemini 3.1 Flash TTS Preview** 原生引擎，支持极致的情感控制与多角色混播。

## When to Use
- 当用户要求朗读文本、语音提醒、角色化播报，或需要导演模式语音表现时使用。
- 本技能处理语音生成与回退路由，不负责普通文字摘要。

## Core Capabilities
*   **Director Mode**: 通过 `Audio Profile`, `The Scene`, `Director's Notes` 三位一体的架构，深度定制播报的语气、环境音效与角色性格。
*   **Multi-Speaker**: 原生支持单次播报中切换多个说话人（通过 `SpeakerName: ` 标识）。
*   **Expressive Audio Tags**: 支持 200+ 细粒度控制标签，精准捕捉从 [whispers] 到 [shouts] 的细微情感。
*   **Hybrid Routing**: 首选 Gemini 神经网络语音，失败后自动指数退避重试，最终切回本地 SAPI5。

## Workflow

### 1. 标准指挥官简报
```bash
python scripts/tts_engine.py "正在执行本周生理审计报告..."
```

### 2. 导演模式 (极致表现力)
```bash
python scripts/tts_engine.py "[excited] 升级成功！[laughs] 效果非常出色。" --scene "在空旷的音乐厅" --notes "带有明显的混响，语速稍快，充满激情"
```

### 3. 多角色对话播报
```bash
python scripts/tts_engine.py "Commander: 检测到异常。Expert: [serious] 正在分析数据流。"
```

## Voice Gallery (Gemini 3.1 音色)
- `Charon`: 沉稳、权威 (推荐：战略汇报)
- `Aoede`: 轻快、空灵 (推荐：日常交互)
- `Puck`: 活泼、充满活力 (推荐：动态提醒/反馈)
- `Kore`: 坚定、中立 (推荐：技术审查/审计)
- `Fenrir`: 兴奋、高能量 (推荐：紧急警报)

## 导演模式参数
- `--profile`: 定义角色身份（如：一位严厉的审查官）。
- `--scene`: 定义环境氛围（如：在下雨的室外）。
- `--notes`: 具体表演指令（如：语速极慢，单词间有明显停顿）。

## Audio Tags 矩阵
支持在文本中直接嵌入：
- **情感**: `[admiration]`, `[agitation]`, `[amazed]`, `[angry]`, `[confidence]`, `[hope]`
- **语气**: `[whispers]`, `[shouts]`, `[slowly]`, `[fast]`, `[monotone]`
- **生理**: `[laughs]`, `[sighs]`, `[coughs]`, `[gasps]`, `[clears throat]`, `[yawn]`

## Failover Mechanism
若看到 `[!] Gemini 引擎调用失败` 字样，系统将自动进入指数退避重试。若最终失败，将启动 `Win32 本地物理链路` 兜底。

## Resources
- `scripts/tts_engine.py`
- Gemini TTS 引擎
- 本地 SAPI5 回退链路

## Failure Modes
- Gemini 引擎失败时必须按回退机制处理，不能静默失败。
- 多角色和标签语法必须保持原样，不要在执行前清洗掉。
- 不要把导演模式参数伪装成普通播报。

## Output Contract
- 必须生成真实音频播报，而不是仅返回脚本命令。
- 若主链路失败，必须明确是否已切到本地兜底。
- 输出应与用户指定的角色、情绪或场景保持一致。

## Telemetry
- 自动记录执行模式（Standard vs Director）与元数据。
