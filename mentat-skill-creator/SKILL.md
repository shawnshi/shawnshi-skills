---
name: mentat-skill-creator
description: 仅供显式调用，审计或维护当前 Pi 技能库的治理、触发所有权、资源清单和发布门；不承接一般单技能内容更新或安装分发。
disable-model-invocation: true
---

# Pi 本地技能库维护

## 定位与合同

- 本技能只补充当前技能库的治理规则；系统 `skill-creator` 仅在实际可用时作为通用创建方法和脚手架来源。外部 handoff 是可选能力，不是工具保证；先核对当前宿主实际暴露的技能、工具和接口，不假定本地存在 `.system` 或其他宿主组件。
- 本技能只补充本库治理。上位 `AGENTS.md` 指令链已常驻，其中已覆盖的通用授权、输出与事实规则不在此重复；用户明确请求和文件范围仍是本技能的授权边界，creator、README、门禁和工具行为均不得扩张权限。
- 将 README、manifest、门禁和测试都视为受检制品。它们冲突时停止相关修改并报告语义差异；依据上位合同和预期行为同步修复，不得自动以任一方为准，也不得修改一方来掩盖另一方的缺陷。
- 以 `SKILL.md` 为技能运行真相源。`resource-manifest.json` 只服务本库门禁；不创建、读取或维护 `skill.json`。
- 只写当前宿主模型不会稳定推断的领域规则、脆弱步骤、真实工具契约和验证方法，不复制通用说明。

## 请求路由

- 显式调用本技能进行审计、诊断、建议或编制计划：只读，禁止编辑、刷新 manifest 或生成报告文件。
- 显式调用本技能修改本库治理：按用户批准范围编辑。唯一可随技能源文件隐式更新的派生文件，是同一技能的 `resource-manifest.json`；还须由局部 `-Check` 证明过期，且用户没有用“只修改这些文件”封闭集合。根 README/AGENTS、shared 矩阵、报告、插件包、锁文件、Git 元数据及其他技能 manifest 均须另行明确授权。
- 通用新技能创建或与本库治理无关的单技能内容修订：不触发本技能；仅在实际可用时转交系统 `skill-creator` 或对应领域技能。creator 缺失不得虚构交接，也不得阻断已授权的局部维护；可依现有 README 维护流程与本库校验工具窄化修订，不因此扩大写集或要求载入本技能。
- 面向他人安装、组合多个技能或绑定 connector/MCP 的分发：仅在实际可用时转交系统 `plugin-creator`；本技能只在用户另行显式要求时预检源技能。新建或打包确实需要而当前缺失的脚手架、格式契约或校验能力，须明确报告缺失与未完成边界，不伪造产物或宣告成功。
- 从其他仓库获取技能或安装到本地：仅在实际可用时转交系统 `skill-installer`；缺失时报告能力边界，不虚构调用。安装是独立写入动作，必须由明确安装请求授权。
- GitHub 源码同步、本地安装和 Plugin 分发是三条不同路线。GitHub 同步在发布前只读验证通过后转交可用的 GitHub 发布能力（当前环境存在时优先 `github:yeet`）；`commit`、`push`、PR、发布或安装均不得由“发布准备”推定授权。

## 执行流程

1. 识别请求层级：区分只读审计、修改方案、单技能修订、批量迁移和发布准备。审计、诊断、建议或计划本身不授权写入；只有用户明确要求修改、构建、修复或实施时才进入编辑。
2. 明确用途：提取正向触发示例、相近但不应触发的示例、非目标、输入、用户可见输出、风险和完成标准；以 `references/trigger-evals.json` 为最低回归集，但不把静态夹具冒充宿主路由实测。
3. 检查现状：完整阅读目标 `SKILL.md`，盘点直接引用并核对资源存在性；在修改与验证相应分支前，按实际依赖读取相关说明、模板或脚本（description 修订核对触发与邻近边界，脚本变更读取调用方及契约，资源迁移核对全部受影响引用），不无条件展开无关引用；盘点 `scripts/`、`references/`、`assets/`、`agents/openai.yaml` 和本库 `resource-manifest.json`。保留有效资源，避免重复内容。
4. 规划最小变更：判断型工作使用目标、启发式和成功标准；顺序脆弱或结果必须一致的工作使用确定性脚本和窄参数。正文过长时按主题渐进拆分，引用尽量只保持一层。
5. 创建或修订：
   - 新技能先确认目标目录，仅在当前系统 `skill-creator` 及其初始化脚本实际可用时优先使用；缺失时按请求路由中的能力边界处理；
   - 现有技能只修改用户授权文件，先声明写集，再使用补丁式编辑并保留无关改动。小型可逆修改不要求额外基线制品，命令输出或 Diff 即可追溯；仅在改动门禁脚本、批量迁移或结构入口时，才在技能目录之外的隔离位置留一份原字节备份，并重新生成受影响技能的 `resource-manifest.json`；
   - 不生成技能内 README、安装指南、变更日志或其他不直接支持运行的文件；
   - 新增脚本只承载确定性或重复逻辑，新增资源必须被 `SKILL.md` 明确路由。
