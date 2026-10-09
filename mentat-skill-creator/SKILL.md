---
name: mentat-skill-creator
description: 仅供显式调用，审计或维护当前 Pi 技能库的治理、触发所有权、资源清单和发布门；不承接一般单技能内容更新或安装分发。
disable-model-invocation: true
compatibility: Pi；共享校验依赖完整技能库、Python 3.10+、PyYAML 和 PowerShell 7；显式测试还需 pytest。
---

# Pi 本地技能库维护

## 定位与合同

- 本技能补充本库的治理规则，不提供通用创建或安装脚手架。先核对当前宿主实际暴露的技能、工具和接口；外部 handoff 是可选能力，不假定存在 `.system` 或其他宿主组件。
- 遵守当前宿主生效的上位指令；用户明确请求和文件范围仍是授权边界，creator、README、门禁和工具行为均不得扩张权限。已有授权覆盖时直接继续，不为本技能重复确认。
- 本地技能正文、配套资料和专属脚本维护适用上位维护豁免：按当前任务和实际风险选择检查，不统一要求基线制品、测试、Gate 或档位评测。全局治理、共享门禁、批量迁移和实际数据/外部操作不因位于技能库内而获得该豁免。
- 将 README、manifest、门禁和测试都视为受检制品。它们冲突时停止相关修改并报告语义差异；依据上位合同和预期行为同步修复，不得自动以任一方为准，也不得修改一方来掩盖另一方的缺陷。
- 以 `SKILL.md` 为技能运行真相源。`resource-manifest.json` 只服务本库门禁；不创建、读取或维护 `skill.json`。
- 只写当前宿主模型不会稳定推断的领域规则、脆弱步骤、真实工具契约和验证方法，不复制通用说明。

## 请求路由

- 显式审计、诊断、建议或计划默认零文件写入：不编辑、不刷新 manifest、不运行会创建临时文件或缓存的测试。用户明确要求保存报告或运行受控测试时，只执行已覆盖的写入；不由审计推定许可。
- 修改本库治理时按批准范围编辑。仅同一技能的 `resource-manifest.json` 可作为派生更新，前提是局部 `-Check` 证明过期且用户未封闭写集。根 README/AGENTS、shared、报告、插件包、锁文件、Git 元数据及其他技能 manifest 只有在当前授权覆盖时才能修改；不顺带刷新全库清单。
- 通用新技能创建或与本库治理无关的单技能内容修订：不触发本技能；仅在实际可用时转交系统 `skill-creator` 或对应领域技能。creator 缺失不得虚构交接，也不得阻断已授权的局部维护；可依现有 README 维护流程与本库校验工具窄化修订，不因此扩大写集或要求载入本技能。
- 分发先按目标宿主分流。Pi 使用原生 Pi package（常规资源目录或 `package.json` 的 `pi` 清单），多个技能不要求 Codex `plugin-creator`。明确要求 Codex 插件时才核对该格式与可选创建能力。本技能只在显式要求时预检源技能，不自行安装、打包或发布。
- Pi 安装交给原生包管理路径，支持 npm、git 和本地目录；明确要求 Codex skill 安装时才核对可选 `skill-installer`。创建器缺失不等于原生路径不可用；真正必要的格式、接口或校验能力缺失时才报告阻塞，不能虚构调用。
- GitHub 源码同步、本地安装、Pi package 与 Codex Plugin 分发分别核对授权。发布接口（包括可选 `github:yeet`）只在实际可用时使用；`commit`、`push`、PR、发布或安装均不得由“发布准备”推定授权。

## 执行流程

