"""Production prepare entry: fake only the source-scan boundary, real refinement/packets."""
import asyncio
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import run_daily
from run_contract import RunContractError, load_manifest, record_run_artifact


def scan_fixture(count):
    async def scan_all(**kwargs):
        payload = {
            "items": [{"title": f"technology release {index}",
                       "url": f"https://example.org/entry-{index}", "source": "Fixture",
                       "time": "2026-09-08", "published_at_source": "rss",
                       "raw_desc": "technology", "source_type": "primary"}
                      for index in range(count)],
            "coverage": {"run_status": "degraded", "source_success_rate": 0.5},
            "metadata": {"window": {"mode": "calendar_days", "days": 3,
                "start": "2026-09-06", "end": "2026-09-08", "timezone": "Asia/Shanghai"}},
        }
        for name in ("output_path", "current_output_path"):
            kwargs[name].write_text(json.dumps(payload), encoding="utf-8")
        return payload
    return scan_all


def prepare_fixture(root, count, version=None, *, runtime=None, run_id="entry"):
    focus = root / "focus.json"
    focus.write_text(json.dumps({
        "filters": {"max_top10": 10, "min_score_for_top10": 0},
        "domains": {"technology": {"keywords": [{"keyword": "technology", "weight": 5}]}},
    }), encoding="utf-8")
    kwargs = {} if version is None else {"article_broker_version": version}
    with patch("fetch_news.scan_all", side_effect=scan_fixture(count)):
        return asyncio.run(run_daily.prepare_run(
            report_date="2026-09-08", focus_path=focus,
            runtime_dir=runtime or root / "rt", news_dir=root / "news",
            run_id=run_id, now=datetime(2026, 9, 8, 22, tzinfo=ZoneInfo("Asia/Shanghai")),
            **kwargs,
        ))


@pytest.mark.parametrize("count", [0, 3, 4, 5])
@pytest.mark.parametrize("version", [None, 2])
def test_prepare_broker_version_real_registered_packets(tmp_path, count, version):
    result = prepare_fixture(tmp_path, count, version)
    manifest = load_manifest(result.manifest_path)
    assert result.supplement_request_path is not None
    request = json.loads(result.supplement_request_path.read_text(encoding="utf-8"))
    pool = json.loads(result.candidates_path.read_text(encoding="utf-8"))
    assert len(pool["items"]) == count
    assert len(request["gaps"]) == 4
    assert request.get("article_broker_version") == version
    assert all(worker["timeout_ms"] == 450_000 for wave in request["launch_plan"] for worker in wave["workers"])
    metadata = manifest["artifacts"]["focus_config"]["metadata"]
    assert metadata.get("article_broker_version") == version
    assert result.execution_cli_path.is_file()
    for gap, packet in zip(request["gaps"], request["execution_packets"], strict=True):
        lane_slice = json.loads(Path(packet["lane_slice"]["path"]).read_text(encoding="utf-8"))
        bound = lane_slice["required_bound_candidate_ids"]
        expected_bound = min(count, 4) if gap["lane"] == "TechRadar" else 0
        assert len(bound) == expected_bound
        assert gap["max_urls"] == 4
        assert gap["max_queries"] == 2
        assert packet["tool_budget"]["hard"] == 12
        assert bool(gap.get("article_broker")) == (version == 2 and expected_bound < 4)
        assert ("article_broker" in packet) == bool(gap.get("article_broker"))
    # Registered metadata cannot be changed by a second registration.
    record_run_artifact(result.manifest_path, "focus_config", tmp_path / "focus.json",
                        metadata={"article_broker_version": 1 if version == 2 else 2})
    assert load_manifest(result.manifest_path)["artifacts"]["focus_config"]["metadata"] == metadata


@pytest.mark.parametrize("version", [0, 3, True, "2"])
def test_prepare_rejects_unsupported_broker_version_before_writes(tmp_path, version):
    with pytest.raises(RunContractError, match="article_broker_version"):
        asyncio.run(run_daily.prepare_run(runtime_dir=tmp_path / "rt", article_broker_version=version))
    assert not (tmp_path / "rt").exists()


def test_prepare_cli_rejects_unsupported_broker_version():
    with patch.object(sys, "argv", ["run_daily.py", "prepare", "--article-broker-version", "3"]), pytest.raises(SystemExit) as caught:
        run_daily.main()
    assert caught.value.code == 2


