---
name: personal-musicbee-dj
description: 管理本地 MusicBee 歌单与播放；明确补全标签请求使用专用 JSON 研究角色串行研究并受控回写五字段。歌单缺标签时仅在已有明确授权覆盖后研究当次必要字段；支持只生成不播放、只读预览和配置分析，不改其他标签、播放统计或 MusicBee 设置。
disable-model-invocation: false
---

# MusicBee 歌单、播放与标签补全

## 入口路由

- “补全歌曲标签 / 补全曲库标签”：读取 [标签补全流程](references/tag-completion.md)，按当前或可核验的既有明确授权范围扫描、输出十列 CSV；专用 musicbee-tags 串行研究，默认每批 10 首、最多 25 首。主控逐字段核验来源、固定审核回执后串行回写；已有合法值不覆盖，无法确认不编造。仅扫描/CSV 不写音乐文件。
- “生成歌单”：使用 `src/cli.py --generate-only`，不等于播放或标签回写。缺标签而调用方未核验补全权限时返回退出码 3、`tag_completion_authorization_required`，不建补全任务；已有明确授权覆盖时直接加 `--allow-tag-completion`，接纳 `needs_tag_completion` 后按上述流程执行，不重复确认。只研究当次场景/能量/人声/情绪要求需要的字段。审核、回写或明确无可写值，并 verify 对账后才携 `--completion-task` 续跑。单次累计最多 100 首，不静默研究全库。
- 只读/预览/`--dry-run`/`--check`：不派发 researcher、不改标签、不创建补全任务。
- 播放/追加：仍遵守下列播放器和队列授权规则；既有歌单不自动改写或重排。
- 自动发现已启用；修改后须 `/reload` 或新会话核验新描述和自然语言路由。专用角色与工作流的模型效果另按 [评估说明](references/evaluation.md) 验证，不把主模型 Sol 的文档当作 Gemini 研究行为证明。

## 环境要求

- 播放入口仅在 Windows、MusicBee 已安装、Python 和 PyYAML 可用且 `config.yaml` 有效时执行。`--generate-only` 和 `--dry-run` 不要求安装或启动播放器；生成仍须可读 XML 与本地文件。标签扫描/回写使用已核验、技能内置的 Mutagen，不安装全局包。合成回归测试另需 pytest、ffmpeg 和当前 Pi 的 Node 运行时；不自动安装依赖。
- `config.yaml` 保留已核验的本机程序和 XML 路径。非空的 `MUSICBEE_EXE_PATH` / `MUSICBEE_XML_PATH` 可覆盖它们；相对路径仍以技能目录为基准。新机器必须核查实际路径，不复制猜测值。
- 先确认 `src/cli.py` 存在，再运行 `python -B -X utf8 src/cli.py --check`。该探针只验证配置及文件存在，不读取真实曲库、不生成歌单、不启动播放器。
- XML 必须为 MusicBee 导出的 iTunes 兼容曲库文件。已兼容 `演出者/艺术家/Artist`、`专辑/Album`、`流派/Genre` 及 `Artist1…/Genre1…` 多值，合并后按个人艺人成员做重复控制；名称中的逗号和 `&` 不作为分隔符。环境缺失时报告缺项，不修改系统配置。
- 可选 `DJ_VOCALS` 已接入读取与人声门禁，值为 `vocal`、`instrumental`、`unknown`；明确值优先于 Genre，明确 unknown 或无效值不降级为器乐判断。字段缺失/空白才保留原 Genre 回退。`DJ_ENERGY`、`DJ_SCENE` 已接入代码、通过合成测试及本机各一首 FLAC、ID3v2.3 MP3 的 unknown 出口/读取测试；其他格式和真实分类值仍未核验，不宣称仅创建字段就能用于选曲。`DJ_ENERGY` 为 low/medium/high/unknown；明确 unknown 不通过 low/high 门禁，normal 不限能量。`DJ_SCENE` 只接受配置中规范标识，多个场景以分号分隔；明确字段优先于旧 Genre，无效/unknown 不回退。
- 保留 `语言/Language`、作曲者、作品及乐章名称供核查，去重身份使用作品/乐章上下文；古典曲目缺少可靠作品或乐章身份时仅按文件路径去重，不合并泛化的速度标题。已支持显式语言要求、排除及偏好，但不声称已成为完整的作品筛选器。XML 缺少 BPM 不等于音频标签缺少 BPM。

