from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from briefing_gate import validate_briefing_data
from hub_utils import atomic_dump_json
from refine import make_candidate
from run_contract import (
    RunContractError,
    _candidate_lane_summary,
    candidate_object_hash,
    file_sha256,
    validate_registered_pipeline_summary,
)
from semantic_agent import _candidate_assessment, _coverage
from source_kind import classify_source_type
from supplement_agent import FetchResult, verify_bound_candidates
from test_contract_fixtures import cloned_v14_payload
from zero_report import zero_report_data_gaps, zero_report_fields, zero_supply_gap


@pytest.mark.parametrize("url", [
    "https://arxiv.org/abs/2609.04286", "https://arxiv.org/pdf/2609.04286v2.pdf",
    "http://arxiv.org/abs/hep-th/9901001",
])
@pytest.mark.parametrize("claim,expected", [(None, "primary"), ("secondary", "secondary"), ("primary", "primary")])
def test_source_kind_lane_helper_semantic_roundtrip(url, claim, expected):
    item = {"url": url, "title": "Research update", "source": "arXiv", "time": "2026-08-31", "published_at_source": "rss_published"}
    if claim:
        item["source_type"] = claim
    candidate = make_candidate(item, 4, [], "technology", {}, False, {})
    lane_candidate = _candidate_lane_summary(candidate)
    lane = {"window": {"start": "2026-08-29", "end": "2026-08-31"}, "candidates": [lane_candidate], "required_bound_candidate_ids": [candidate["candidate_id"]]}
    with patch("supplement_agent._load_bound_packet", return_value=(Path("request.json"), {}, {}, {"lane": "TechRadar", "max_urls": 4}, lane, {})), patch("supplement_agent._fetch_url", return_value=FetchResult("verified", url, 200, "none", None)), patch("supplement_agent.time.sleep"):
        dynamic = verify_bound_candidates("request.json", "technology", write_draft=False)["draft"]
    enriched = dynamic["candidates"][0]
    assert enriched["source_type"] == expected
    enriched["candidate_object_sha256"] = candidate_object_hash(enriched)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        request = {"bound_artifacts": {}}
        for name, value in {"candidate_pool": {"items": [candidate]}, "supplement": {"results": [dynamic]}, "history_snapshot": {}}.items():
            path = root / f"{name}.json"
            atomic_dump_json(path, value)
            request["bound_artifacts"][name] = {"path": str(path), "sha256": file_sha256(path)}
        with patch("semantic_agent.load_recent_history", return_value=[]):
            eligible, dispositions = _candidate_assessment(request, {"report_date": "2026-08-31", "timezone": "Asia/Shanghai"})
    assert len(eligible) == (1 if expected == "primary" else 0)
    assert dispositions[1]["reason"] == "duplicate_candidate_id"
    assert candidate["candidate_object_sha256"] == candidate_object_hash(candidate)
    if claim:
        assert lane_candidate["source_type"] == claim


@pytest.mark.parametrize("url", [
    "https://arxiv.org", "https://arxiv.org/list/cs.AI/recent", "https://arxiv.org/abs/",
    "https://arxiv.org.evil.test/abs/2609.04286", "https://evil.test/arxiv.org/abs/2609.04286",
    "https://arxiv.org@evil.test/abs/2609.04286", "https://evil.test/?url=https://arxiv.org/abs/2609.04286",
    "https://journal.test/research", "https://export.arxiv.org/abs/2609.04286",
])
def test_source_kind_rejects_portals_and_deceptive_hosts(url):
    assert classify_source_type({"url": url, "source": "Research Journal"}) == "secondary"


def test_zero_report_gate_rejects_every_freeform_field_and_preserves_nonzero():
    nonzero = cloned_v14_payload()
    before = deepcopy(nonzero)
    assert validate_briefing_data(nonzero)[0] == []
    assert nonzero == before
    payload = cloned_v14_payload()
    payload["top_10"] = []
    payload["pipeline"]["semantic_review"].update(verified_access_count=0, reviewed_item_hashes=[], lineage_bindings=[])
    payload["candidate_funnel"] = {"observed": 0, "terminal_dispositions": {"retained": 0}, "quality_gate_reasons": {}, "candidate_dispositions": []}
    payload["mix"]["target_counts"] = {"technology": 0, "healthcare_digital": 0}
    payload["mix"]["actual_counts"] = {"technology": 0, "healthcare_digital": 0}
    payload["mix"]["supply_exception"] = {"applied": False, "reason": "none", "missing_domains": []}
    payload.update(zero_report_fields())
    payload["data_gaps"] = [zero_supply_gap()]
    assert validate_briefing_data(payload)[0] == []
    for field in zero_report_fields():
        forged = deepcopy(payload)
        forged[field] = [{"task": "market is silent; buy now"}] if field == "action_levers" else "No innovations; market is silent"
        assert any(f"zero-report {field}" in error for error in validate_briefing_data(forged)[0])


def test_zero_report_gaps_bound_to_registered_success_and_failure_evidence():
    for failed in (0, 1):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            supplement = {"coverage": {"attempted": 1, "succeeded": 1 - failed, "failed": failed}, "results": [{"gap_id": "actual-lane", "lane": "TechRadar", "status": "degraded" if failed else "no_increment", "coverage": {"failed": failed}, "candidates": []}]}
            baseline = {"source_attempted": 1, "source_succeeded": 1, "source_failed": 0, "raw_candidates": 0, "dated_candidates": 0, "reasons": ["registered date gap"] if failed else []}
            pool = {"items": [], "candidate_funnel": {"observed": 0, "retained_for_review": 0, "terminal_dispositions": {"retained_for_review": 0}}}
            for name, value in {"supplement": supplement, "pool": pool}.items():
                atomic_dump_json(root / f"{name}.json", value)
            manifest = {"stages": {"baseline": {"status": "completed", "metadata": {"coverage": baseline}}, "supplemental": {"status": "degraded" if failed else "completed", "artifact_path": str(root / "supplement.json"), "artifact_sha256": file_sha256(root / "supplement.json")}}, "artifacts": {"candidate_pool": {"artifact_path": str(root / "pool.json"), "artifact_sha256": file_sha256(root / "pool.json")}}}
            core = {"schema_version": "1.4", "top_10": [], "mix": {}, "coverage": _coverage(manifest, supplement), "candidate_funnel": {"observed": 0, "terminal_dispositions": {"retained": 0}}}
            core["data_gaps"] = zero_report_data_gaps(supplement, {}, baseline)
            validate_registered_pipeline_summary(core, manifest)
            assert len(core["data_gaps"]) == (3 if failed else 1)
            for gaps in ([], core["data_gaps"] + [{"description": "all sources failed"}], [{**gap, "description": "no innovation"} for gap in core["data_gaps"]]):
                with pytest.raises(RunContractError, match="data_gaps.*registered evidence"):
                    validate_registered_pipeline_summary({**core, "data_gaps": gaps}, manifest)