6. 更新界面元数据：当技能提供 `agents/openai.yaml` 时，解析并最小合并现有字段；不得用生成器盲目覆盖已有 `policy`、依赖或图标。校准 `display_name`、25–64 字符的 `short_description` 和显式包含 `$skill-name` 的 `default_prompt`，再运行 `scripts/validate_openai_yaml.py`。高权限治理技能默认关闭隐式调用。
7. 处理权限：用户明确要求修改、构建、修复或实施时，可执行其范围内的本地编辑和非破坏性验证。仅同一技能的 `resource-manifest.json` 可按上一节的窄条件作为派生更新；若用户用“只修改”封闭文件集合，连该 manifest 也不得追加。联网、安装依赖、控制外部应用、发送、发布、合并、删除和范围外永久写入遵循上位规则与用户明确授权；README 不得扩张权限。
8. 分层验证：依次验证结构、资源、界面元数据、脚本行为、触发边界和仓库门禁。系统校验器实际可用且适用时先使用；未提供时记录未运行原因，继续适用的本库校验，不把可选校验器缺失当作已授权局部维护的阻塞；区分内容失败与校验器、编码或环境失败，环境失败可用 UTF-8 模式重试一次。局部变更先运行选中技能门禁；修改根 AGENTS/README、shared、Gate、生成器或批量 manifest 时再运行全库门禁。单元测试只证明合同文本自洽；宿主路由与档位行为按 `references/host-routing-eval.md` 的协议由操作者执行并记录，未运行时不得以静态夹具替代。
9. 迭代：每次只修改一个相关问题组，并在相同代表性用例上复测。只有复杂技能且能力可用时才用子代理做独立前向测试；传递原始制品和最少上下文，不泄露预期答案或修复意图。
10. 汇报结果：先给出完成状态，再列出修改文件、通过的验证、未运行项、阻塞和残余风险，并注明本次实际执行的路由评测宿主表面与档位；未执行时写明未执行。不自动登记知识库或持久化到其他系统。

## 验证命令

首选跳平台的单一入口，缺 Python 3 + PyYAML 或 `pwsh` 时失败关闭：

```sh
sh scripts/gate.sh                    # 全库：元数据、单元测试、资源清单、根门禁
sh scripts/gate.sh <skill-name> ...   # 按技能作用域
```

等价的分项命令（本库根目录，`<skill-name>` 替换为目标目录名，不要求 Git 工作树）：

```powershell
python -B -X utf8 scripts/validate_openai_yaml.py --root . --include-skill <skill-name> --json
python -B -X utf8 scripts/test_mentat_skill_creator.py -v
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/generate_resource_manifests.ps1 -Root . -IncludeSkills <skill-name> -Check
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/repair_skills.ps1 -Mode Gate -Root . -IncludeSkills <skill-name>
```

改动 `scripts/` 下的门禁脚本本身会让 `mentat-skill-creator/resource-manifest.json` 过期，因为该 manifest 记录了它声明依赖的脚本哈希。顺序固定为：先改脚本，最后重新生成受影响技能 manifest，再跑门禁。

只有在修改获授权且清单确实过期时，才去掉 `-Check` 生成选中技能的 manifest；随后再次运行 `-Check` 和局部门禁。涉及根治理或批量迁移时，另运行不带 `-IncludeSkills` 的全库检查。系统 `skill-creator` 的 `quick_validate.py` 仅在本轮实际发现且适用于当前宿主格式时先运行；未提供时不猜测路径或接口，记录该项未运行。所有验证均须记录退出码。

## 门禁判定

`repair_skills.ps1 -Mode Gate` 对下表每一项按“值大于 0 即失败”处理，无阈值容忍。执行前按此表核对，不要靠试错发现阻断项；字面模式清单以 `scripts/repair_skills.ps1` 中对应的命令模式变量为唯一权威源，本节不复制字面量，避免重复维护。