## 只读选曲与证据报告

```powershell
python -B -X utf8 src/cli.py --type scene --value focus --dry-run --explain --seed 19
# 严格要求明确场景、能量和无人声标签；不足就报告，不用旧流派补齐
python -B -X utf8 src/cli.py --type scene --value focus --no-vocals --strict-evidence --dry-run --explain
# 人声曲只接纳已知英语，确定器乐不受歌词语言条件限制
python -B -X utf8 src/cli.py --type scene --value focus --language eng --dry-run --explain
```

- `--dry-run` 不生成任务目录、M3U、JSON 缓存，不查询播放器进程，不发送播放/队列请求；仅打印结果。`--explain` 单独使用不构成只读模式，须与 `--dry-run` 配对。
- `--language`、`--exclude-language` 为硬条件，支持常用 ISO 别名、English/Chinese/Japanese/Korean/French/German/Spanish/Italian 名称及对应中文名称；未知人声语言不通过，确定器乐豁免。`--prefer-language` 是同分候选的软偏好，不把地域或 Genre 当作语言。
- `--mood` 为硬条件、`--prefer-mood` 为软偏好，可重复。支持补全流程中的 MusicBee 情绪枚举，也兼容旧 neutral、warm、joyful、melancholic、tense、introspective、calm、energetic；保留不同细分值，不靠 Genre、BPM 或曲名生成。原 Happy/Sad 别名兼容规则保留。calm/energetic 在能量参与评分时不重复作为独立情感色彩加分。
- `--bpm-min/max` 为 1–500 的已知 BPM 硬范围，未知节奏被排除；明确 DJ_ENERGY 不得覆盖限制。速度文本只保留、不转成猜测 BPM，也不重复计权。
- `--strict-evidence` 要求本次场景/low-high/无歌词对应的明确 DJ 标签，禁止旧 Genre/BPM 回退；默认保留兼容回退但逐项报告来源。它证明元数据满足契约，不证明已试听或音频分类准确。
- 评分先于来源配额分配：场景／情绪／能量／流派／节奏起始权重 35/25/20/10/10；只激活有目标的维度，缺失目标证据不从分母删除。Genre 回退、普通标签和 DJ 字段的可用系数是设计参数，不是准确率或用户喜好概率。
- 输出匹配分、证据覆盖、未知字段、流派回退、候选短缺、配额目标／实际／偏差、间隔放宽。近期新增来源只取有有效日期的最近窗口，不把未知日期算作新增。


## 播放工作流程

1. 从请求提取：
   - `type`：`genre`、`scene` 或 `playlist`
   - `value`：流派、场景别名，或用户明确指定的已有本地 `.m3u` / `.m3u8` / `.mbp` 文件路径。不能用命名歌单字符串冒充已解析的歌单。
   - `intensity`：用户明确指定时使用 `high`、`normal` 或 `low`；否则采用配置的场景强度，流派/歌单默认为 `normal`。
   - “夜间思考 / night thinking / 思考 / 专注 / 阅读”映射为 `focus`，默认 `low`；“放松 / 助眠”映射为 `relax`，默认 `low`。未识别的场景失败并报告，不回退到 `pop`。
   - `low/high` 优先按明确 `DJ_ENERGY` 等级筛选；明确 unknown/无效值被排除，缺失/空值才回退到旧 BPM/流派规则。旧回退中未知 BPM 可保留，但不调整音量，不保证安静或无歌词。
   - 原句中的艺人/流派排除分别传入可重复的 `--exclude-artist` / `--exclude-genre`。`--value` 只做场景别名识别，不是完整自然语言解析器；含否定的分句不作为正向场景，多个正向场景冲突时先澄清。
   - 用户明确要求无歌词时传 `--no-vocals`：优先要求 `DJ_VOCALS=instrumental`；该字段缺失/空白时才使用明确器乐流派标签并排除人声标签。明确 unknown、无效值、古典、爵士或未知标签本身不证明无歌词。这是标签门禁，不是音频检测。
   - 用户指定时长时传 `--minutes <正数>`：按 XML 的毫秒时长筛选完整曲目，不超过预算；排除未知时长，不剪断歌曲，不保证填满预算。未指定时不擅自添加时长限制。
   - 当次排除曲目/专辑用可重复的 `--exclude-track` / `--exclude-album`；当次艺人偏好用 `--prefer-artist`，只提升相应候选优先级，不保证全部来自该艺人。
   - 当次探索强度用 `--familiarity balanced|familiar|explore`；分别使用配置比例、80/15/5、30/50/20 的熟悉/少听/新增来源配额。它们是明确选择的试用策略，不是推定的个人喜好；不写回配置或保存反馈。
   - 调试复现可用 `--seed <整数>`；只保证同一候选集和同一版本算法下的可复现性，不保存会话档案。
   - 明确要求完整专辑、连续乐章或原始顺序时，不用场景抽样拼凑作品。仅使用用户提供的完整歌单文件，保持文件内容不变；没有该文件就说明能力缺口，不扫描私人歌单或猜测乐章顺序。
