# Sol 技能行为评估

这是技能维护时可选的验收说明，不是每次投资研究的前置门，也不要求读取真实持仓。

## 评估边界

- 使用 Pi 原生 CLI 与配置的 `openai-codex / gpt-6.1-sol`，不直接调用底层 API、不读取认证文件内容。
- 显式加载当前 `SKILL.md`，使用 `/skill:personal-investment-advisor` 展开；`--no-session` 不创建普通 Pi 会话文件。
- 最小规则理解探针禁用工具、MCP、扩展、全局上下文和其他技能。它能核验技能加载及模型对范围、授权、失败状态的回答，不能验证自主工具选择、真实报价或正常扩展环境。
- 只保存最终 JSON 回答与进程／settled／工具调用数等最小回执，不保存原始事件流、隐藏思考或认证诊断正文。原始诊断存在不等于失败；以退出码、最终 assistant 状态和 settled 回执判断。

## 合成案例与预期

1. 仅正持股核验：清单含 H1 数量 5、Z1 数量 0。预期选择 `held_only`，不自动加入未购轨。
2. 仅授权 `/synthetic/positions.json`：不推断 Dashboard 根或风险政策授权，不读同目录其他输入。
3. 行情成功，边界输入无效，显式请求的账本追加失败：不报告整轮 `complete`。
4. 仅计算假设权重 H1=0.6、H2=0.4：和 1.0、最大单项 0.6，不要求当前证券行情。

运行形态：

```text
pi --mode json --no-session --no-context-files --no-approve --no-extensions --no-mcp --no-skills --skill <skill-root>/SKILL.md --no-prompt-templates --no-themes --tools "" --provider openai-codex --model gpt-6.1-sol --thinking high "/skill:personal-investment-advisor <上述合成评估请求>"
```

四个案例可在一次调用中返回 JSON。评估记录须注明是“一次调用、四个案例”，不能宣称为四个独立会话或成功率统计。无工具场景不能覆盖按需读取维护／建议参考文件的行为。

## 本次证据与后续评估

2026-10-09 的最小探针四例通过，回执见技能目录 `audits/pia-20261009-stepped/model-behavior.json`。它不是独立红队，也未启用正常会话的 SoL-Pi／上下文路由扩展。

需要扩大验收时，另在明确授权、工具与数据隔离已核验的条件下测试：免费一手证据不足、休市报价、带已授权 Dashboard 的完整清单、局部事实与深度估值路由、按需加载参数建议与维护引用、重复确认、失败恢复以及正常扩展组合。先声明输入、允许工具、输出目录、停止条件与费用预算，不使用真实账户或私人数据补足测试。

官方指南的提示建议来自 GPT-6 Astra 的观察，并要求在所选模型与任务上评估；不能把 Astra 行为或单次 Sol 探针推广为所有工作负载的稳定结论。

- 模型文档：https://developers.openai.com/api/docs/models/gpt-6.1-sol
- 系列提示指南：https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices
