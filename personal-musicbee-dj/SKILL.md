---
name: personal-musicbee-dj
version: 9.0.0
tier: action-allowed
description: 'MusicBee DJ。根据意图与情绪控制本地播放。将场景映射至播放参数并自动生成 M3U 歌单拉起物理进程。禁止虚假汇报播放状态。'
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

# Personal MusicBee DJ (音乐点播与场域渲染 V9.0 Native)

本技能将用户模糊的听歌意图、场景氛围（如 focus, coding, relax）转化为精准的本地 MusicBee 播放指令，并拉起物理端的音频进程。

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. un_command (调用专属的本地 CLI 脚本拉起物理进程)
2. write_to_file (落盘遥测数据)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Intent Resolution (意图解析)
解析用户的需求，提取出必须要传给控制脚本的 3 个参数：
- 	ype: 必须是 genre | scene | playlist
- alue: 具体请求的流派、场景名称或歌单名。
  *(推荐内置场景/Scene包括: ocus, elax, nergy, coding, pop。若用户给出了非标场景，必须走语义回退/Semantic Fallback就近映射。)*
- intensity: 必须是 high | normal | low

### Phase 2: Execution (拉起播放器)
必须使用原生 un_command 工具调用专属本地 CLI 脚本。执行前必须挂载跨平台数据流保护锁，并**绝对使用物理硬编码路径**：
`powershell
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\personal-musicbee-dj\src\cli.py" --type <type> --value "<value>" --intensity <intensity>
`

### Phase 3: Verification (确认执行状态)
执行完毕后，主代理仅向用户返回一段极短的执行状态确认（如：“已为您切至 Focus 场景，正在启动 MusicBee”）。绝对禁止向用户解释背后的 M3U 解析流程。

## 2. <Contracts> (输出与交付契约)
- **配置挂载契约**: 该脚本执行依赖本地 config.yaml（包含 musicbee.exe_path 等物理路径定义）。若为 scene 播放，配置文件必须至少存在一种映射。若为 genre 播放，XML 路径必须物理存在。
- **Result Gate 准入契约**: 绝不向用户报告成功，除非物理条件全部验证通过（解析目标成功、M3U生成有效、MusicBee存在）。
- **Telemetry 遥测归档**: 成功点播后，必须使用 write_to_file 将执行元数据保存至：
  C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **伪变量与死锁 (Pathing Hallucination)**：严禁在命令行里拼接被废弃的模板宏。必须使用绝对物理全路径。严禁不加 PYTHONIOENCODING 强行解析含中文的 XML。
- **虚假汇报 (Phantom Playback)**：若脚本实际报错，严禁通过文本安抚用户“已经为您播放”。必须 Fail Fast。
- **非映射阻断 (Scene Rejection)**：如果用户的场景无法精准匹配，严禁放弃！必须执行就近映射策略。
- **文件解析断裂 (XML Parsing Crash)**：如果解析失败，明确提示用户检查“MusicBee 库分享 XML 选项”是否已开启。
- **沙盒连坐绞杀 (Sandbox Job Object Kill)**：严禁修改 cli.py 中用于拉起 MusicBee 的 WMI 调用。必须依赖 WMI 跨域生成进程进行沙盒逃逸，防止沙盒后台关闭时引发播放器闪退。
