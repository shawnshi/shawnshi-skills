"""Readability plumbing is deterministic; prose adequacy still needs semantic review."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import semantic_agent as agent
from article_broker import NATIVE_VISIBILITY
from briefing_gate import validate_briefing_data
from forge import render_briefing
from run_contract import RunContractError, file_sha256, item_hash
from test_contract_fixtures import cloned_v14_payload

ROOT = Path(__file__).resolve().parents[1]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def native_fixture(tmp_path, text, source_truncated=None):
    binding = {
        "contract_version": "article-broker/3.0",
        "request_sha256": "a" * 64,
        "gap_id": "tech",
        "reservation_id": "fetch-1",
        "invocation_id": "a" * 64 + ":tech:fetch-1",
        "receipt_sha256": "b" * 64,
        "readable_text_sha256": sha(text),
        "transport_visibility": deepcopy(NATIVE_VISIBILITY),
    }
    access = {
        "status": "verified", "checked_at": "2026-09-10T00:00:00+00:00",
        "method": "native_readable", "requested_url": "https://example.org/article",
        "final_url": None, "http_status": None, "failure_class": "none",
        "error_code": None, "native_evidence": binding,
    }
    proof = {
        "evidence_kind": "native_readable", "request_sha256": "a" * 64,
        "gap_id": "tech", "id": "fetch-1", "receipt_sha256": "b" * 64,
        "readable_text": text, "readable_text_sha256": sha(text), "access": access,
        "receipt": {"text": text, "truncated": source_truncated},
    }
    path = tmp_path / "broker_tech_body_1.json"
    write_json(path, proof)
    event = {"kind": "fetch_recorded", "id": "fetch-1", "proof_path": str(path.resolve()),
             "proof_sha256": file_sha256(path)}
    manifest = {"run_dir": str(tmp_path), "article_broker_evidence": {"tech": {
        "request_sha256": "a" * 64, "events": [event, {"kind": "sealed"}],
    }}}
    candidate = {"url": access["requested_url"], "access_check": deepcopy(access),
                 "summary": "A separate compressed synopsis."}
    return candidate, manifest, path


@pytest.mark.parametrize("text", ["A short abstract.\r\nNo full paper here.",
                                  ('方法：比较样本。\\\"\r\n\t😀' * 2000)], ids=["short", "escaped-unicode-long"])
@pytest.mark.parametrize("source_truncated", [None, False])
def test_registered_excerpt_exact_bounded_hash_offsets(tmp_path, text, source_truncated):
    candidate, manifest, path = native_fixture(tmp_path, text, source_truncated)
    before = path.read_bytes()
    result = agent._registered_evidence_excerpt(candidate, manifest)
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= 4000
    assert result["text"] == text[result["start"]:result["end"]]
    assert result["offset_unit"] == "unicode_code_points"
    assert result["readable_text_sha256"] == sha(text)
    assert result["excerpt_sha256"] == sha(result["text"])
    assert result["readable_text_utf8_bytes"] == len(text.encode("utf-8"))
    assert result["readable_text_characters"] == len(text)
    assert result["excerpt_truncated"] == (len(result["text"]) < len(text))
    assert result["source_truncated"] is source_truncated
    assert "abstract_not_full_paper" in result["coverage"]
    assert "body_sha256" not in result
    assert path.read_bytes() == before
    assert candidate["summary"] == "A separate compressed synopsis."


@pytest.mark.parametrize("mutation", ["missing", "mutated", "forged_path", "missing_event",
                                     "duplicate_event", "foreign_request", "unsealed",
                                     "access_mismatch", "text_hash", "receipt_text", "url"])
def test_registered_excerpt_fails_closed(tmp_path, mutation):
    candidate, manifest, path = native_fixture(tmp_path, "Original readable evidence.")
    ledger = manifest["article_broker_evidence"]["tech"]
    event = ledger["events"][0]
    if mutation == "missing":
        path.unlink()
    elif mutation == "mutated":
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "forged_path":
        foreign = tmp_path / "not-authorized.json"
        foreign.write_bytes(path.read_bytes())
        event["proof_path"] = str(foreign)
    elif mutation == "missing_event":
        ledger["events"].pop(0)
    elif mutation == "duplicate_event":
        ledger["events"].insert(0, deepcopy(event))
    elif mutation == "foreign_request":
        ledger["request_sha256"] = "f" * 64
    elif mutation == "unsealed":
        ledger["events"].pop()
    elif mutation in {"access_mismatch", "text_hash", "receipt_text"}:
        proof = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "access_mismatch":
            proof["access"]["checked_at"] = "2026-09-09T00:00:00+00:00"
        elif mutation == "text_hash":
            proof["readable_text_sha256"] = "f" * 64
        else:
            proof["receipt"]["text"] += "changed"
        write_json(path, proof)
        event["proof_sha256"] = file_sha256(path)
    else:
        candidate["url"] = "https://example.org/foreign"
    with pytest.raises(RunContractError, match="semantic readable evidence"):
        agent._registered_evidence_excerpt(candidate, manifest)


def test_legacy_explicit_unavailable_never_reads_candidate_path(tmp_path):
    candidate = {"access_check": {"method": "http_get"},
                 "body_path": str(tmp_path / "private.txt")}
    with patch.object(Path, "read_bytes", side_effect=AssertionError("unauthorized read")):
        result = agent._registered_evidence_excerpt(candidate, {})
    assert result == {"status": "unavailable",
                      "reason": "legacy_access_without_registered_readable_body"}


def test_context_delivers_registered_frozen_contract_and_distinct_evidence(tmp_path):
    contract = json.loads((ROOT / "references/subagent_prompts.json").read_text(encoding="utf-8"))["review_agents"]["SemanticEvaluator"]
    frozen = deepcopy(contract)
    frozen["readability_contract"]["purpose"] = "Frozen earlier request wording, distinct from installed current configuration."
    assert frozen != contract
    prompt_path = tmp_path / "frozen-prompts.json"
    write_json(prompt_path, {"review_agents": {"SemanticEvaluator": frozen}})
    request_path = tmp_path / "semantic_review_request.json"
    dynamic_path = tmp_path / "semantic-dynamic.json"
    packet = {"run_manifest_path": str(tmp_path / "manifest.json"),
              "prompt_config": {"path": str(prompt_path), "sha256": file_sha256(prompt_path)},
              "agent_helper": {"path": str(Path(agent.__file__).resolve()),
                               "sha256": file_sha256(Path(agent.__file__)),
                               "finalize_command": ["frozen-helper", "finalize"]},
              "agent_contract": frozen, "draft_paths": {"dynamic": str(dynamic_path)},
              "write_scope": [str(dynamic_path)]}
    request = {"contract_version": "review-request/1.1", "review_kind": "semantic",
               "run_id": "fixture", "execution_packet": packet, "bound_artifacts": {},
               "max_turns": 2, "halt_condition": "review done"}
    write_json(request_path, request)
    candidate, manifest, _ = native_fixture(tmp_path, "An exact registered abstract, not a paper.")
    manifest.update(run_id="fixture", window={}, topic="test", region="global",
                    mix_request={"requested_ratio": {"technology": 0.6, "healthcare_digital": 0.4}},
                    artifacts={"semantic_review_request": {"artifact_path": str(request_path),
                               "artifact_sha256": file_sha256(request_path)}})
    # Registration and helper/prompt hashes are real; unrelated manifest schema
    # and candidate assessment are covered by the native frozen pipeline suite.
    with patch.object(agent, "load_manifest", return_value=manifest), patch.object(
        agent, "_eligible_candidates", return_value=[deepcopy(candidate)]
    ):
        context = agent.build_agent_context(request_path)
    assert context["agent_contract"] == frozen
    assert context["agent_contract"]["readability_contract"]["contract_version"] == "semantic-readability/1.0"
    assert context["eligible_candidates"][0]["summary"] == candidate["summary"]
    assert context["eligible_candidates"][0]["evidence_excerpt"]["text"] != candidate["summary"]
    assert context["dynamic_draft_path"] == str(dynamic_path.resolve())
    assert context["max_turns"] == 2
    assert not ({"candidate_pool", "history", "request", "supplement"} & set(context))
    context["agent_contract"]["role"] = "mutated returned copy"
    assert packet["agent_contract"] == frozen


def test_schema_and_render_preserve_long_independent_field_paragraphs():
    payload = cloned_v14_payload()
    item = payload["top_10"][0]
    fields = ["fact", "connection", "deduction", "actionability", "summary_zh"]
    for field in fields:
        item[field] = f"{field}：" + "这是一句完整且可追踪的测试材料。" * 30 + "\n\n第二段保留证据范围，不代表临床效果。"
    payload["insights"] = "第一段说明共同问题。\n\n第二段说明机制与差异。\n\n第三段说明决策意义与边界。"
    semantic = payload["pipeline"]["semantic_review"]
    semantic["reviewed_item_hashes"] = [item_hash(item)]
    semantic["lineage_bindings"][0]["output_item_sha256"] = item_hash(item)
    assert not validate_briefing_data(payload)[0]
    rendered = render_briefing(payload)
    assert payload["insights"] in rendered
    for field, label in zip(fields, ["事实", "连接", "推断", "动作", "摘要"], strict=True):
        assert f"**{label}**\n\n{item[field]}" in rendered
    assert item["url"] in rendered and item["title"] in rendered
    assert "## 技术资讯" in rendered and "## 医疗数字化资讯" in rendered
