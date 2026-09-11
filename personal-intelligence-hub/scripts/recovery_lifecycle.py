"""Immutable source adoption/1.0. No scanner, launch, or network authority."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

VERSION = "pih-source-adoption/1.0"
SOURCE_ARTIFACTS = ("candidate_pool", "history_snapshot", "history_review_slice", "focus_config")
IDENTITY_FIELDS = ("report_date", "timezone", "window", "explicit_window", "topic", "region", "mix_request", "linked_from_run_id")


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(value, dict), "JSON object required")
    return value


def tree_hashes(root):
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "source symlinks forbidden")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            # A separately authorized add-only reconciliation is not source evidence.
            if relative.startswith("late-telemetry/"):
                continue
            result[relative] = sha(path)
    return result


def closure_digest(hashes):
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _ownership(source_path, source):
    root = source_path.parent.resolve()
    require(root.name == source["run_id"] and Path(source["run_dir"]).resolve() == root,
            "foreign source run ownership")
    require(source_path.resolve() == root / "run_manifest.json", "noncanonical source manifest")
    require("source_adoption" not in source, "nested adoption forbidden")
    require(source["stages"]["baseline"]["status"] in {"completed", "degraded"}
            and source["stages"]["supplemental"]["status"] in {"completed", "degraded"},
            "whole settled source closure required")
    require(source["stages"]["semantic_review"]["status"] in {"degraded_timeout", "failed"},
            "source semantic invocation must be closed")
    require(source["stages"]["archive"]["status"] == "pending", "archived source cannot be adopted")
    records = [source["stages"][name] for name in ("baseline", "supplemental")]
    records += [source["artifacts"][name] for name in SOURCE_ARTIFACTS if name in source["artifacts"]]
    records += [source["artifacts"]["supplement_request"]]
    for record in records:
        path = Path(record["artifact_path"]).resolve()
        require(path.is_file() and sha(path) == record["artifact_sha256"], "source artifact hash changed")
        if record is source["artifacts"].get("focus_config"):
            frozen = root / "personal-intelligence-hub/references/strategic_focus.json"
            require(sha(frozen) == record["artifact_sha256"], "foreign focus configuration")
        else:
            require(path.parent == root, "foreign source artifact path")
    request = load(source["artifacts"]["supplement_request"]["artifact_path"])
    require(request["run_id"] == source["run_id"], "foreign original request")
    require(Path(source["bundle_snapshot"]["snapshot_root"]).resolve() == root / "personal-intelligence-hub",
            "source must own frozen validator bundle")
    for packet in request["execution_packets"]:
        for name in ("result", "draft"):
            require(Path(packet["output_paths"][name]).resolve().parent == root, "foreign supplement output")
    for ledger in source.get("article_broker_evidence", {}).values():
        require(ledger.get("status") not in {"pending", "running"}, "pending broker closure")
    for reservation in source.get("telemetry", {}).get("reservations", {}).values():
        require(reservation.get("status") != "reserved", "pending original invocation")


# Original terminal replay returns before every publication path. Audit guards
# additionally deny writes, sockets and subprocesses in that frozen validator process.
FROZEN_REPLAY = r'''
import sys,json,os
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root/'personal-intelligence-hub/scripts'))
def audit(event,args):
    if event.startswith('socket.') or event in {'subprocess.Popen','os.system','os.mkdir','os.remove','os.rename','os.rmdir','os.link','os.symlink','os.truncate'}:
        raise RuntimeError('read-only frozen replay denied '+event)
    if event == 'open':
        mode=args[1]; flags=args[2]
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
            raise RuntimeError('read-only frozen replay denied write')
sys.addaudithook(audit)
from run_contract import load_manifest,register_supplement_results,review_input_bundle_sha256,registered_candidate_lineage
m=load_manifest(root/'run_manifest.json')
assert m['stages']['supplemental']['status'] in {'completed','degraded'}
r=json.loads(Path(m['artifacts']['supplement_request']['artifact_path']).read_text(encoding='utf8'))
p,a=register_supplement_results(root/'run_manifest.json',m['artifacts']['supplement_request']['artifact_path'],[p['output_paths']['result'] for p in r['execution_packets']])
print(json.dumps({'status':'valid','input_bundle_sha256':review_input_bundle_sha256(m),'lineage_count':len(registered_candidate_lineage(m)),'aggregate_sha256':m['stages']['supplemental']['artifact_sha256']}))
'''


def frozen_replay(source_path):
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", FROZEN_REPLAY,
                             str(Path(source_path).resolve().parent)], shell=False, check=True,
                            capture_output=True, text=True, encoding="utf-8", timeout=120,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    value = json.loads(result.stdout)
    require(value.get("status") == "valid", "original frozen validators refused source")
    return value


def history_preflight(source):
    from update_index import rebuild_history
    record = source["artifacts"]["history_snapshot"]
    metadata = record["metadata"]
    require(metadata.get("allow_existing_archive_replacement") is False,
            "adoption never authorizes canonical replacement")
    news = Path(metadata["news_dir"]).resolve()
    targets = metadata["archive_target_state"]
    stem = "intelligence_" + source["report_date"].replace("-", "") + "_briefing"
    require(set(targets) == {stem + suffix for suffix in (".json", ".md", ".manifest.json")},
            "canonical target set mismatch")
    require(all(value is None and not (news / name).exists() for name, value in targets.items()),
            "canonical replacement refused")
    snapshot = load(record["artifact_path"])
    actual = rebuild_history(news_dir=news, now=datetime.fromisoformat(snapshot["generated_at"]),
                             exclude_report_date=source["report_date"], dry_run=True)
    require(actual == snapshot, "stale source history; no automatic refresh or rescan")


def preview(source_path):
    source_path = Path(source_path).resolve()
    before = tree_hashes(source_path.parent)
    source = load(source_path)
    _ownership(source_path, source)
    replay = frozen_replay(source_path)
    history_preflight(source)
    require(tree_hashes(source_path.parent) == before, "source changed during admission")
    return {"contract_version": VERSION, "status": "admissible", "source_manifest_path": str(source_path),
            "source_manifest_sha256": sha(source_path), "source_run_id": source["run_id"],
            "source_hashes": before, "source_closure_sha256": closure_digest(before),
            "original_validator_result": replay, "identity": {k: source[k] for k in IDENTITY_FIELDS},
            "evidence_refreshed": False, "network_performed": False}


def validated_source(manifest):
    """Every source consumer checks derivation and original ownership, not new IDs."""
    binding = manifest.get("source_adoption")
    if binding is None:
        return manifest
    path = Path(binding["path"]).resolve()
    require(path == Path(manifest["run_dir"]).resolve() / "source_admission.json"
            and sha(path) == binding["sha256"], "adoption admission binding changed")
    admission = load(path)
    require(admission.get("contract_version") == VERSION and admission["new_run_id"] == manifest["run_id"],
            "foreign adoption admission")
    source_path = Path(admission["source_manifest_path"]).resolve()
    require(sha(source_path) == admission["source_manifest_sha256"]
            and tree_hashes(source_path.parent) == admission["source_hashes"], "immutable source closure changed")
    require(closure_digest(admission["source_hashes"]) == admission["source_closure_sha256"], "closure digest mismatch")
    source = load(source_path)
    _ownership(source_path, source)
    require(source["run_id"] == admission["source_run_id"] != manifest["run_id"], "adoption identity replay")
    require(admission["admitted_at"] == manifest["created_at"], "admission clock mismatch")
    for key in IDENTITY_FIELDS:
        require(manifest[key] == source[key] == admission["identity"][key], "adopted identity changed: " + key)
    for key in SOURCE_ARTIFACTS:
        require(manifest["artifacts"].get(key) == source["artifacts"].get(key), "adopted artifact rebound: " + key)
    for key in ("baseline", "supplemental"):
        require(manifest["stages"][key] == source["stages"][key], "source stage relabeled")
    require("supplement_request" not in manifest["artifacts"]
            and not manifest.get("article_broker_evidence"), "new run cannot own original broker proofs")
    return source


def apply(source_path, expected_closure, runtime_dir, *, skill_path=None):
    from run_contract import create_run, commit_manifest, locked_manifest
    from hub_utils import HUB_DIR, atomic_dump_json
    admission = preview(source_path)
    require(admission["source_closure_sha256"] == expected_closure, "preview closure changed")
    source = load(source_path)
    runtime = Path(runtime_dir).resolve()
    source_root = Path(source_path).resolve().parent
    require(not runtime.exists(), "new isolated runtime root required; adoption replay refused")
    require(not runtime.is_relative_to(source_root), "adoption cannot write inside original run")
    identifier = uuid.uuid4().hex
    # A dedicated runtime also confines create_run's active_run.json pointer.
    path, manifest = create_run(report_date=source["report_date"], timezone_name=source["timezone"],
        window_days=source["window"]["days"], explicit_window_days=source["explicit_window"],
        topic=source["topic"], region=source["region"], requested_ratio=source["mix_request"]["requested_ratio"],
        ratio_source=source["mix_request"]["ratio_source"], ratio_reason=source["mix_request"]["ratio_reason"],
        linked_from_run_id=source["linked_from_run_id"], runtime_dir=runtime, run_id=identifier,
        skill_path=Path(skill_path) if skill_path else HUB_DIR / "SKILL.md")
    record_path = path.parent / "source_admission.json"
    admission.update(new_run_id=identifier, admitted_at=manifest["created_at"], status="admitted",
                     budget_boundary="independent_new_run_no_source_headroom_transfer")
    atomic_dump_json(record_path, admission)
    with locked_manifest(path) as (current, expected):
        for key in SOURCE_ARTIFACTS:
            if key in source["artifacts"]:
                current["artifacts"][key] = deepcopy(source["artifacts"][key])
        for key in ("baseline", "supplemental"):
            current["stages"][key] = deepcopy(source["stages"][key])
        current["source_adoption"] = {"contract_version": VERSION, "path": str(record_path.resolve()), "sha256": sha(record_path)}
        validated_source(current)
        commit_manifest(path, current, expected)
    require(tree_hashes(source_root) == admission["source_hashes"], "source changed during apply")
    return {"status": "adopted", "run_id": identifier, "manifest_path": str(path.resolve()),
            "execution_cli_path": current["bundle_snapshot"]["execution_cli_path"],
            "admission_path": str(record_path), "semantic_review": "fresh_independent_required"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "apply"))
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--expected-closure-sha256")
    parser.add_argument("--new-runtime-dir", type=Path)
    args = parser.parse_args()
    if args.operation == "preview":
        result = preview(args.source_manifest)
    else:
        require(args.expected_closure_sha256 and args.new_runtime_dir, "apply requires preview SHA and new runtime")
        result = apply(args.source_manifest, args.expected_closure_sha256, args.new_runtime_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
