---
name: personal-musicbee-dj
description: 音乐极客控制协议。当用户想“听音乐”、“打开 MusicBee”、“放点歌”或描述“某种氛围/流派”时，务必激活。该技能通过 JIT 歌单算法与 XML 物理操纵，精准控制本地 MusicBee 进程，实现秒级氛围切换。
triggers: ["播放音乐", "播放 [流派/场景/歌单] 歌单", "我想听点...", "打开MusicBee", "放点歌"]
---
# Personal MusicBee DJ (音乐极客控制协议)

## 核心机制
本技能旨在通过 Gemini 意图引擎解析用户的需求，将其转化为对 MusicBee 进程的精确控制。
由于 MusicBee 原生功能不支持“按需组合流派播放”或无缝场景切换，我们在后端利用「缓存层 + XML高速解析 + 归纳算法」做到 JIT（即时）歌单生成，绕开笨重的传统接口。

## 适用条件与触发器
当用户对话包含以下关键词可激活此模块：
- "播放音乐"
- "播放流派/场景/歌单"
- "我想听点..."
- "打开MusicBee", "放点歌"
- 提到的意图涉及：专注、放松、工作、打代码时的背景音、赛博朋克、爵士乐等。

## 参数定义 (Prompt Injection)
在执行本模块前，必须抽象出以下关键指令：
```json
{
  "type": "类型，枚举值：[genre | scene | playlist]",
  "value": "需要解析的内容，例如：'Jazz', 'focus', '我最喜欢的音乐'",
  "intensity": "动量/强度参数，枚举值：[high | low | normal]。根据用户语气或形容词（如：极速、激烈、炸裂 -> high；舒缓、安静、慢慢摇 -> low）"
}
```

### 场景映射 (Scene Mapping)
为了解决抽象化需求（如：“我想安静一会儿”），本模块自带一层概念转换。基于你当前音乐库中的 11 个核心流派（如 chinese folk, chs, Classical, Country, eng, France, Jap, Jazz, Korean, pure music, Rock），请对照 `config.yaml` 的 `scenes` 定义。常用场景如下：
- **focus**: 深度工作、阅读、极度专注。主要映射至 `Classical`, `pure music`, `Jazz`。
- **relax**: 休息、冥想、舒缓。主要映射至 `Jazz`, `Country`, `France`, `pure music`。
- **energy**: 燃向、健身、提神。主要映射至 `Rock`, `Korean`, `Jap`, `eng`。
- **coding**: 写代码、心流状态。主要映射至 `pure music`, `Classical`, `Jap`, `eng`。
- **pop**: 流行人声、日常听歌。主要映射至 `chs`, `eng`, `Jap`, `Korean`。

## 执行流程 (Execution Rules)
1. **意图获取**: 你需负责与用户确认或自动判定上述 `type` 与 `value`，以及隐形的 `intensity` 参量。
2. **场景降级 (Fallback)**: 如果用户提出的场景（如“我要学习”、“做家务”）不在映射表内，**严禁报错退出**。请自行揣摩意图，将其转换为最接近的可用 11 个核心流派之一的 `type="genre"`（如：`pure music` 或 `chs`）来进行兜底。
3. **底层降维执行**: 组织完备后，使用 `python` 投递至命令行：

```bash
python "{root_dir}\.gemini\skills\personal-musicbee-dj\src\cli.py" --type <type> --value "<value>" --intensity <intensity>
```

**⚠️ 警告 (Failsafe)**: 
*   若遇到路径不对应或子进程抛出异常，请自行挂载 `/forge` 进行日志检查或提醒用户。
*   此模块高度依赖 MusicBee 开启了 `共享 iTunes 兼容库 XML` 开关（默认在 `编辑 > 首选项 > 库 > library settings` 处打开）。

**Telemetry & Metadata (Mandatory):**
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root_dir}/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "office-hours", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