2. 用户明确要求播放即构成对该目标提交请求的授权。默认 `--queue play`；脚本只读核查 MusicBee 进程是否存在，无法确认正在播放。有进程且未明确授权覆盖时停止并询问替换/追加选择，进程查询失败也停止，不能当作未运行。用户已经明确要求替换当前队列时，直接传 `--replace-current`，不重复确认。明确追加到下一首/队尾时分别传 `--queue next` / `--queue last`；不把普通播放请求自动改成追加。私人歌单目标或多个目标有歧义时先澄清。
3. 在技能目录运行：

   ```powershell
   python -B -X utf8 src/cli.py --type <type> --value "<value>"
   # 夜间思考；等价于 focus + low
   python -B -X utf8 src/cli.py --type scene --value "夜间思考"
   # 仅当用户明确要求覆盖场景强度时追加 --intensity <intensity>
   # 用户明确要求一小时、无歌词且排除爵士时
   python -B -X utf8 src/cli.py --type scene --value focus --minutes 60 --no-vocals --exclude-genre "爵士"
   # 仅在用户明确要求队尾追加时
   python -B -X utf8 src/cli.py --type scene --value focus --queue last
   # 仅在用户明确要求替换当前队列时
   python -B -X utf8 src/cli.py --type scene --value focus --replace-current
   ```

4. 流派/场景播放在系统临时目录创建独立的 `musicbee-dj-*` 任务目录，生产 CLI 直接解析 XML 到内存后生成 M3U，不写曲库 JSON 缓存、播放次数索引或固定歌单。内部 parser 的显式缓存接口仅保留兼容及合成测试，不由 CLI 启用。失败时清理本次任务目录；不处理其他任务的文件。
5. 成功提交后只保留临时 M3U 和任务标记，并报告目录。MusicBee 可能异步读取歌单，不能在进程创建后立即删除。确认播放器不再使用该歌单且取得清理授权后，执行 `python -B -X utf8 src/cli.py --cleanup-task "<脚本报告的任务目录>"`。清理只接受系统临时目录下带标记的平坦任务目录，遇到未知文件或链接拒绝删除；不扫描或清理其他任务、旧缓存或用户文件。
6. 只有命令成功并获得可核验的进程或脚本状态后，才确认启动请求已提交。失败时返回实际错误和最小修复建议，不假报播放状态。

## 输出

简短报告歌单数量、已知时长及必要缺口、请求提交结果和临时目录，例如“已提交 12 首专注歌单，已知时长 55 分钟；实际播放未确认”。脚本还报告未知 BPM、人声/能量/场景未知曲目数及重复间隔放宽次数；`--explain` 可检查逐曲证据、回退与配额偏差，只按需要展示，不能把标签计数当作听感证明。进程创建或立即退出失败时返回原生错误。

