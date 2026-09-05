---
name: mentat-skill-creator
description: 维护当前本地 Codex skills 库的仓库级治理合同，审计或修订根 AGENTS/README、资源清单、触发所有权、批量迁移与发布门禁。仅在用户显式调用本技能处理本库治理时使用；通用新技能创建、与本库治理无关的单技能内容更新或可安装插件打包不应触发，分别使用系统 skill-creator、对应领域技能或 plugin-creator。
---

# 本地 Codex 技能库维护

## 定位与合同

- 将系统 `skill-creator` 作为通用创建方法和脚手架来源；本技能只补充当前技能库的治理规则。
- 遵循系统、开发者和 Codex 已加载的 `AGENTS.md` 指令链；在这些上位约束内，以用户明确请求和文件范围作为授权边界。系统 creator、README、门禁和工具行为均不得扩张权限。
- 将 README、manifest、门禁和测试都视为受检制品。它们冲突时停止相关修改并报告语义差异；依据上位合同和预期行为同步修复，不得自动以任一方为准，也不得修改一方来掩盖另一方的缺陷。
- 以 `SKILL.md` 为技能运行真相源。`resource-manifest.json` 只服务本库门禁；不创建、读取或维护 `skill.json`。
- 只写 Codex 不会稳定推断的领域规则、脆弱步骤、真实工具契约和验证方法，不复制通用说明。
- 不要求隐藏推理，不虚构工具或运行时协议，不硬编码机器专属路径。

## 请求路由

- 显式调用本技能进行审计、诊断、建议或编制计划：只读，禁止编辑、刷新 manifest 或生成报告文件。
- 显式调用本技能修改本库治理：按用户批准范围编辑。唯一可随技能源文件隐式更新的派生文件，是同一技能的 `resource-manifest.json`；还须由局部 `-Check` 证明过期，且用户没有用“只修改这些文件”封闭集合。根 README/AGENTS、shared 矩阵、报告、插件包、锁文件、Git 元数据及其他技能 manifest 均须另行明确授权。
- 通用新技能创建或与本库治理无关的单技能内容修订：转交系统 `skill-creator` 或对应领域技能。
- 面向他人安装、组合多个技能或绑定 connector/MCP 的分发：转交系统 `plugin-creator`；本技能只在用户另行显式要求时预检源技能。
- 从其他仓库获取技能或安装到本地：转交系统 `skill-installer`；安装是独立写入动作，必须由明确安装请求授权。
- GitHub 源码同步、本地安装和 Plugin 分发是三条不同路线。GitHub 同步在发布前只读验证通过后转交可用的 GitHub 发布能力（当前环境存在时优先 `github:yeet`）；`commit`、`push`、PR、发布或安装均不得由“发布准备”推定授权。

## 执行流程

1. 识别请求层级：区分只读审计、修改方案、单技能修订、批量迁移和发布准备。审计、诊断、建议或计划本身不授权写入；只有用户明确要求修改、构建、修复或实施时才进入编辑。
2. 明确用途：提取正向触发示例、相近但不应触发的示例、非目标、输入、用户可见输出、风险和完成标准；以 `references/trigger-evals.json` 为最低回归集，但不把静态夹具冒充宿主路由实测。
3. 检查现状：完整阅读目标 `SKILL.md` 及其直接引用；盘点 `scripts/`、`references/`、`assets/`、`agents/openai.yaml` 和本库 `resource-manifest.json`。保留有效资源，避免重复内容。
4. 规划最小变更：判断型工作使用目标、启发式和成功标准；顺序脆弱或结果必须一致的工作使用确定性脚本和窄参数。正文过长时按主题渐进拆分，引用尽量只保持一层。
5. 创建或修订：
   - 新技能先确认目标目录，并优先使用当前系统 `skill-creator` 提供的初始化脚本；
   - 现有技能只修改用户授权文件，使用补丁式编辑并保留无关改动；
   - 不生成技能内 README、安装指南、变更日志或其他不直接支持运行的文件；
   - 新增脚本只承载确定性或重复逻辑，新增资源必须被 `SKILL.md` 明确路由。
6. 更新界面元数据：当技能提供 `agents/openai.yaml` 时，解析并最小合并现有字段；不得用生成器盲目覆盖已有 `policy`、依赖或图标。校准 `display_name`、25–64 字符的 `short_description` 和显式包含 `$skill-name` 的 `default_prompt`，再运行 `scripts/validate_openai_yaml.py`。高权限治理技能默认关闭隐式调用。
7. 处理权限：用户明确要求修改、构建、修复或实施时，可执行其范围内的本地编辑和非破坏性验证。仅同一技能的 `resource-manifest.json` 可按上一节的窄条件作为派生更新；若用户用“只修改”封闭文件集合，连该 manifest 也不得追加。联网、安装依赖、控制外部应用、发送、发布、合并、删除和范围外永久写入遵循上位规则与用户明确授权；README 不得扩张权限。
8. 分层验证：依次验证结构、资源、界面元数据、脚本行为、触发边界和仓库门禁。先使用系统校验器；区分内容失败与校验器、编码或环境失败，环境失败可用 UTF-8 模式重试一次。局部变更先运行选中技能门禁；修改根 AGENTS/README、shared、Gate、生成器或批量 manifest 时再运行全库门禁。
9. 迭代：每次只修改一个相关问题组，并在相同代表性用例上复测。只有复杂技能且能力可用时才用子代理做独立前向测试；传递原始制品和最少上下文，不泄露预期答案或修复意图。
10. 汇报结果：先给出完成状态，再列出修改文件、通过的验证、未运行项、阻塞和残余风险。不自动登记知识库或持久化到其他系统。

## 验证命令

本库严格清单和元数据门禁需要 Python 3 与 PyYAML；缺失时失败关闭，安装依赖仍须明确授权。先运行本轮实际加载的系统 `skill-creator` 所提供的 `quick_validate.py`，再将 `<skill-name>` 替换为目标目录名执行本库校验：

```powershell
python -B -X utf8 scripts/validate_openai_yaml.py --root . --include-skill <skill-name> --json
python -B -X utf8 scripts/test_mentat_skill_creator.py -v
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/generate_resource_manifests.ps1 -Root . -IncludeSkills <skill-name> -Check
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/repair_skills.ps1 -Mode Gate -Root . -IncludeSkills <skill-name>
```

只有在修改获授权且清单确实过期时，才去掉 `-Check` 生成选中技能的 manifest；随后再次运行 `-Check` 和局部门禁。涉及根治理或批量迁移时，另运行不带 `-IncludeSkills` 的全库检查。所有验证均须记录退出码；静态 trigger eval 只证明合同完整，实际模型路由仍需宿主级评测。

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
- 已区分本地校验、GitHub 源码同步、本地安装与 Plugin 分发；未获得明确授权时停在相应外部动作之前。
- 验证无法运行时说明原因和替代检查；存在未解释的失败时不得宣告完成。

## 停止规则

- 用户只要求审计、诊断或建议时，在证据和建议处停止。
- 缺少会实质改变技能定位、授权范围或外部副作用的选择时，停止并请求用户决定。
- 空结果或单一校验器异常时尝试一个有意义的降级路径；不要为增加说明而重复检查。
- 同一环境故障重试一次后仍失败，报告阻塞和下一项可执行检查，不循环重试。
