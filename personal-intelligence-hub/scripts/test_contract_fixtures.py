from copy import deepcopy

from history_manager import generate_event_id
from run_contract import candidate_ref, item_hash


def valid_v12_payload():
    item = {
        "event_id": generate_event_id(
            {
                "primary_domain": "healthcare_digital",
                "actor": "Example Hospital",
                "action": "published",
                "object": "clinical AI evaluation",
                "event_date": "2026-08-09",
                "key_version": "1",
            }
        ),
        "event_identity": {
            "primary_domain": "healthcare_digital",
            "actor": "Example Hospital",
            "action": "published",
            "object": "clinical AI evaluation",
            "event_date": "2026-08-09",
            "key_version": "1",
        },
        "identity_quality": "semantic",
        "title": "Clinical AI evaluation published",
        "title_zh": "临床 AI 评估发布",
        "url": "https://example.org/source",
        "candidate_refs": [candidate_ref("https://example.org/source")],
        "source": "Example Hospital",
        "source_type": "primary",
        "access_check": {
            "status": "verified",
            "checked_at": "2026-08-10T09:00:00+08:00",
            "method": "http_get",
            "requested_url": "https://example.org/source",
            "final_url": "https://example.org/source",
            "http_status": 200,
        },
        "event_date": "2026-08-09",
        "event_date_source": "source_explicit",
        "published_at": "2026-08-09",
        "published_at_source": "page_metadata",
        "observed_at": "2026-08-10T09:00:00+08:00",
        "retrieved_at": "2026-08-10T09:00:00+08:00",
        "primary_domain": "healthcare_digital",
        "secondary_domains": [],
        "major_signal": False,
        "major_signal_reason": "none",
        "near_term_decision_impact": False,
        "decision_impact_reason": "none",
        "fact": "医院发布了一项临床 AI 评估。",
        "connection": "该评估与临床部署证据相关。",
        "deduction": "现有证据只支持继续观察。",
        "actionability": "跟踪后续独立复核。",
        "intelligence_level": "L2",
        "confidence": "medium",
        "corroboration_status": "single_primary",
        "summary_zh": "该机构发布了临床 AI 评估结果。",
    }
    reviewed_hash = item_hash(item)
    return {
        "schema_version": "1.2",
        "run_id": "run-contract-001",
        "report_date": "2026-08-10",
        "generated_at": "2026-08-10T09:00:00+08:00",
        "model_used": "semantic_model",
        "topic": "技术与医疗数字化",
        "region": "中国、美国与全球",
        "window": {
            "mode": "calendar_days",
            "days": 7,
            "start": "2026-08-04",
            "end": "2026-08-10",
            "timezone": "Asia/Shanghai",
        },
        "punchline": "当前窗口只有一条经过核验但仍需复核的信号。",
        "insights": "证据不足以支持扩大部署。",
        "digest": "继续观察独立复核。",
        "market": "暂无足够市场变化证据。",
        "action_levers": [],
        "pipeline": {
            "baseline_sha256": "a" * 64,
            "supplement_status": "completed",
            "semantic_review": {
                "status": "passed",
                "reviewer_kind": "semantic_model",
                "reviewer_id": "SemanticEvaluator",
                "invocation_id": "semantic-fixture-invocation",
                "request_sha256": "c" * 64,
                "input_bundle_sha256": "d" * 64,
                "access_log_sha256": "1" * 64,
                "verified_access_count": 1,
                "output_sha256": "b" * 64,
                "reviewed_item_hashes": [reviewed_hash],
                "lineage_bindings": [
                    {
                        "output_item_sha256": reviewed_hash,
                        "inputs": [
                            {
                                "candidate_ref": item["candidate_refs"][0],
                                "candidate_object_sha256": "e" * 64,
                            }
                        ],
                    }
                ],
                "turns_used": 1,
                "halt_condition_met": True,
            },
            "red_team": {
                "status": "not_required",
                "reviewer_kind": "logic_adversary",
                "reviewer_id": "RedTeam",
                "invocation_id": "red-fixture-invocation",
                "request_sha256": "f" * 64,
                "turns_used": 1,
                "halt_condition_met": True,
                "covered_item_hashes": [],
            },
        },
        "coverage": {
            "run_status": "degraded",
            "coverage_confidence": "medium",
            "baseline_status": "degraded",
            "source_attempted": 10,
            "source_succeeded": 8,
            "source_failed": 2,
            "source_success_rate": 0.8,
            "dated_candidate_rate": 0.9,
            "required_lane_failures": [],
            "reasons": [],
        },
        "candidate_funnel": {
            "observed": 3,
            "terminal_dispositions": {
                "retained": 1,
                "below_quality_gate": 2,
            },
        },
        "mix": {
            "default_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "requested_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "ratio_source": "schema_default",
            "ratio_reason": "none",
            "effective_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "target_counts": {"technology": 0, "healthcare_digital": 1},
            "actual_counts": {"technology": 0, "healthcare_digital": 1},
            "adjustment": {
                "applied": False,
                "favored_domain": "none",
                "reason": "none",
                "trigger_urls": [],
            },
            "supply_exception": {
                "applied": False,
                "reason": "none",
                "missing_domains": [],
            },
        },
        "top_10": [item],
        "data_gaps": [
            {
                "gap_id": "second-source",
                "lane": "HealthcareRadar",
                "status": "open",
                "description": "尚无第二独立来源。",
                "impact": "主张置信度不等于覆盖充分。",
            }
        ],
    }


def cloned_v12_payload():
    return deepcopy(valid_v12_payload())


def valid_v13_payload():
    payload = valid_v12_payload()
    payload["schema_version"] = "1.3"
    payload["mix"] = {
        "default_ratio": {"technology": 0.6, "healthcare_digital": 0.4},
        "requested_ratio": {"technology": 0.6, "healthcare_digital": 0.4},
        "ratio_source": "schema_default",
        "ratio_reason": "none",
        "effective_ratio": {"technology": 0.6, "healthcare_digital": 0.4},
        "target_counts": {"technology": 1, "healthcare_digital": 0},
        "actual_counts": {"technology": 0, "healthcare_digital": 1},
        "adjustment": {
            "applied": False,
            "favored_domain": "none",
            "reason": "none",
            "trigger_urls": [],
        },
        "supply_exception": {
            "applied": True,
            "reason": "合格候选不足：technology",
            "missing_domains": ["technology"],
        },
    }
    return payload


def cloned_v13_payload():
    return deepcopy(valid_v13_payload())


def valid_v14_payload():
    payload = valid_v13_payload()
    payload["schema_version"] = "1.4"
    return payload


def cloned_v14_payload():
    return deepcopy(valid_v14_payload())
