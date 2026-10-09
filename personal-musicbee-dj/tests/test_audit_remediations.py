"""Audit regressions use disposable fixtures, never the real library or player."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core.curator import DJCurator
from src.core.models import Track
from src.core.tag_preflight import attempted_paths
from src.core import tag_writer
from src.tag_completion import import_result, verify_task
import test_tag_completion as media_fixtures
from test_tag_completion import record_review, research_rows, task

media = media_fixtures.media


def test_final_live_refresh_cannot_export_a_hard_constraint_violation(tmp_path, monkeypatch):
    tracks = []
    for i in range(1, 102):
        path = tmp_path / f"synthetic-{i}.flac"
        path.write_bytes(b"fixture")
        tracks.append(Track(i, f"Fixture {i}", f"Artist {i}", "Fixture album", "Ambient",
                            100 if i == 101 else 0, 80, 60000, "2026-01-01T00:00:00Z", str(path),
                            dj_vocals="instrumental", dj_energy="low", dj_scene="focus"))
    curator = DJCurator({
        "musicbee": {"xml_path": str(tmp_path / "unused.xml")},
        "playlist": {"max_tracks_per_session": 1, "output_m3u": str(tmp_path / "queue.m3u")},
        "scenes": {"focus": {"genres": ["Ambient"]}},
        "request": {"no_vocals": True, "strict_evidence": True, "seed": 19},
        "tag_completion": {"enabled": True, "library_root": str(tmp_path), "candidate_limit": 100},
    })
    monkeypatch.setattr(curator.parser, "load_library", lambda: tracks)

    def refresh(selected, settings, limit=True, required_fields=None):
        if not limit:
            for track in selected:
                track.dj_vocals = "vocal"
        return {"inspected_files": min(len(selected), 100) if limit else len(selected), "errors": 0}

    monkeypatch.setattr("src.core.tag_preflight.inspect_tracks", refresh)
    export = Mock(return_value=(str(tmp_path / "queue.m3u"), 1))
    monkeypatch.setattr(curator, "_export_to_m3u", export)
    with pytest.raises(ValueError, match="Final live metadata"):
        curator.generate_m3u("scene", "focus", "low")
    export.assert_not_called()


def test_optimized_python_preserves_result_validation():
    source = Path(tag_writer.__file__).read_text(encoding="utf-8")
    namespace = {"__name__": "audit_optimized", "__file__": tag_writer.__file__}
    exec(compile(source, tag_writer.__file__, "exec", optimize=1), namespace)
    path = "synthetic.flac"
    row = {"file": path, "Tempo": "", "mood": "INVALID", "DJ_VOCALS": "",
           "DJ_ENERGY": "", "DJ_SCENE": "", "confidence": "high", "unresolved": [],
           "evidence": [{"url": "https://example.org/fixture", "supports": ["mood"],
                         "note": "Synthetic fixture", "kind": "inference"}]}
    with pytest.raises(ValueError, match="Invalid mood"):
        namespace["validate_results"]({"rows": [row], "summary": {"input_count": 1, "researched_count": 1, "limitations": []}}, {path: {"tags": {}}})


def test_resume_rejects_researched_but_unapplied_changes(media, tmp_path):
    root, make = media
    path = make()
    work, records = task(tmp_path, root, [path])
    report = tmp_path / "report.json"
    report.write_text(json.dumps(research_rows(records)), encoding="utf-8")
    accepted = import_result(work, "batch-0001", report)
    record_review(work, "batch-0001", accepted["result_sha256"], records, tmp_path)
    verify_task(work)
    with pytest.raises(ValueError, match="unapplied|not physically verified"):
        attempted_paths(work, root, {str(path)})


@pytest.mark.parametrize("count", [-1, 2, True])
def test_invalid_summary_counts_are_rejected(count):
    result = research_rows([{"path": "fixture.flac"}])
    result["summary"]["input_count"] = count
    with pytest.raises(ValueError, match="summary"):
        tag_writer.validate_results(result, {"fixture.flac": {"tags": {}}})


def test_subjective_source_fact_is_rejected():
    result = research_rows([{"path": "fixture.flac"}])
    result["rows"][0]["evidence"][0]["kind"] = "source_fact"
    with pytest.raises(ValueError, match="inference"):
        tag_writer.validate_results(result, {"fixture.flac": {"tags": {}}})


def test_field_confidence_and_requested_scope_limit_updates():
    result = research_rows([{"path": "fixture.flac"}])
    result["rows"][0]["field_confidence"] = {field: "high" for field in tag_writer.FIELDS}
    result["rows"][0]["field_confidence"]["DJ_SCENE"] = "low"
    assert tag_writer.validate_results(result, {"fixture.flac": {"tags": {}, "requested_fields": ["DJ_SCENE", "DJ_ENERGY"]}}) == {"fixture.flac": {"DJ_ENERGY": "low"}}


def test_apply_requires_parent_review_and_rejects_review_tampering(media, tmp_path):
    from src.tag_completion import apply_batch
    root, make = media
    path = make()
    work, records = task(tmp_path, root, [path])
    report = tmp_path / "result.json"
    report.write_text(json.dumps(research_rows(records)), encoding="utf-8")
    accepted = import_result(work, "batch-0001", report)
    before = tag_writer.digest(path)
    with pytest.raises(ValueError, match="regular|does not exist|Cannot|local|file|review|load"):
        apply_batch(work, "batch-0001", accepted["result_sha256"])
    assert tag_writer.digest(path) == before
    record_review(work, "batch-0001", accepted["result_sha256"], records, tmp_path)
    (work / "batches" / "batch-0001" / "review.json").write_text("{}")
    with pytest.raises(ValueError, match="review.*changed"):
        apply_batch(work, "batch-0001", accepted["result_sha256"])
    assert tag_writer.digest(path) == before


def test_expired_deadline_never_changes_audio(media, tmp_path):
    import time
    root, make = media
    path = make()
    before = tag_writer.digest(path)
    from src.core.tag_inventory import inventory
    with pytest.raises(TimeoutError, match="deadline"):
        tag_writer.update_one(path, {"Tempo": "Fast"}, inventory(path, root), tmp_path / "backups", root,
                              deadline=time.monotonic() - 1)
    assert tag_writer.digest(path) == before and not (tmp_path / "backups").exists()


def test_recovery_inspection_is_read_only_and_reports_prepared_replace(media, tmp_path):
    from src.tag_completion import inspect_recovery
    root, make = media
    path = make()
    work, records = task(tmp_path, root, [path])
    with tag_writer.library_lock(root):
        tag_writer.update_one(path, {"Tempo": "Fast"}, records[0], work / "backups", root)
    receipt_path = next((work / "backups").glob("*.json"))
    receipt = json.loads(receipt_path.read_text())
    receipt["status"] = "prepared"
    receipt_path.write_text(json.dumps(receipt))
    before = {file: file.read_bytes() for file in (path, receipt_path, receipt_path.with_suffix(".header"))}
    result = inspect_recovery(work, receipt_path)
    assert result["observed_state"] == "replacement_present" and not result["music_files_modified"]
    assert all(file.read_bytes() == data for file, data in before.items())
    assert not (root / ".musicbee-dj-tag-writer.lock").exists()


def test_research_role_and_schema_are_pinned(media, tmp_path):
    from src.tag_completion import next_jobs
    root, make = media
    work, _ = task(tmp_path, root, [make()])
    assert next_jobs(work)[0]["schema"] == str(work / "tag-schema.json")
    (work / ".pi" / "agents" / "musicbee-tags.md").write_text("tampered")
    with pytest.raises(ValueError, match="role/schema"):
        next_jobs(work)


def test_workflow_serial_contract_without_starting_children():
    import subprocess
    workflow = Path(__file__).resolve().parents[1] / "src" / "research_wave.js"
    script = """