控制依据：[MusicBee Wiki 命令行参数](https://musicbee.fandom.com/wiki/Command_Line_Parameters)，支持 `/Play`、`/QueueNext`、`/QueueLast`。文档没有只读播放状态或随机模式查询；不安装插件补足，也不因进程存在、命令返回零或歌单存在而声称正在播放。未核验播放器随机模式时提示其可能改变编排，不擅改全局播放设置。

## 配置与标签试点

用户明确要求配置分析或小样本整理时，读取 [配置与支持边界](references/MUSICBEE_SETUP.md)。历史音频/分类预览入口因资源缺失暂不作为受支持路由，不猜测恢复锁文件、安装依赖或读取真实音频。`src/pilot.py --output-dir <新的任务专属目录>` 仅准备六组、默认最多 30 首的本地待审核 CSV 和汇总回执，不写音乐标签、MusicBee 设置或播放统计，不启动播放器。建议字段保持空白，原始语种/地区分类不自动推断成音乐风格或歌词语言。CSV 仅供人工审核，不能直接导入；其中不记录新增收听历史。不默认安装插件或读取系统剪贴板。

MusicBee 正常退出后本机 XML 会刷新，运行时旧导出不能当作当前标签状态。用户主动清空 Genre 后沿用新状态，不用旧备份把 Genre 补回；场景优先读取已审核的 `DJ_SCENE`，缺失/空白才沿用 Genre；目前真实曲库的新场景字段仅核验了两条 unknown（1 FLAC、1 MP3），尚无已审核的具体分类值，不能承诺清空 Genre 后仍能有效筛选。注册、槽位映射、单文件赋值、导出与消费端识别必须分别核验。

授权只来自当前请求或可核验的既有明确授权，不来自本技能、配置注释或 CLI 参数。覆盖动作、目标、范围和副作用时直接执行 [标签补全流程](references/tag-completion.md)，不重复确认；生成歌单本身不授予标签回写权限。其他标签、槽位/设置或目标目录变更未被覆盖时补足授权，试点、CSV 或校验通过均不扩张权限。

## 边界

- 不自动记录收听偏好、播放遥测或个人资料。只有用户明确要求记住偏好时才持久化，并说明保存内容。
- 不修改 MusicBee 安装、系统服务、注册表或全局环境变量。
- `anchor_ratio`、`discovery_ratio`、`novelty_ratio` 必须为 0–1 的有限数且总和为 1。按候选目标数量分配来源配额，预留新增曲目配额；某类不足时用其他候选补齐。时长预算、排除和去重均优先于配额，不声称最终类别比例仍严格相等；播放次数仅是熟悉度代理，不代表喜欢。
- 文件门禁仅证明歌曲和 M3U 是普通文件，不证明音频可解码或播放器已接受。
- `--type playlist` 只接受已有本地歌单文件，不解析命名歌单。文件作为字面参数传递，不修改、不重排其内容；选曲、人声、时长等约束不能静默作用于既有歌单，也不静默忽略，组合这些参数时拒绝执行。
- 场景匹配优先使用明确 `DJ_SCENE`，能量筛选及编排优先使用明确 `DJ_ENERGY`；不把主观能量等级当作测量 BPM。缺失/空字段才沿用 Genre/BPM 回退。专注/放松尽量保持邻近能量与风格；运动在间隔约束允许时先按已审核能量等级爬升，缺少等级时再按已知 BPM。缺少节奏/能量信息仍做标签连贯及重复间隔控制，不退化为无条件洗牌。尽量让同艺人或同艺人/专辑组合之间隔开两首，候选不足可放宽并报告，不声称全局最优或实际听感已验证。
- 混合歌单在路径去重之外，仅对同艺人、规范化标题和明确括号版本后缀做保守去重；保留乐章编号，不合并不同艺人或缺失标题的记录；Genre 未知或作品/乐章身份不完整时保守使用文件路径，防止清空 Genre 后合并独立乐章。不下载音频、不扫描音频内容补特征、不上传私人曲库，也不推断响度、调性、音色或偏好。
- 不假设进程脱离当前任务后仍会持续运行；能验证时再说明状态。
