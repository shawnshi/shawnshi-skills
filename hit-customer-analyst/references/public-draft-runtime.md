# 公开资料草稿执行档 v1

`public_draft`是宿主能力不足时的内部执行档，不是第五种用户业务模式。它只解决“先得到一份可审阅的公开资料工作稿”，不替代认证工作区、来源捕获、候选签章、人工审批或正式发布。

## 1. 适用条件

必须同时满足：

- 业务模式为`briefing`、`standard_visit`或`strategic_account`；
- 资料范围为`public_only`；
- 当前输入不存在主体、人物、角色、时间、项目范围或目标的未解高影响冲突；
- 不使用附件、内部文件、邮件、CRM、患者资料、登录态页面或企业连接器；
- 用户只要求研究或内部工作稿，不要求建立正式客户工作区、审批、`ready`、release、写回或发送。

一封信不进入该档。认证宿主不可用时，只能说明需要的宿主能力；命中直接外发、虚构批准、患者/内部资料、未经核验的排期/效果/价格或非真人责任人时，仍走固定五段拒绝。

## 2. 选择与优先级

在任何检索或业务文件写入前运行：

```bash
python3 scripts/select_execution_profile.py \
  --business-mode <briefing|standard_visit|strategic_account|letter> \
  --data-scope <public_only|authorized_internal|mixed|unknown> \
  --requested-outcome <draft|official_workspace|ready|release|external_version|external_send>
```

存在风险指令时追加`--risk-code <code>`；存在高影响冲突时逐项追加`--unresolved-conflict <field>`。执行优先级固定为：

1. 高风险指令或`external_send`：五段拒绝，普通问题数0；
2. 高影响冲突：一个合并阻断问题；
3. 认证能力完整：只进入`signed_preflight`，仍须执行原有验签链；
4. 认证能力不足但满足公开草稿条件：进入`public_draft`；
5. 其他情况：`blocked_host_required`。

选择器只报告当前能力和允许动作，不证明环境可信。`protected_workflow_candidate`仍必须由`preflight_intake.py`、来源回执、候选签章、治理事件和commit逐层验签。

## 3. 允许的研究行为

- 只使用已确认的公开机构规范名、地区和公共主题组织未登录公开Web查询；
- 用户提供的项目、合同、内部人员、患者、CRM或邮件字符串只能作为内部问题线索，不得拼入公开搜索词或URL；
- 先查机构官网、政府、公共资源交易、正式政策和其他直接来源；
- 关键身份、职务、日期、金额、项目阶段和采购结论必须在相邻位置给出可打开的公开来源；
- 事实、分析、假设和建议分开；来源不一致时并列记录并降低结论强度；
- 选择器返回本执行档独立的`research_budget`。公开搜索与打开页面合计计入`public_tool_calls_max`，其中搜索不得超过`public_searches_max`；直接来源达到`direct_sources_target_max`后不得为凑数量继续检索。
- `delegated_workers_max=0`：公开草稿不得把研究再委派给子代理、子任务或并行研究线程。达到任一预算上限即停止检索；核心证据不足时按`partial`交付事实缺口和资料预警，不得请求用户补一句“停止检索”才收束。

该档不生成`CLM-*`、`SRC-*`、F/F2、source receipt、candidate attestation、治理事件或任何看似已认证的ID。网页引用只证明本次对话可回查，不得描述为宿主捕获或人工事实审核。

## 4. 输出契约

输出直接返回当前对话，不写客户工作区或候选目录。开头必须给出：

```text
执行档：公开资料内部草稿
ready_for_use：false
external_use：false
release_eligible：false
证据截止时间：<带时区时间>
可用范围：内部讨论和人工复核；不得直接外发或写回业务系统
```

`证据截止时间`必须使用带`Z`或`±HH:MM`偏移的RFC 3339时间，例如`2026-08-27T15:30:00+08:00`。上述六行必须从首行开始、顺序固定、各出现一次；三个状态字段不得在正文中重复或改写。

