---
name: personal-musicbee-dj
description: MusicBee DJ for local playback control. Use when the user wants to hear music, open MusicBee, switch playlists, or describe a mood, scene, or genre such as focus, relax, coding, pop, jazz, or energy. The skill resolves intent into genre/scene/playlist parameters, generates a just-in-time M3U playlist from the local MusicBee XML library when needed, and launches MusicBee with a validated local play target.
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

# Personal MusicBee DJ (V4.0: Runtime-Resolved Edition)

This skill turns vague listening intent into a real local MusicBee playback action.

## When to Use

- The user asks to hear music, open MusicBee, switch playlists, or set a background mood.
- The user describes a scene such as focus, relax, coding, pop, jazz, energy, calm, housework, workout, or similar.

## Intent Contract

Resolve three parameters before execution:

- `type`: `genre | scene | playlist`
- `value`: the requested genre, scene, or playlist target
- `intensity`: `high | normal | low`

## Scene Routing

Preferred built-in scenes:

- `focus`
- `relax`
- `energy`
- `coding`
- `pop`

If the user gives a non-canonical scene, do not fail immediately. Use semantic fallback and route it to the nearest configured scene.

## Execution Workflow

1. Resolve `type`, `value`, and `intensity`.
2. Resolve the active skill root for the current copy of this skill.
3. Execute the local CLI from that skill root:

```bash
python "<skill-root>\src\cli.py" --type <type> --value "<value>" --intensity <intensity>
```

4. The CLI must validate config, generate a playable target, and enforce the result gate before MusicBee is launched.
5. Return a short status line to the user. Do not explain the whole pipeline unless the user asks.

## Config Contract

The active skill copy must provide these fields in `config.yaml`:

- `musicbee.exe_path`
- `musicbee.xml_path`
- `cache.db_path`
- `playlist.output_m3u`
- `playlist.max_tracks_per_session`
- `scenes`

For `scene` playback, `scenes` must contain at least one configured scene.
For `genre` or `scene` playback, the XML path must exist.

## Result Gate

Do not report success unless all applicable conditions are true:

1. A play target was resolved.
2. For JIT playlists, the generated `.m3u` file exists.
3. For JIT playlists, at least one valid track was exported.
4. MusicBee executable exists.

If the gate fails, stop and report the real reason.

## Runtime Failure Notes

- Unmapped scenes must go through semantic fallback, not immediate abort.
- Do not hardcode `.gemini` or `.codex` into execution instructions.
- If XML parsing fails, tell the user to check MusicBee XML sharing.
- If MusicBee path is invalid, fail fast.

## Runtime Telemetry Notes

After a successful run, persist execution metadata to:
`C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

JSON format:
`{"skill_name": "personal-musicbee-dj", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## Workflow
- Follow the existing phases, scripts, and handoff rules in this skill. Do not skip validation or approval gates already defined above.

## Resources
- Use this skill directory's bundled scripts, references, assets, examples, prompts, and agents as needed. Load only the specific resource needed for the current request.

## Playback Output Contract
- Final output must match the user request, preserve the skill's domain contract, and include validation evidence or an explicit reason validation could not run.

## Failure Modes
- If required inputs, local files, evidence, permissions, or validation steps are missing, stop the risky action, state the blocker, and choose the narrowest recovery path.

## Output Contract
- Final output must match the user request, preserve the skill's domain contract, and include validation evidence or an explicit reason validation could not run.

## Telemetry
- When persistent logging is available, record task type, inputs, outputs, validation status, failures, and follow-up risks in the local skill-audit path.
