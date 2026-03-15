# Text-to-Speech Skill Directory Metadata

## Purpose
该技能是 Gemini CLI 的官方语音反馈组件，旨在通过神经网络语音提升人机协作的临场感与指令传达效率。

## Directory Map
- `scripts/`: 核心混合动力引擎 (`tts_engine.py`)。
- `references/`: 音色库、协议文档、技术指标。
- `output/`: 所有的音频资产 (.mp3) 缓存。
- `install.ps1`: 环境一键闭环脚本。
- `SKILL.md`: 指挥官级使用手册。

## Maintenance
- 缓存清理：定期手动或通过脚本清理 `output/`。
- 引擎优先级：Cloud (High Fidelity) > Local (Fallback)。