正文沿用所选业务模式的用户交付结构，但不输出内部审核谱系、机器台账或伪造状态。末尾按下列顺序各输出一次完全一致的二级Markdown标题：

- `公开来源支持、待人工复核`：逐条带相邻公开来源，不表述为宿主捕获或人工事实审核；
- `推断与建议`：说明推断依据；
- `待人工复核`：身份、时效、采购、合作或会议缺口；
- `下一步`：只给一个内部核实或拜访验证动作。

公开草稿的目标是减少后续结构性重写，但其事实、时效和适用性仍须人工复核。若公开证据不足以支撑核心结论，交付事实简报和缺口，不填满模板。

### 4.1 返回前机器验证

编排器必须把完整待返回文本直接通过标准输入交给选择器返回的`output_validation.argv`；该合同动态绑定当前Skill内的`validate_public_draft.py`绝对路径、`cwd`和`script_sha256`，执行前须逐项核对，不得自行改回相对路径，也不得为验证创建临时客户文件。

验证器不读取路径、不写文件、不回显草稿；它只返回`discovery-call-public-draft-validation/v1` JSON。只有退出码为0且`valid=true、delivery_allowed=true`时，才可把同一份、未经后续修改的文本返回当前对话。验证失败时丢弃候选文本；任何修改后必须重新验证。通过只代表`conversation_internal_draft`可在当前对话交付，返回值仍固定`formal_authorized=false、ready_for_use=false、external_use=false、release_eligible=false`，不能用于正式链授权。

验证必须是返回前最后一个工具动作；任何文字修改都会使前一次验证失效，必须对修改后的完整文本重新运行。验证器失败关闭以下可识别痕迹：

- 缺失、移动、重复或改写固定水印与三个`false`状态；
- `CLM-*`、`SRC-*`、F/F2、正式上下文字段、收据/签章或机器工件名称；
- Unix、Windows、UNC及`workspace/candidate/runtime`等文件路径；公开`http/https`来源URL不视为文件路径；
- 私网、回环、链路本地IP，`localhost`、单标签或`.local/.internal/.intranet/.corp/.lan`主机，以及非`http/https`定位符；
- 凭据、token、cookie、会话值，中国身份证号、手机号、电子邮箱，以及带值的患者、病历、CRM或内部邮件字段；URL的路径、查询键、查询值和最多三层百分号解码结果同样扫描。
- “公开来源支持、待人工复核”章节为空或没有至少一个`http/https`公开来源URL。

该扫描是公开草稿交付前的纵深防护，不替代执行档选择时的`public_only`、无敏感材料和无高影响冲突判断；调用方不得通过改写、编码或拆分敏感内容规避扫描。

## 5. 禁止行为

`public_draft`固定禁止：

- 创建或更新正式workspace、candidate、manifest或客户文件；
- 使用用户附件、内部目录、邮件、CRM、患者资料或登录态内容；
- 调用内部连接器、写回工具或发送工具；
- 生成、模拟或声称拥有request/source/candidate/governance签名；
- 标记`completed/approved/ready/release`；
- 把公开搜索结果写成我方已确认的客户内部事实；
- 把草稿直接改称正式拜访包或正式客户信。

需要正式成果时，必须在新的认证宿主请求中重新捕获完整原文和附件，从签名intake开始执行；公开草稿不能原地升级或继承为已审核成果。

## 6. 失败与恢复

| 情况 | 固定处理 |
|---|---|
| 主体/人物/时间等冲突 | 一个合并问题；零检索、零文件 |
| 要求内部资料或附件 | 阻断并说明需要认证宿主和授权范围 |
| 要求正式workspace、ready、release或客户信外发版 | 阻断正式部分；前三种模式可明确提供公开草稿选项 |
| 一封信且认证宿主不可用 | 不制稿；说明需要认证宿主 |
| 直接发送或其他高风险指令 | 固定五段拒绝；问题数0 |
| 公开来源不可访问或证据不足 | 降级为事实缺口清单，不猜测 |
