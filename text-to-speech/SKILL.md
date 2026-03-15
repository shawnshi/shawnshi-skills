# Text-to-Speech (TTS 2.0 Hybrid Engine)

Gemini CLI 高保真混合播报系统。采用神经网络云端引擎与本地物理链路双轨制，确保播报的**高审美**与**极高可用性**。

## Core Capabilities
*   **Hybrid Routing**: 自动探测环境。首选 Microsoft Edge 神经网络语音（高保真），失败后 50ms 内自动切回本地 SAPI5 播报。
*   **Encoder Shield**: 采用物理文件中转技术，完美解决 Win32 环境下长中文 Token 的传输死锁问题。
*   **Sovereign Control**: 支持音色、语速、音调的精细化参数控制。

## Execution Protocol

### 1. 指挥官简报 (默认高保真)
```bash
python scripts/tts_engine.py "正在执行本周生理审计报告..."
```

### 2. 紧急报警模式
```bash
python scripts/tts_engine.py "检测到系统熵增风险！" --rate +30% --voice zh-CN-Xiaoxiao-Neural
```

### 3. 离线验证/手动兜底
若需强制保存音频资产：
```bash
python scripts/tts_engine.py "逻辑资产固化测试" --output output/logic_asset.mp3 --play
```

## Voice Gallery (神经网络音色)
- `zh-CN-Yunxi-Neural`: 沉稳、权威 (推荐：战略汇报)
- `zh-CN-Xiaoxiao-Neural`: 亲切、流畅 (推荐：日常交互)
- `zh-CN-Xiaochen-Neural`: 严谨、干练 (推荐：技术审查)

## Failover Mechanism
若看到 `[!] 云端引擎握手失败` 字样，系统将自动进入 `Win32 本地物理链路`。这是正常的优雅降级行为，确保指令传达不中断。
