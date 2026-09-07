"""Synthetic periodic payloads shared by auditor and writer acceptance tests.

No production imports: expected outcomes must not be derived from the validator.
The period ends coincide so writer tests can preserve other valid same-day audits.
"""

PERIODS = (
    ("weekly", "week", "2024-W13", "2024-03-31"),
    ("monthly", "month", "2024-03", "2024-03-31"),
    ("quarterly", "quarter", "2024-Q1", "2024-03-31"),
)

SYNTHETIC_BODY = """### 时间范围与证据
- 证据：仅合成夹具，未读取私人来源。

### 能量管理（描述性生理背景）
- **数据范围与来源:** 合成测试，无私人数据采集。
- **组件覆盖与新鲜度:** 无有效观测，未采集。
- **采集审计:** sync_eligible=false; sync_attempted=not_attempted; task_status=not_checked; local_reread=not_run; local_status=not_run; live_fallback=not_used; reason=synthetic_fixture
- **睡眠观察:** 无有效观测，未采集。
- **HRV 与静息心率观察:** 无有效观测，未采集。
- **Body Battery 与压力观察:** 无有效观测，未采集。
- **执行带宽:** not_scored；不从健康指标推断认知或工作表现。
- **睡眠负债:** 来源未提供；sleep_debt_h=null; sleep_debt_status=not_provided_by_source; method=none; baseline_h=null; window_days=null。
- **摩擦解构:** 负荷、主观状态及外部约束均未提供。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 若需补充事实，可列一条待核实事项；完成标准为说明来源。
- **数据缺口与不可判断事项:** 未采集健康数据，不能判断生理状态。
"""


def periodic_payload(label, period_id):
    return f"## [{period_id}] {label.title()} Cognitive Audit\n\n{SYNTHETIC_BODY}"


def topology_cases(label, period_id):
    """Return stable case IDs, complete payloads, and independent pass/fail oracles."""
    valid = periodic_payload(label, period_id)
    heading = valid.splitlines()[0]
    cases = [
        ("valid", valid, True),
        ("valid-leading-blank", "\n\n" + valid, True),
        ("valid-deeper-heading", valid + "\n#### 合成细节\n证据：未采集。\n", True),
        ("wrong-period", valid.replace(f"[{period_id}]", "[2000-01]", 1), False),
        ("wrong-type", valid.replace("Cognitive Audit", "Other Audit", 1), False),
        ("nonheading-first-line", "合成前言\n\n" + valid, False),
        ("duplicate-target", valid + "\n" + heading + "\n", False),
        ("missing-target", SYNTHETIC_BODY, False),
    ]
    for indent in range(4):
        for marker in ("#", "##"):
            cases.append((
                f"extra-atx-h{len(marker)}-indent-{indent}",
                valid + f"\n{' ' * indent}{marker} 非目标区块\n",
                False,
            ))
        for marker, level in (("===", 1), ("---", 2)):
            cases.append((
                f"extra-setext-h{level}-indent-{indent}",
                valid + f"\n非目标区块\n{' ' * indent}{marker}\n",
                False,
            ))
    for indent in range(1, 4):
        cases.append((f"indented-target-{indent}", " " * indent + valid, False))
    return cases