1. 识别请求层级：区分只读审计、修改方案、单技能修订、批量迁移和发布准备。审计、诊断、建议或计划本身不授权写入；只有用户明确要求修改、构建、修复或实施时才进入编辑。
2. 明确用途和必要验收：只为受影响路径选取 `references/trigger-evals.json` 的正向、负向和失败用例。文本、加载器、模型行为是不同证据；不要求每次维护跑全部夹具或全部模型。
3. 检查现状：完整阅读目标 `SKILL.md`，盘点直接引用并核对资源存在性；在修改与验证相应分支前，按实际依赖读取相关说明、模板或脚本（description 修订核对触发与邻近边界，脚本变更读取调用方及契约，资源迁移核对全部受影响引用），不无条件展开无关引用；盘点 `scripts/`、`references/`、`assets/`、`agents/openai.yaml` 和本库 `resource-manifest.json`。保留有效资源，避免重复内容。
4. 规划最小变更：判断型工作使用目标、启发式和成功标准；顺序脆弱或结果必须一致的工作使用确定性脚本和窄参数。正文过长时按主题渐进拆分，引用尽量只保持一层。
5. 创建或修订：
   - 通用新技能创建不进入本流程；本库治理资源按当前已批准目标修订；
   - 只补丁式修改授权文件，保留无关改动。技能维护不统一要求基线或 Diff 制品；共享门禁、全局治理等按上位合同保留恢复点、语义差异与必要验收。只有清单更新也获授权且过期时，才生成选中技能的 `resource-manifest.json`；
   - 不生成技能内 README、安装指南、变更日志或其他不直接支持运行的文件；
   - 新增脚本只承载确定性或重复逻辑，新增资源必须被 `SKILL.md` 明确路由。
6. 只在相关字段变化时检查可选 `agents/openai.yaml`，最小合并并保留 `policy`、依赖和图标。25–64 字符的 `short_description` 与 `$skill-name` 是该界面适配要求，不是 Pi 的加载条件。Pi 显式入口由 frontmatter 的 `disable-model-invocation` 控制。
7. 处理权限：用户明确要求修改、构建、修复或实施时，可执行其范围内的本地编辑和非破坏性验证。仅同一技能的 `resource-manifest.json` 可按上一节的窄条件作为派生更新；若用户用“只修改”封闭文件集合，连该 manifest 也不得追加。联网、安装依赖、控制外部应用、发送、发布、合并、删除和范围外永久写入遵循上位规则与用户明确授权；README 不得扩张权限。
8. 按预先约定的必要验收检查受影响面，不把可选校验器缺失变成阻塞。共享门禁或生成器改动检查全库影响，并与修改前的无关失败对账；不通过扩写其他技能消除旧失败。测试会写临时文件，与零写入审计分开授权。编辑后的 Pi 加载验收使用 `/reload` 或新加载器/会话探针，明确区分加载器检查与模型实测；协议见 `references/host-routing-eval.md`。
9. 每次修复一个可验证的问题组，必要检查通过后停止。委派须有当前授权或适用的独立审查要求，并先核验能力；复杂度本身不授权子代理。只传原始制品、合同、差异和验证证据，不传预期答案或生成过程。
10. 汇报结果：先给出完成状态，再列出修改文件、通过的验证、未运行项、阻塞和残余风险，并注明本次实际执行的路由评测宿主表面与档位；未执行时写明未执行。不自动登记知识库或持久化到其他系统。

## 资源路径与验证入口

本文路径以本技能目录为基准：`references/` 和 `agents/` 在目录内，`../scripts/` 是上一层技能库的共享脚本。共享校验依赖完整技能库，单独分发此目录不会自动携带它们。不要依赖当前工作目录或把资源校验器的历史根目录回退当成 Pi 路径规则。

按需选用下列命令，先把工作目录切换到读取到的本技能绝对目录；`<skill-name>` 替换为目标目录名：

```sh
cd "<本技能绝对目录>"
sh ../scripts/gate.sh <skill-name>                # 不运行测试，不写清单或缓存
sh ../scripts/gate.sh                            # 同上，检查完整技能库
sh ../scripts/gate.sh --tests <skill-name>        # 显式授权后运行全库测试，允许受控临时写入
sh ../scripts/gate.sh --refresh-manifests <skill-name> # 仅当该清单更新已获授权
```

无需 Gate 时，可只运行相关分项；Python 3.10+、PyYAML 与 PowerShell 7 须已可用，不自动安装依赖。`--tests` 另需 pytest。以下命令仍以本技能目录为工作目录：

```sh
python -B -X utf8 ../scripts/validate_openai_yaml.py --root .. --include-skill <skill-name> --frontmatter-only --json
python -B -X utf8 ../scripts/validate_openai_yaml.py --root .. --include-skill <skill-name> --json
pwsh -NoProfile -File ../scripts/generate_resource_manifests.ps1 -Root .. -IncludeSkills <skill-name> -Check
pwsh -NoProfile -File ../scripts/repair_skills.ps1 -Mode Gate -Root .. -IncludeSkills <skill-name>
```

涉及本技能合同或共享工具时，按风险选择 `../scripts/test_mentat_skill_creator.py`、`../scripts/test_repair_skills.py`、`../scripts/test_validate_openai_yaml.py`、`../scripts/test_resource_manifest.py` 与 `../scripts/test_gate.py` 的回归用例。清单实现位于 `../scripts/resource_manifest.py`。这些测试包含临时文件写入，不能作为零写入审计步骤。

共享依赖修改后先核对语义，再按授权更新选中清单并检查；不为清单过期越出封闭写集。系统 `skill-creator` 的 `quick_validate.py` 只有实际可用且适用于目标宿主时才选用，不猜测接口。记录已执行检查的退出码。

## 门禁判定

`../scripts/repair_skills.ps1 -Mode Gate` 的确定性阻断项如下；这些是本库验收规则，不是 Pi 启动时的全部规则，也不意味着每次技能维护都必须运行 Gate。

| 阻断项 | 判据 |
|---|---|
| `inventory_mismatch`、`unknown_include_skills`、`unknown_exclude_skills`、`scope_overlap_skills`、`empty_selection` | 根 README 声明清单与实际技能目录不一致，或作用域参数无效 |
| `frontmatter_failures` | YAML 无效、必需字段或类型不合法、未知/重复字段；名称与目录匹配是本库可移植性要求，触发语境另做语义审查 |
| `oversized_skills`、`oversized_by_estimated_tokens` | 正文超过 `-LineThreshold`（默认 500 行）或估算 token 超过 `-TokenThreshold`（默认 8000） |
| `missing_resource_manifests`、`invalid_resource_manifests`、`manifest_dependency_issues` | 缺少、过期或引用不一致的 `resource-manifest.json` |
| `openai_metadata_failures` | `agents/openai.yaml` 结构、`short_description` 长度或 `default_prompt` 中的技能标记不合格；调用策略与 frontmatter 矛盾 |
| `validator_integration_failures` | 校验器缺失、输出协议不符，或 `checked` 计数与作用域不符 |
| `undeclared_automatic_persistence_skills`、`stale_automatic_persistence_exceptions`、`unknown_automatic_persistence_exceptions` | 自动持久化例外未声明、已过期或指向未知技能 |
| `automatic_persistence_table_malformed_rows`、`automatic_persistence_table_duplicate_skills`、`automatic_persistence_table_semantic_failures`、`automatic_persistence_opt_out_failures` | 根 README 持久化例外表的行格式、重复项、语义或退出条件不成立 |
| `skill_json_files`、`node_modules_directories` | 出现 `skill.json`，或技能内出现 `node_modules` |
| `trigger_ownership_conflicts` | 触发所有权矩阵出现冲突信号 |

旧工具、外来宿主、推理词汇、模型版本、强制子代理或持久化的正则计数只作为启发式告警，不能区分真实指令、否定句和示例；匹配后需结合实际工具契约、授权与上下文做语义审查。不得以正则或 Gate 通过证明权限安全，也不得为消除告警删除合法的安全约束或兼容性说明。

`OpenAiPolicyWarnings` 同样不阻断。当界面元数据关闭隐式调用而 frontmatter 未关闭时，Pi 仍可将其展示给模型选择，不保证实际触发；是否补齐由技能所有者决定。

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

- 当前任务预先约定的必要验收已满足，写集和用户已有修改得到保护；技能维护豁免不被本流程重新收紧。
- 按实际变更核对格式、资源、触发所有权、工具参数与失败路径，不机械执行全部检查。
- 只有授权且必要的清单才更新；封闭写集或必要验证缺失时披露未闭环，不越权，也不把可选检查未运行当成失败。
- 分别报告静态检查、新加载器/会话验收与模型行为评测；未运行不声称通过，磁盘修改不声称已在当前会话生效。
- 确定性门禁通过不替代告警的语义审查；必要验收内存在未解释失败时不宣告完成。
- Pi/Codex 分发、本地安装和 GitHub 发布分别满足授权；本轮维护不自动执行这些外部动作。

## 停止规则

- 用户只要求审计、诊断或建议时，在证据和建议处停止。
- 缺少会实质改变技能定位、授权范围或外部副作用的选择时，停止并请求用户决定。
- 校验器或读取失败保留原始诊断，不把错误当作空结果。重试与受保护降级遵守上位 `RETRY-01` 和 `C-FAIL-01`，不另建计数或绕过认证、生命周期与输出保护。