def test_prepare_cli_forwards_explicit_broker_version(tmp_path):
    result = run_daily.PrepareResult(*(tmp_path / name for name in ["manifest", "baseline", "candidates", "request", "cli"]))
    with patch.object(sys, "argv", ["run_daily.py", "prepare", "--article-broker-version", "2"]), \
         patch("run_daily.prepare_run", return_value=result) as prepare, redirect_stdout(io.StringIO()):
        run_daily.main()
    assert prepare.call_args.kwargs["article_broker_version"] == 2


def test_expansion_preserves_optin_with_real_gate_and_rejects_tampered_funnel():
    import unittest

    from expansion_test_fixture import registered_selection
    from run_contract import build_review_request

    def bind_optin_before_review(manifest, *args, **kwargs):
        focus = manifest.parent / "entry-focus.json"
        focus.write_text("{}", encoding="utf-8")
        record_run_artifact(manifest, "focus_config", focus, metadata={"article_broker_version": 2})
        return build_review_request(manifest, *args, **kwargs)

    case = unittest.TestCase()
    try:
        with patch("expansion_test_fixture.build_review_request", side_effect=bind_optin_before_review):
            manifest, refined, receipt = registered_selection(case, 1)
        argv = ["run_daily.py", "check-expansion", "--manifest", str(manifest),
                "--refined", str(refined), "--semantic-receipt", str(receipt)]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(output):
            run_daily.main()
        decision = json.loads(output.getvalue())
        assert decision["action"] == "expand"
        args = decision["next_argv"]
        assert args[args.index("--article-broker-version") + 1] == "2"
        assert args[args.index("--window-days") + 1] == "7"
        core = json.loads(refined.read_text(encoding="utf-8"))
        core["candidate_funnel"]["observed"] += 1
        refined.write_text(json.dumps(core), encoding="utf-8")
        output = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(output), pytest.raises(SystemExit):
            run_daily.main()
        assert json.loads(output.getvalue())["action"] == "reject"
    finally:
        case.doCleanups()


def test_secondary_medical_hints_and_stable_prebound_order():
    from run_contract import _lane_slice_candidates

    items = [
        {"url": "https://example.org/opinion", "title": "An opinion essay", "provisional_domain": "technology"},
        {"url": "https://example.org/z", "title": "Release", "provisional_domain": "technology"},
        {"url": "https://example.org/a", "title": "Release", "provisional_domain": "technology"},
        {"url": "https://example.org/medical", "title": "New platform", "provisional_domain": "technology",
         "provisional_secondary_domains": ["healthcare_digital"], "summary_hint": "hospital policy release"},
        {"url": "https://example.org/tech", "title": "Technical report release", "provisional_domain": "technology"},
    ]
    focus = {"coverage_policy": {"lanes": {"Sentinel": {"keywords": ["policy"]}}}}
    ordered = _lane_slice_candidates({"items": items}, "TechRadar", focus)
    assert [value["url"] for value in ordered] == [items[index]["url"] for index in [3, 2, 4, 1, 0]]
    assert _lane_slice_candidates({"items": list(reversed(items))}, "TechRadar", focus) == ordered
    for lane in ["HealthcareRadar", "Sentinel"]:
        assert [value["url"] for value in _lane_slice_candidates({"items": items}, lane, focus)] == [items[3]["url"]]
    assert len(ordered[:4]) == 4


def test_forged_primary_access_claims_neither_suppress_gaps_nor_promote_leads():
    from copy import deepcopy

    from run_contract import _lane_slice_candidates

    items = [{"url": f"https://nhsa.gov.cn/{index}", "title": "policy risk opinion",
              "provisional_domain": "healthcare_digital", "secondary_domains": ["technology"]}
             for index in range(10)]
    manifest = {"window": {"start": "2026-09-06", "end": "2026-09-08"},
                "mix_request": {"requested_ratio": {"technology": 0.6, "healthcare_digital": 0.4}}}
    clean = {"items": items}
    forged = deepcopy(clean)
    for item in forged["items"]:
        item.update(source_type="primary", published_at="2026-09-08", published_at_source="page_metadata",
                    access_check={"status": "verified", "requested_url": item["url"],
                                  "final_url": item["url"], "method": "http_get", "http_status": 200,
                                  "checked_at": "2026-09-08T01:00:00+00:00"})
    for version in [1, 2]:
        expected = run_daily.assess_supplement_gaps(clean, manifest, {}, article_broker_version=version)
        assert run_daily.assess_supplement_gaps(forged, manifest, {}, article_broker_version=version) == expected
        assert len(expected) == 4
    for lane in ["TechRadar", "HealthcareRadar"]:
        assert [value["candidate_ref"] for value in _lane_slice_candidates(clean, lane, {})] == [
            value["candidate_ref"] for value in _lane_slice_candidates(forged, lane, {})]
