# 配置分析与支持边界

只读分析配置、检查路径，不修改 MusicBee、注册表、插件、槽位或曲库标签。用户要求生成歌单不等于允许更改音乐文件；已有明确授权覆盖时直接复用，不重复确认。

## 当前入口

- `src/cli.py --check`：配置和路径检查，不读曲库、不建补全任务、不启动播放器。它不证明子代理服务、音频解码或实际播放可用。
- `--dry-run --explain`：基于 XML 的只读选曲；不是实际歌曲标签刷新后的生产预演。
- `--generate-only`：生成歌单，不查询或启动播放器。标签缺失且调用方未核验补全权限时，返回退出码 3、`tag_completion_authorization_required`，不创建补全任务。
- `--allow-tag-completion`：只在调用方已核验当前或既有明确授权覆盖目标曲库、公开研究、任务文件及限定标签回写后传入。该参数或本文件都不能创造权限。
- `src/pilot.py`：用户明确要求时准备合成建议之外的本地待审核 CSV，不回写音乐文件，不改设置。

路径以 `config.yaml` 及非空的 `MUSICBEE_EXE_PATH` / `MUSICBEE_XML_PATH` 为准。配置中的目录不等于自动授权；换机器、换用户或换曲库须重新核对范围。依赖缺失只报告，不自动安装。

## 暂不支持的历史预览入口

本目录仍保留 audio/classifier/runtime 相关历史脚本，但它们不是当前技能的受支持路由。原有 `AUDIO_PREVIEW.md`、`CLASSIFIER_PREVIEW.md`、`RUNTIME.md`、三个 requirements lock、`classifier-models.json` 和 `classifier-prompts.json` 缺失；不猜测重建锁文件、模型、提示或审核结果，不删除历史脚本。`runtime-manifest.json` 存在也不证明运行环境已通过验证。

请求音频分类、校准或此类预览时，报告该支持缺口，停在读取真实音频或安装依赖之前。恢复这些入口需要单独确定来源、依赖与验收范围。

## 新会话与服务验证

专用 `musicbee-tags` 角色由主进程从技能 `templates/` 复制到当次任务 `.pi/agents/`，不修改全局 researcher。角色保留当前研究模型 `antigravity/gemini-3.8-flash`，与默认主模型 GPT-6.1 Sol 分开，不推定两者行为相同。

公开搜索仅允许 `google_search`，走 Antigravity Grounding，固定使用 `gemini-3.8-flash`（底层请求 ID `gemini-3.8-flash-low`），不自动降级到旧模型。全局 `pi-web-access` 的 `webSearch` 工具已停用，其他工具和显式命令保留原配置；本角色不再允许 Gemini API 搜索或 URL 提取。Antigravity 搜索默认值是本地已安装包补丁，包升级可能覆盖，届时须重新核验。

修改技能后 `/reload` 或新会话才能验证自动路由。真正派发前核对任务 cwd 下的原生子代理角色、模型和网络工具注册。静态发现、合成测试和配置检查不能代替真实启动或身份认证验证。

研究模型的任务成功率、版本识别、来源支持和成本尚需按 [评估说明](evaluation.md) 实测；不把本地回归测试称为模型效果评估。
