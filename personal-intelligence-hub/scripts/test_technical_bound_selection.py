"""Portable NEW-v3 TechRadar selection, without network or private fixtures."""

import json
from copy import deepcopy
from itertools import permutations
from pathlib import Path
from unittest.mock import patch

import pytest
import run_contract as rc
from supplement_agent import build_agent_context
from test_run_daily_broker_entry import prepare_fixture

FOCUS = json.loads(
    (
        Path(__file__).resolve().parents[1] / "references" / "strategic_focus.json"
    ).read_text(encoding="utf-8")
)
GAP = {"lane": "TechRadar", "max_urls": 4, "verify_bound_candidates": True}


def item(title, path="article", **fields):
    return {
        "title": title,
        "url": "https://example.org/" + path,
        "provisional_domain": "technology",
        **fields,
    }


def select(items, version=3, lane="TechRadar"):
    return rc.select_supplement_bound_candidates(
        {"items": items}, {**GAP, "lane": lane}, FOCUS, article_broker_version=version
    )


@pytest.mark.parametrize(
    "lead,reason",
    [
        (
            item("A quotation", source="Hacker News", heuristic_rank=999),
            "no_technical_text",
        ),
        (item("All grown-ups were once children"), "no_technical_text"),
        (
            item("Octopus", url="https://en.wikipedia.org/wiki/Octopus"),
            "non_article_url",
        ),
        (item("What is a compiler?"), "explanation_or_access_page"),
        (item("WebAssembly explained"), "explanation_or_access_page"),
        (item("AI release", ""), "homepage"),
        (item("AI release", "search?q=compiler"), "non_article_url"),
        (item("AI release", "login"), "non_article_url"),
        (
            item("AI release", description="Verify you are human"),
            "challenge_or_login_content",
        ),
        (item("Chair repair and unfair claims"), "no_technical_text"),
        (
            item("Hospital payment release", primary_domain="healthcare_digital"),
            "no_technical_text",
        ),
    ],
)
def test_irrelevant_or_nonarticle_never_binds(lead, reason):
    assert rc._technical_lead_evidence(lead, FOCUS)[0] == reason
    assert select([lead]) == ([], [])


@pytest.mark.parametrize(
    "title",
    [
        "WebAssembly in Anubis",
        "JIT compiler release",
        "Support Local Variables",
        "Microsoft Plugs Nearly 1,000 Security Holes",
        "Security patches",
        "CVE-2026-1234",
        "AI release",
        "Kubernetes release",
        "DeepSeek v4.1 Flash",
    ],
)
def test_genuine_technical_terms_retained(title):
    assert len(select([item(title)])[1]) == 1


def test_retained_description_not_generated_hints_or_assurances():
    good = item("New release", summary_hint="JIT compiler now supports local variables")
    bad = item("An unrelated quotation", "bad")
    _, expected = select([good, bad])
    forged = deepcopy([good, bad])
    for lead in forged:
        lead.update(
            source="Hacker News",
            source_type="primary",
            heuristic_rank=999,
            keyword_connection_hint="AI compiler CVE",
            primary_domain="healthcare_digital",
            access_check={
                "status": "blocked",
                "requested_url": lead["url"],
                "http_status": 403,
            },
        )
    assert select(forged)[1] == expected
    assert select([bad])[1] == []


def test_stable_unique_two_bound_and_medical_not_promoted():
    leads = [
        item("AI release", "z"),
        item("AI release", "a"),
        item(
            "AI release",
            "m",
            primary_domain="healthcare_digital",
            provisional_secondary_domains=["healthcare_digital"],
        ),
    ]
    expected = select(leads)[1]
    assert expected == [
        rc.candidate_ref(leads[1]["url"]),
        rc.candidate_ref(leads[2]["url"]),
    ]
    for ordered in permutations(leads):
        assert select(list(ordered))[1] == expected
    candidates, required = select([leads[0], leads[0], leads[1]])
    assert len(candidates) == len(required) == 2
    assert GAP["max_urls"] - len(required) == 2
    assert select([]) == ([], [])


def test_v2_four_bound_and_other_lanes_unchanged():
    leads = [
        item(
            "Hospital policy risk",
            str(i),
            secondary_domains=["healthcare_digital"],
            lane="Ranger",
        )
        for i in range(5)
    ]
    assert len(select(leads, version=2)[1]) == 4
    for lane in ["HealthcareRadar", "Sentinel", "Ranger"]:
        assert select(leads, version=2, lane=lane) == select(
            leads, version=3, lane=lane
        )


def test_registered_two_bound_context_and_frozen_finalization(tmp_path):
    result = prepare_fixture(tmp_path, 5)
    assert result.supplement_request_path is not None
    request = json.loads(result.supplement_request_path.read_text(encoding="utf-8"))
    packet = request["execution_packets"][0]
    lane = json.loads(Path(packet["lane_slice"]["path"]).read_text(encoding="utf-8"))
    required = lane["required_bound_candidate_ids"]
    assert len(required) == 2
    with patch.object(
        rc,
        "select_supplement_bound_candidates",
        side_effect=AssertionError("must not rerank"),
    ):
        context = build_agent_context(
            result.supplement_request_path, "technology-supply", candidate_limit=1
        )
        assert [c["candidate_ref"] for c in context["bound_candidates"]] == required
        pool = json.loads(result.candidates_path.read_text(encoding="utf-8"))
        results = []
        for gap, p in zip(request["gaps"], request["execution_packets"], strict=True):
            frozen = json.loads(
                Path(p["lane_slice"]["path"]).read_text(encoding="utf-8")
            )
            results.append(
                {
                    "gap_id": gap["gap_id"],
                    "run_id": request["run_id"],
                    "request_sha256": rc.file_sha256(result.supplement_request_path),
                    "access_log": [],
                    "candidates": [],
                    "failure_kind": "infrastructure",
                    "bound_candidate_decisions": [
                        {
                            "candidate_id": ref,
                            "decision": "infrastructure_unavailable",
                            "reason": "offline fixture",
                        }
                        for ref in frozen["required_bound_candidate_ids"]
                    ],
                }
            )
        rc.build_candidate_date_evidence(
            request, rc.file_sha256(result.supplement_request_path), pool, results
        )
        results[0]["bound_candidate_decisions"].pop()
        with pytest.raises(rc.RunContractError, match="exactly once"):
            rc.build_candidate_date_evidence(
                request, rc.file_sha256(result.supplement_request_path), pool, results
            )
    assert context["execution_budget"] == {
        "max_queries": 2,
        "max_urls": 4,
        "max_duration_seconds": 600,
    }
