#!/usr/bin/env python3
"""Measure the observed interval after Skill reading; never claim end-to-end coverage."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.dont_write_bytecode = True
from research_plan import RunMetrics, atomic_write_json

EXCLUSIONS = ["before_start_including_skill_read", "final_response", "human_review_wait_after_finish"]
SEMANTICS = {
    "elapsed_ms": "Wall-clock interval since start; no automatic pause or full-task instrumentation. Finish before human review waiting; any wait before finish remains included.",
    "sources_opened": "Business original-source read requests only; count failed requests and rereads; exclude hash-byte reads and rule/Skill reads.",
    "queries_executed": "Query items submitted, including failed queries; a batch counts by items.",
    "other_counters": "Explicit observed nonnegative increments only; unobserved default zero is not measured zero.",
    "tokens": "Only provider-observed usage within the measured interval; unknown remains null.",
    "events": "Explicit request counts, not automatic tool interception; do not double-count an event through --count.",
}
EVENTS = ("business_source_open", "hash_bytes_read", "rule_read")

def now():
    return datetime.now(timezone.utc)

def increment_spec(item, allowed):
    key, amount = item.split("=", 1)
    amount = int(amount)
    if key not in allowed or amount < 0:
        raise ValueError("未知计数器/事件或负增量。")
    return key, amount

def enrich(value):
    # Older logs do not establish whether Skill reading preceded their start.
    value.setdefault("measurement_scope", "legacy_recorded_start_to_validation_or_safe_stop")
    value.setdefault("coverage_exclusions", ["before_recorded_start"])
    value.setdefault("counter_semantics", {
        key: "Unknown legacy counting/coverage semantics; historical values are preserved without asserting the current counting rules. Default event zeros are unmeasured, not evidence of zero historical requests."
        for key in SEMANTICS
    })
    value.setdefault("event_counts", dict.fromkeys(EVENTS, 0))
    value.setdefault("observed_counters", [])
    for key in ("input_tokens", "output_tokens"):
        if key not in value["observed_counters"]:
            value["counters"][key] = None
    return value

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=["start", "record", "finish", "attach"])
    p.add_argument("file", type=Path)
    p.add_argument("--count", action="append", default=[])
    p.add_argument("--event", action="append", default=[], help="business_source_open|hash_bytes_read|rule_read=N")
    p.add_argument("--reason", choices=["validation_complete", "safe_stop"], default="validation_complete")
    p.add_argument("--candidate", type=Path)
    a = p.parse_args()
    try:
        if (a.count or a.event) and a.operation != "record":
            raise ValueError("计数仅适用于record。")
        if a.file.is_symlink():
            raise ValueError("拒绝符号链接。")
        if a.operation == "start":
            if a.file.exists():
                raise ValueError("记录已存在，不覆盖首次起点。")
            value = {"schema": "discovery-call-session-timing/v1", "started_at": now().isoformat(),
                     "ended_at": None, "observed_counters": [],
                     "measurement_scope": "post_skill_read_to_validation_or_safe_stop",
                     "coverage_exclusions": list(EXCLUSIONS),
                     "counter_semantics": dict(SEMANTICS),
                     "counters": dict.fromkeys(RunMetrics.COUNTERS, 0)}
        else:
            value = json.loads(a.file.read_text(encoding="utf-8"))
        if value.get("schema") != "discovery-call-session-timing/v1":
            raise ValueError("错误的计量记录。")
        enrich(value)
        if a.operation == "record":
            if value.get("ended_at"):
                raise ValueError("已结束记录不可追加。")
            counts = [increment_spec(item, RunMetrics.COUNTERS) for item in a.count]
            events = [increment_spec(item, EVENTS) for item in a.event]
            if any(k == "sources_opened" for k, _ in counts) and any(k == "business_source_open" for k, _ in events):
                raise ValueError("业务原文请求不能在同一次record中重复计数。")
            for key, amount in events:
                value["event_counts"][key] += amount
                if key == "business_source_open":
                    counts.append(("sources_opened", amount))
            for key, amount in counts:
                value["counters"][key] = (value["counters"][key] or 0) + amount
                value["observed_counters"] = sorted(set(value["observed_counters"]) | {key})
        if a.operation == "finish" and not value.get("ended_at"):
            value["ended_at"] = now().isoformat()
            value["finish_reason"] = a.reason
        if a.operation == "attach":
            if value.get("ended_at"):
                raise ValueError("attach须在finish前生成提交前快照。")
            if not a.candidate:
                raise ValueError("attach需要--candidate。")
            if a.candidate.absolute() != a.candidate.resolve() or (a.candidate / "runtime").is_symlink():
                raise ValueError("候选路径不得含链接。")
            base = json.loads((a.candidate / "runtime/candidate-base.json").read_text(encoding="utf-8"))
            if a.candidate.resolve() == Path(base["workspace"]).resolve():
                raise ValueError("计量快照只能写隔离候选。")
            if (a.candidate / "runtime/manifest.json").is_symlink():
                raise ValueError("拒绝清单链接。")
            m = json.loads((a.candidate / "runtime/manifest.json").read_text(encoding="utf-8"))
            started = datetime.fromisoformat(value["started_at"])
            ended = now()
            metric = RunMetrics(a.candidate / "runtime/run-metrics.json", m["context_id"], m["latest_run_id"], m["business_mode"], started)
            snapshot = metric.initial()
            snapshot.update({k: value[k] for k in ("counters", "coverage_exclusions", "counter_semantics", "event_counts")})
            snapshot["coverage_exclusions"] = list(value["coverage_exclusions"]) + ["commit_and_post_snapshot_work"]
            prefix = "post_skill_read" if value["measurement_scope"].startswith("post_skill_read_") else "legacy_recorded_start"
            snapshot["measurement_scope"] = prefix + "_to_precommit_snapshot"
            snapshot["unmeasured_counters"] = sorted(set(RunMetrics.COUNTERS) - set(value["observed_counters"]))
            snapshot["ended_at"] = ended.isoformat()
            snapshot["elapsed_ms"] = max(0, int((ended - started).total_seconds() * 1000))
            metric.save(snapshot)
            print(json.dumps({"measurement_scope": snapshot["measurement_scope"], "snapshot": str(metric.path)}, ensure_ascii=False))
            return 0
        if value.get("ended_at"):
            value["elapsed_ms"] = max(0, int((datetime.fromisoformat(value["ended_at"]) - datetime.fromisoformat(value["started_at"])).total_seconds() * 1000))
        atomic_write_json(a.file, value)
        print(json.dumps(value, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        print("ERROR: " + str(e), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
