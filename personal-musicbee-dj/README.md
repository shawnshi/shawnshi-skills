name: personal-musicbee-dj
description: 音乐极客控制协议 (MusicBee DJ)。当用户想“听音乐”、“打开 MusicBee”、“放点歌”或描述“某种氛围/流派”时，务必激活。该技能通过 JIT 歌单算法与 XML 物理操纵，精准控制本地 MusicBee 进程，实现秒级氛围切换。
triggers: ["播放音乐", "播放 [流派/场景/歌单] 歌单", "我想听点...", "打开MusicBee", "放点歌", "给我点专注的背景音", "来点爵士乐"]
---

# 🎵 Personal MusicBee DJ (音乐极客控制协议)

> **版本体系**: V3.0 (Agentic Curation Edition)
> 
> **定位**: 专为 Gemini CLI 打造的智能本地音乐控制引擎与情绪策展系统。超越传统的“随机播放器”，利用“JIT即时挂载 + 毫秒级 XML 引擎 + DJ 算法数学模型”，根据当前的情绪、任务强度和场景，全自动生成并无缝切入能量最适宜的背景音。

## 🎯 核心使命 (Mission)
在数字噪音横行的时代，将背景音的控制权交给算法，把心流（Flow）交还给大脑。通过解析用户的模糊意图（如“想静一静”、“要肝代码”），将其降维映射为对底层 MusicBee 进程的精准物理控制。

## 🛠️ 核心架构 (Architecture)
```text
personal-musicbee-dj/
│
├── SKILL.md                 # 🧠 核心大脑：意图解析、场景映射与物理执行指令
├── README.md                # 📖 当前说明文档与元数据
├── config.yaml              # ⚙️ 配置文件：包含音乐库 XML 路径与场景映射表
│
└── src/                     # 📦 物理执行引擎
    ├── cli.py               # CLI 入口
    └── core/                # JIT 歌单生成与 XML 高速解析逻辑
```

## 🚀 触发与适用条件 (Usage)
当对话包含以下关键词或意图时激活此模块：
- "播放音乐", "打开MusicBee", "放点歌"
- 提到的意图涉及：专注、放松、工作、打代码时的背景音、赛博朋克、爵士乐等。

---
*Developed by Gemini Agentic Reasoning | Framework V3.0*