| 阻断项 | 判据 |
|---|---|
| `inventory_mismatch`、`unknown_include_skills`、`unknown_exclude_skills`、`scope_overlap_skills`、`empty_selection` | 根 README 声明清单与实际技能目录不一致，或作用域参数无效 |
| `frontmatter_failures` | `name`/`description` 缺失、名称与目录不一致、无触发语境，或出现未知、重复字段 |
| `oversized_skills`、`oversized_by_estimated_tokens` | 正文超过 `-LineThreshold`（默认 500 行）或估算 token 超过 `-TokenThreshold`（默认 8000） |
| `missing_resource_manifests`、`invalid_resource_manifests`、`manifest_dependency_issues` | 缺少、过期或引用不一致的 `resource-manifest.json` |
| `openai_metadata_failures` | `agents/openai.yaml` 结构、`short_description` 长度或 `default_prompt` 中的技能标记不合格；调用策略与 frontmatter 矛盾 |
| `validator_integration_failures` | 校验器缺失、输出协议不符，或 `checked` 计数与作用域不符 |
| `deprecated_tool_skills` | 正文出现宿主耦合的旧工具名（`$DeprecatedPatterns`） |
| `foreign_runtime_skills` | 出现其他运行时的路径或标识（`$ForeignRuntimePatterns`） |
| `reasoning_directive_skills` | 要求模型词露内部推理内容或推理标签（`$ForbiddenReasoningPatterns`） |
| `hardcoded_model_skills` | 正文写死具体模型版本（`$HardcodedModelPatterns`） |
| `mandatory_subagent_skills`、`mandatory_persistence_skills` | 把子代理调用或持久化写成强制步骤 |
| `undeclared_automatic_persistence_skills`、`stale_automatic_persistence_exceptions`、`unknown_automatic_persistence_exceptions` | 自动持久化例外未声明、已过期或指向未知技能 |
| `automatic_persistence_table_malformed_rows`、`automatic_persistence_table_duplicate_skills`、`automatic_persistence_table_semantic_failures`、`automatic_persistence_opt_out_failures` | 根 README 持久化例外表的行格式、重复项、语义或退出条件不成立 |
| `skill_json_files`、`node_modules_directories` | 出现 `skill.json`，或技能内出现 `node_modules` |
| `trigger_ownership_conflicts` | 触发所有权矩阵出现冲突信号 |

非阻断但会打印：`OpenAiPolicyWarnings`。当 `agents/openai.yaml` 关闭隐式调用而 `SKILL.md` 未声明 `disable-model-invocation` 时，本宿主仍会自动触发该技能；这属于路由决策，报告给用户，不自行补齐任一侧。

校验器跳过 `.venv`、`node_modules`、`__pycache__` 与构建输出目录：技能内自带虚拟环境不会产生误报。

## 标准结构

```text
skill-name/
├── SKILL.md
├── agents/
│   └── openai.yaml          # 可选，面向界面的元数据
├── scripts/                 # 可选，确定性或重复执行逻辑
├── references/              # 可选，按需读取的领域资料
├── assets/                  # 可选，输出使用的模板或素材
└── resource-manifest.json   # 本库门禁索引，不定义技能语义
```

## 完成标准

- Frontmatter 包含 `name` 和 `description`；名称与目录匹配，描述覆盖能力和触发语境，可选字段仅使用 Pi 当前支持的集合。
- 正向与负向触发样例符合预期，相近技能的所有权已明确。
- 所有相对资源存在，脚本参数来自实际帮助或源码，界面元数据与技能一致。
- 修改过的脚本已运行代表性正向测试和必要的失败测试。
- 已按授权边界刷新必要资源清单，并运行适用的系统校验、局部门禁、全库门禁和相关单元测试；若文件范围封闭导致 manifest 不能更新，必须报告未闭环而非越权写入。
- 单元测试证明的是合同文本自洽，不是模型行为。宿主路由与档位评测按 `references/host-routing-eval.md` 执行；未执行时必须写明未执行及其覆盖边界。
- 已区分本地校验、GitHub 源码同步、本地安装与 Plugin 分发；未获得明确授权时停在相应外部动作之前。
- 验证无法运行时说明原因和替代检查；存在未解释的失败时不得宣告完成。

## 停止规则

- 用户只要求审计、诊断或建议时，在证据和建议处停止。
- 缺少会实质改变技能定位、授权范围或外部副作用的选择时，停止并请求用户决定。
- 空结果或单一校验器异常时尝试一个有意义的降级路径；不要为增加说明而重复检查。
- 同一环境故障重试一次后仍失败，报告阻塞和下一项可执行检查，不循环重试。
