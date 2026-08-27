# 工作模式与最小流程

只选择足以回答当前决策的最低成本模式。`direct` 不创建状态，其他模式在需要保存、复核或多人协作时使用同一个 Blackboard。

## 模式路由

| 模式 | 选择条件 | 最小产出 | 必需门禁 |
|---|---|---|---|
| `direct` | 单一稳定问题；无多来源研究、量化模型或正式文件 | 结论、依据、必要限制 | 人工事实检查 |
| `brief` | 有界管理问题；通常比较2—3个选项 | 建议、条件、关键事实、风险、待验证项 | 保存时执行统一质量门禁 |
| `board-memo` | 管理层需要短决策材料 | 待决定事项、事实与未知、选项、财务影响、风险、下一验证点 | Blackboard校验；`decision_ready`时使用严格质量门禁 |
| `deep-dive` | 关键主张依赖多个研究面或冲突证据 | 可独立核验的证据链、方案比较、反证、路线图 | Blackboard校验；`decision_ready`时使用严格质量门禁 |
| `investment-case` | 涉及项目排序、预算、ROI/TCO、采购或投标承诺 | 投资组合、财务模型、敏感性、收益实现与阶段门 | 投资模型专属硬门禁；`decision_ready`时使用严格质量门禁 |

## 共同决策契约

至少明确：

- 决策及批准人；
- 受众与组织类型（医疗机构、医疗IT厂商或生态合作方）；
- 适用地区和截止日期；
- 时间范围、预算状态与资源约束；
- 成功指标、不可接受风险和当前决策阶段；
- 可使用的内部数据、保密边界和证据质量。

缺少会改变结论的字段时先追问。用户暂时无法提供时，保留缺口并把成果成熟度降为 `working_draft` 或 `blocked`，不得自行补数。

## 医疗机构侧

除战略适配和财务结果外，必须考虑患者安全、监管强制性、公共服务、临床工作量、流程采用、技术债、预算与采购周期、数据治理、运维能力和非现金价值。刚性合规、安全或连续性项目不得只按简单ROI排序。

## 医疗IT厂商侧

除客户价值外，必须考虑产品标准化率、研发和交付能力、定制边界、毛利、云与支持成本、渠道、验收、账期、回款、续费、质保和退出责任。客户ROI不能替代厂商项目经济性。

## 深度研究

1. 先列关键主张和改变决策所需的证据，不机械覆盖政策、流程、技术、经济和执行全部维度。
2. 维护证据ID、来源ID、冲突和缺口；同一来源的转载只算一个证据链。
3. 新来源不再改变关键主张、仅重复已有信息，或缺口属于未公开数据时停止扩展检索。
4. 对中心建议保留最强反证、替代解释和证伪条件。
5. 把建议转换为带责任、验收、资源、回退和退出条件的阶段门。

## 并行研究

按预计净节省而不是研究面数量决定是否并行。两个大型独立研究面可以并行；三个微小或强依赖研究面不应拆分。

并行代理不得直接同时写Blackboard。每个代理返回统一证据包，由主代理按来源URL、文件标识和证据链去重后一次性合并；冲突不能用多数表决消除。

## 成熟度

| 状态 | 含义 |
|---|---|
| `working_draft` | 关键输入或证据仍缺失，只能用于研究、讨论和补充信息 |
| `review_ready` | 分析结构、证据和风险可供管理层或专业人员复核 |
| `decision_ready` | 对应模式的业务、财务、责任、验收和合规门禁均满足，可提交有权人员决定 |
| `approved_for_execution` | 仅记录有权人员或正式流程已经作出的决定，本技能不得自行声明 |
| `blocked` | 关键上下文、数据或专业复核缺失，不得据此作出目标决定 |

## 文件交付

需要文件时才创建章节并装配。必须至少有一个非空章节；装配后运行统一质量门禁。`working_draft` 和 `review_ready` 可以带着明确披露的警告供复核；`decision_ready` 必须通过严格门禁。文件头的成熟度必须与Blackboard一致，不能用脚本成功状态替代管理结论。

## 最短工具路径

`direct` 不运行脚本。需要保存状态时，先初始化一次，然后按 section 批量更新；复杂 JSON 优先写入项目内文件后用 `@file` 读取，或用 `--value -` 从标准输入读取，避免逐字段调用和命令行转义错误。并发更新时带上最近读取的 `--expect-revision`。

```bash
python scripts/blackboard.py --workspace-root "$PROJECT_ROOT" init \
  --topic "待决定事项" --mode investment-case

python scripts/blackboard.py --workspace-root "$PROJECT_ROOT" update \
  --section quantitative_model \
  --value @/absolute/path/quantitative_model.json \
  --expect-revision 3
```

起草期间可按需运行 `blackboard.py validate` 定位缺口。只有消费纯状态的自动化才单独运行 `blackboard.py ready`；已有报告时由 `strategy_gate.py` 同时检查报告和Blackboard，避免重复执行多个等价门禁。

```bash
python scripts/assembler.py --path "$PROJECT_ROOT" \
  --output final_report.md --title "决策材料" \
  --mode investment-case \
  --blackboard "$PROJECT_ROOT/tmp/strategy_blackboard.json"

python scripts/strategy_gate.py \
  --path "$PROJECT_ROOT/final_report.md" \
  --mode investment-case \
  --blackboard "$PROJECT_ROOT/tmp/strategy_blackboard.json" \
  --strict
```

`--strict` 只用于要求无警告的正式交付；草稿和复核稿应保留并披露警告，而不是通过放宽字段或改写成熟度来消除警告。
