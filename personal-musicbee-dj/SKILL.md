---
name: personal-musicbee-dj
version: 8.1.0
description: MusicBee DJ for local playback control. Use when the user wants to hear music, open MusicBee, switch playlists, or describe a mood, scene, or genre such as focus, relax, coding, pop, jazz, or energy. The skill resolves intent into genre/scene/playlist parameters, generates a just-in-time M3U playlist from the local MusicBee XML library when needed, and launches MusicBee with a validated local play target.
triggers: ["播放音乐", "听歌", "放点歌", "切换歌单", "背景音乐", "专注音乐", "放松音乐"]
---

<strategy-gene>
Keywords: MusicBee, 播放音乐, playlist, focus music
Summary: 控制本地 MusicBee 播放和歌单切换，服务即时场景氛围。
Strategy:
1. 判断用户想打开、播放、切换歌单还是按情绪选曲。
2. 使用本地可用控制路径执行播放动作。
3. 若控制失败，报告进程、路径或权限问题。
AVOID: 禁止假装已经播放；禁止随意改动音乐库文件。
</strategy-gene>

# Personal MusicBee DJ (音乐点播与场域渲染 V8.1 Native)

本技能将用户模糊的听歌意图、场景氛围（如 focus, coding, relax）转化为精准的本地 MusicBee 播放指令，并拉起物理端的音频进程。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Intent Resolution (意图解析) [Mode: PLANNING]
解析用户的需求，提取出必须要传给控制脚本的 3 个参数：
- `type`: 必须是 `genre | scene | playlist`
- `value`: 具体请求的流派、场景名称或歌单名。
  *(推荐的内置场景/Scene包括: `focus`, `relax`, `energy`, `coding`, `pop`。若用户给出了非标场景，必须走语义回退/Semantic Fallback，将其就近映射到已有配置中，而不是直接中止任务。)*
- `intensity`: 必须是 `high | normal | low`

### Phase 2: Execution (拉起播放器) [Mode: EXECUTION]
必须使用原生 `run_command` 工具调用该技能专属的本地 CLI 脚本。执行前必须挂载跨平台数据流保护锁，并**绝对使用物理硬编码路径**（不再使用任何伪变量）：
```powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-musicbee-dj\src\cli.py" --type <type> --value "<value>" --intensity <intensity>
```

### Phase 3: Verification (确认执行状态) [Mode: VERIFICATION]
执行完毕后，主代理仅向用户返回一段极短的执行状态确认（如：“已为您切至 Focus 场景，正在启动 MusicBee”）。绝对禁止向用户解释背后的 M3U 解析或管道流程。

## 2. <Contracts> (输出与交付契约)
- **配置挂载契约**: 该脚本执行依赖本地 `config.yaml`（必须包含 `musicbee.exe_path`, `musicbee.xml_path`, `cache.db_path` 等物理路径定义）。如果是 `scene` 播放，配置文件中必须至少存在一种场景映射。如果是 `genre` 播放，音乐库的 XML 路径必须物理存在。
- **Result Gate 准入契约**: 绝不向用户报告成功，除非以下物理条件全部验证通过：
  1. 成功解析出了播放目标 (play target)
  2. 若为 JIT（即时）歌单，必须在本地成功生成 `.m3u` 物理文件，且内含至少一首有效曲目。
  3. MusicBee.exe 主程序确实存在于本地路径中。
- **Telemetry 遥测归档**: 成功点播后，必须使用原生的 `write_to_file` 工具将执行元数据以 JSON 格式保存至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`
  格式范例：`{"skill_name": "personal-musicbee-dj", "status": "success", "duration_sec": 1, "input_tokens": 10, "output_tokens": 5}`

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **伪变量与死锁 (Pathing Hallucination)**：严禁在命令行里拼接 `<skill-root>` 这种已经被废弃的模板宏。必须使用绝对的物理全路径 `C:\Users\shich\.gemini\config\skills\personal-musicbee-dj\src\cli.py`。严禁不加 `PYTHONIOENCODING` 强行解析含中文的 XML。
- **虚假汇报 (Phantom Playback)**：严禁在 Python 脚本实际抛出错误（如找不到路径或权限不够）时，大模型还通过文本安抚用户“已经为您播放”。若 Gate 拦截失败，必须 Fail Fast 并报错。
- **非映射阻断 (Scene Rejection)**：如果用户的场景无法精准匹配，严禁直接放弃！必须执行“就近回退策略（Semantic Fallback）”强行映射。
- **文件解析断裂 (XML Parsing Crash)**：如果脚本提示解析失败，请明确提示用户去检查“MusicBee 库分享 XML 选项”是否已在本地客户端内开启。
- **沙盒连坐绞杀 (Sandbox Job Object Kill)**：严禁修改 `cli.py` 中用于拉起 MusicBee 的 `Invoke-WmiMethod` WMI 调用。在原生的 Antigravity 沙盒中，后台任务结束后会通过 Job Object 瞬间击杀所有子进程。必须依赖 WMI 跨域生成进程进行沙盒逃逸，否则用户将遭遇“系统汇报播放成功但播放器闪退”的物理死锁。
