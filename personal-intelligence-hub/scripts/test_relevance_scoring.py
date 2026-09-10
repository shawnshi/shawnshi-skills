"""Content relevance/source separation and shared configured concept regression."""

import json
from copy import deepcopy
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

import pytest
import refine
import run_contract as rc
from relevance import content_relevance, keyword_matches

FOCUS = json.loads(
    (Path(__file__).resolve().parents[1] / "references/strategic_focus.json").read_text(
        encoding="utf-8"
    )
)


def item(title, source="Hacker News", **fields):
    return {
        "title": title,
        "raw_desc": "",
        "url": "https://example.org/" + title.replace(" ", "-"),
        "source": source,
        **fields,
    }


def pool(items, **kwargs):
    return refine.heuristics({"items": items}, FOCUS, **kwargs)


def test_source_only_cannot_admit_or_choose_medical_domain():
    assert pool([item("An unrelated quotation")])["items"] == []
    candidate = pool([item("hospital procurement")])["items"][0]
    assert candidate["provisional_domain"] == "healthcare_digital"
    assert candidate["domain_scores"] == {"technology": 0, "healthcare_digital": 5}
    assert candidate["heuristic_rank"] == 5
    assert candidate["source_preference"] == 0
    explicit = item("hospital procurement", primary_domain="technology")
    assert refine.score_item(explicit, FOCUS)[2] == "technology"
    assert pool([explicit])["items"] == []


@pytest.mark.parametrize(
    "text,score",
    [
        ("DeepSeek v4.1 Flash", 4),
        ("Windows Security Holes CVE-2026-1234 vulnerability vulnerabilities", 5),
        ("compiler compilers compiler", 5),
        ("security patch security patches", 4),
        ("AI artificial intelligence 人工智能", 4),
        ("WebAssembly wasm", 4),
    ],
)
def test_aliases_once_and_genuine_leads(text, score):
    assert refine.score_item(item(text), FOCUS)[0] == score
    assert len(pool([item(text)])["items"]) == 1
    assert rc._technical_lead_evidence(item(text), FOCUS)[0] == "technical_text"


def test_ascii_boundaries_chinese_and_shared_matcher():
    assert not keyword_matches("chair unfair ragtime compilersx", "AI")
    assert not keyword_matches("compilersx", "compilers")
    assert keyword_matches("采用人工智能技术", "人工智能")
    for text in ["JIT compiler", "AI agents", "网络安全", "DeepSeek", "chair repair"]:
        score, _ = content_relevance(text, FOCUS["domains"]["technology"])
        assert refine.score_item(item(text), FOCUS)[3]["technology"] == score
        reason, rank = rc._technical_lead_evidence(item(text), FOCUS)
        assert (reason == "technical_text") == (score > 0)
        if score:
            assert rank[2] == -score


def test_order_threshold_cap_and_funnel():
    leads = [
        item("compiler", "Other"),
        item("compilers"),
        item("DeepSeek"),
        item("quotation"),
    ]
    expected = [c["title"] for c in pool(leads)["items"]]
    assert expected == ["compilers", "compiler", "DeepSeek"]
    for ordered in permutations(leads):
        result = pool(list(ordered), max_items_override=2)
        assert [c["title"] for c in result["items"]] == expected[:2]
        assert sum(result["candidate_funnel"]["terminal_dispositions"].values()) == 4
    assert pool(leads, min_score_override=6)["items"] == []
    assert len(pool(leads, min_score_override=0)["items"]) == 4
    assert pool(leads)["metadata"]["scoring"]["version"] == "content-relevance/2.0"


def test_generated_hints_never_qualify_or_outrank_content():
    bad = item(
        "quotation",
        heuristic_rank=999,
        source_preference=999,
        keyword_connection_hint="AI compiler",
        access_check={"status": "ok"},
    )
    focus = deepcopy(FOCUS)
    focus.setdefault("coverage_policy", {}).setdefault("lanes", {})["TechRadar"] = {
        "keywords": ["quotation"]
    }
    assert rc._technical_lead_evidence(bad, focus)[0] == "no_technical_text"
    stronger = item("compiler", "Other")
    weaker = item("DeepSeek")
    assert (
        rc._technical_lead_evidence(stronger, FOCUS)[1]
        < rc._technical_lead_evidence(weaker, FOCUS)[1]
    )


def test_summary_projection_does_not_claim_full_description_coverage():
    lead = item("new finding", raw_desc="x" * 230 + " compiler")
    candidate = pool([lead])["items"][0]
    assert candidate["heuristic_rank"] == 5
    assert len(candidate["summary_hint"]) == 220
    assert rc._technical_lead_evidence(candidate, FOCUS)[0] == "no_technical_text"


def test_new_scoring_prepare_to_frozen_request(tmp_path):
    from supplement_agent import build_agent_context
    from test_run_daily_broker_entry import prepare_fixture, scan_fixture

    original_scan = scan_fixture(4)

    async def scan(**kwargs):
        payload = await original_scan(**kwargs)
        for lead, title in zip(
            payload["items"],
            [
                "DeepSeek release",
                "Windows Security Holes",
                "compiler release",
                "An unrelated quotation",
            ],
            strict=True,
        ):
            lead.update(title=title, raw_desc="", source="Hacker News")
        for name in ("output_path", "current_output_path"):
            kwargs[name].write_text(json.dumps(payload), encoding="utf-8")
        return payload

    with patch("test_run_daily_broker_entry.scan_fixture", return_value=scan):
        result = prepare_fixture(tmp_path, 4, focus_config=FOCUS)
    candidates = json.loads(result.candidates_path.read_text(encoding="utf-8"))
    assert len(candidates["items"]) == 3
    assert (
        candidates["candidate_funnel"]["rejected_by_reason"][
            "below_heuristic_threshold"
        ]
        == 1
    )
    assert result.supplement_request_path is not None
    request = json.loads(result.supplement_request_path.read_text(encoding="utf-8"))
    packet = request["execution_packets"][0]
    frozen = json.loads(Path(packet["lane_slice"]["path"]).read_text(encoding="utf-8"))
    required = frozen["required_bound_candidate_ids"]
    assert len(required) == 2
    with patch.object(
        rc,
        "select_supplement_bound_candidates",
        side_effect=AssertionError("must consume frozen IDs"),
    ):
        context = build_agent_context(
            result.supplement_request_path, "technology-supply", candidate_limit=1
        )
    assert [c["candidate_ref"] for c in context["bound_candidates"]] == required
    assert packet["execution_budget"] == {
        "max_queries": 2,
        "max_urls": 4,
        "max_duration_seconds": 600,
    }
    assert packet["finalization"]["grace_seconds"] == 300
    assert packet["usage_budget"] == {"tokens": 150000, "cost_usd": 0.5}
