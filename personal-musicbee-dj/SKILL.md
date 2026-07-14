---
name: personal-musicbee-dj
description: 在本地 Windows 电脑上根据歌曲、歌单、流派、场景或情绪请求启动并控制 MusicBee 播放，必要时生成临时 M3U 歌单。用于“播放音乐”“放点专注音乐”“切换歌单”“用 MusicBee 播放”等明确播放请求；不用于远程设备、流媒体账户管理或未经请求记录收听偏好。
---

# MusicBee 本地播放

## 环境要求

- 仅在 Windows、MusicBee 已安装、Python 可用且 `config.yaml` 配置有效时执行。
- 先确认本地脚本存在：`src/cli.py`。环境缺失时报告缺项，不自动安装软件或修改系统配置。

## 工作流程

1. 从请求提取：
   - `type`：`genre`、`scene` 或 `playlist`
   - `value`：目标名称
   - `intensity`：`high`、`normal` 或 `low`
2. 用户明确要求播放即构成启动 MusicBee 的授权。若请求可能覆盖当前队列、播放私人歌单或含多个目标，先确认选择。
3. 在技能目录运行：

   ```powershell
   $env:PYTHONIOENCODING = "utf-8"
   python src/cli.py --type <type> --value "<value>" --intensity <intensity>
   ```

4. 将脚本生成的临时歌单保存在当前任务允许的临时位置；不要把调试日志或播放历史写入永久目录。
5. 只有命令成功并获得可核验的进程或脚本状态后，才确认已启动。失败时返回实际错误和最小修复建议，不假报播放状态。

## 输出

用一句话报告结果，例如“已启动 MusicBee，播放 Focus 场景”。必要时补充失败原因或用户需要完成的环境步骤。

## 边界

- 不自动记录收听偏好、播放遥测或个人资料。只有用户明确要求记住偏好时才持久化，并说明保存内容。
- 不修改 MusicBee 安装、系统服务、注册表或全局环境变量。
- 不假设进程脱离当前任务后仍会持续运行；能验证时再说明状态。
