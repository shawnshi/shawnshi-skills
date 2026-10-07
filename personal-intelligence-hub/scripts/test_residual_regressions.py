"""Cross-surface regressions. Synthetic evidence, never production or independent approval."""
from copy import deepcopy

import pytest
from briefing_gate import _validate_claim_grounding
from mix_policy import major_signal_eligible
from forge import render_briefing
from run_contract import RunContractError, review_scope
from test_contract_fixtures import cloned_v14_payload


def assembled_case(grounding=True):
    # Keep the fixture class local: pytest's unittest plugin collects imported
    # TestCase classes even under an underscore alias, inflating suite counts.
    from test_semantic_agent import SemanticAgentFinalizeTests
    fixture = SemanticAgentFinalizeTests()
    candidate, identity = fixture._dated_candidate()
    item = {
        "candidate_id": candidate["candidate_id"], "event_identity": identity,
        "title_zh": "核验测试通告", "fact": "厂商发布了 3 项隔离修复。",
        "connection": "与沙箱隔离边界相关。", "deduction": "部署前核对修复范围。",
        "actionability": "由平台团队核对修复版本。", "intelligence_level": "L3",
        "confidence": "high", "summary_zh": "发布隔离修复。", "major_signal": True,
        "major_signal_reason": "改变近期部署条件", "near_term_decision_impact": True,
        "decision_impact_reason": "近期部署前需要核验",
    }
    if grounding:
        item["claim_grounding"] = {
            "basis": "synthetic source fixture, not a real-world finding",
            "claims": [{"kind": "number", "statement": "发布了 3 项修复",
                        "status": "grounded", "value": "3", "evidence": candidate["url"]}],
        }
    core = fixture._assemble(candidate, identity, dynamic_overrides={"selected_items": [item]})
    return core, item


def test_producer_grounding_survives_gate_scope_and_render():
    core, dynamic = assembled_case()
    item = core["top_10"][0]
    assert item["claim_grounding"] == dynamic["claim_grounding"]
    assert item["intelligence_level"] == "L3"
    assert item["major_signal"] is True
    assert major_signal_eligible(item)
    assert review_scope(core)["review_mode"] == "targeted_review"
    errors, warnings = [], []
    _validate_claim_grounding([item], errors, warnings, True)
    assert not errors and not warnings
    # Render checks are separate from publication/reviewer approval.
    payload = cloned_v14_payload()
    payload["top_10"] = [item]
    assert item["title_zh"] in render_briefing(payload)
    dynamic["claim_grounding"]["basis"] = "mutated input"
    assert item["claim_grounding"]["basis"] != "mutated input"


def test_legacy_no_ledger_is_not_forcibly_downgraded():
    core, _ = assembled_case(False)
    item = core["top_10"][0]
    assert item["intelligence_level"] == "L3"
    assert "claim_grounding" not in item
    errors, warnings = [], []
    _validate_claim_grounding([item], errors, warnings, True)
    assert not errors and warnings
    assert review_scope(core)["review_mode"] == "targeted_review"


@pytest.mark.parametrize("ledger", [
    {"basis": "source", "claims": []},
    {"basis": "source", "claims": [{"kind": "number", "statement": "3", "status": "grounded", "value": "99", "evidence": "source"}]},
])
def test_malformed_ledgers_never_reach_finalization(ledger):
    from semantic_agent import _validate_claim_grounding as producer_validate
    with pytest.raises(RunContractError):
        producer_validate({"claim_grounding": deepcopy(ledger)}, "3 项修复", 0)