const fs=require('fs');
(async()=>{
const {runWorkflowScript}=await import('file:///C:/Users/shich/.pi/agent/npm/node_modules/pi-subagents/src/workflows/scripted-workflow.js');
const source=fs.readFileSync(process.argv[1],'utf8'); const launches=[];
const execute=args=>runWorkflowScript({script:source,args,timeoutMs:10000,globalConcurrencyLimit:1,
  launch:async(key,params)=>{launches.push({key,params});return {key,ok:true,output:'synthetic output',artifactPaths:[]};},
  status:async()=>{throw Error('unexpected status');}});
const result=await execute({jobs:[{key:'batch-0001',count:5,cwd:'fixture',input:'input.csv',schema:'schema.json'}]});
if(launches.length!==1||launches[0].key!=='batch-0001'||launches[0].params.agent!=='musicbee-tags'||
   launches[0].params.outputMode!=='file-only'||result.value.jobs[0].ok!==true)throw Error('bad native contract');
try{await execute({jobs:[{},{}]});throw Error('parallel accepted');}catch(e){if(!e.message.includes('exactly one'))throw e;}
if(launches.length!==1)throw Error('extra dispatch');
// Real sandbox validation must reject the former single-object call before the fake launch callback.
try{await runWorkflowScript({script:"return await runs.run({key:'batch-0001',agent:'musicbee-tags',task:'fixture'});",
  timeoutMs:10000,launch:async()=>{throw Error('invalid call reached launch');},status:async()=>{throw Error('unexpected status');}});
  throw Error('single-object call accepted');}catch(e){if(!e.message.includes('invalid key'))throw e;}
console.log('installed native sandbox contract passed; actual research children launched: 0');
})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run(["node", "-e", script, str(workflow)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_cli_missing_tags_without_authority_creates_no_research_task(media, tmp_path, monkeypatch, capsys):
    import sys
    import src.cli as cli
    from test_tag_completion import curator_for
    root, make = media
    path = make()
    config = curator_for(tmp_path, path, root).config
    config['musicbee']['exe_path'] = str(tmp_path / 'unused.exe')
    monkeypatch.setattr(cli, 'load_config', lambda _: config)
    monkeypatch.setattr(cli, 'resolve_config_paths', lambda config, _: config)
    monkeypatch.setattr(sys, 'argv', ['cli.py', '--type', 'scene', '--value', 'focus', '--generate-only'])
    inventory_write = Mock(side_effect=AssertionError('No authorized research artifact'))
    monkeypatch.setattr('src.core.tag_inventory.write_inventory', inventory_write)
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 3
    report = next(json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"status":'))
    assert report['status'] == 'tag_completion_authorization_required' and not report['task_created']
    inventory_write.assert_not_called()


def test_task_role_discovered_by_installed_native_resolver(media, tmp_path):
    import subprocess
    root, make = media
    work, _ = task(tmp_path, root, [make()])
    # Parser/discovery only: no child session, provider call or credential read.
    script = """
(async()=>{
const {discoverAgents}=await import('file:///C:/Users/shich/.pi/agent/npm/node_modules/pi-subagents/src/agents/agents.js');
const result=discoverAgents(process.argv[1],'project',undefined,{globalNpmRoot:null});
const agent=result.agents.find(a=>a.name==='musicbee-tags');
if(!agent||agent.systemPromptMode!=='replace'||agent.model!=='antigravity/gemini-3.8-flash')throw Error('role discovery failed');
if(agent.inheritProjectContext!==false||agent.inheritSkills!==false)throw Error('unexpected inherited context');
console.log('native task-role discovery passed; no child launched');
})().catch(e=>{console.error(e);process.exit(1)});
"""
    result = subprocess.run(['node', '-e', script, str(work / 'batches' / 'batch-0001')],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
