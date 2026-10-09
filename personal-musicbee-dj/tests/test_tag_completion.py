"""Generated-media tests only. Never read or alter the real D:\\Music library."""

import csv
import json
import plistlib
import subprocess
from unittest.mock import Mock

import pytest

from src.core.attributes import MOOD_ALIASES, requested_values
from src.core.curator import DJCurator
from src.core.tag_inventory import (
    FIELDS,
    codec,
    incomplete,
    inventory,
    scan_paths,
    write_inventory,
)
from src.core.tag_preflight import TagCompletionRequired
from src.core.tag_writer import (
    digest,
    library_lock,
    read_results,
    restore,
    update_one,
)
from src.tag_completion import (
    apply_batch,
    import_result,
    review_batch,
    mark_job,
    next_jobs,
    prepare_jobs,
    verify_task,
)


@pytest.fixture
def media(tmp_path):
    root = tmp_path / "music"
    root.mkdir()

    def make(ext="flac", version=4):
        path = root / f"音楽-{len(list(root.iterdir()))}.{ext}"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.2",
                "-y",
                str(path),
            ],
            check=True,
            timeout=20,
        )
        module = codec()
        audio = module.File(path)
        if ext == "flac":
            from mutagen.flac import Picture

            audio["TITLE"] = ["Original title"]
            audio["ARTIST"] = ["Fixture Artist"]
            audio["ALBUM"] = ["Fixture Album"]
            audio["DATE"] = ["2001"]
            audio["REPLAYGAIN_TRACK_GAIN"] = ["-7.23 dB"]
            pic = Picture()
            pic.mime = "image/png"
            pic.type = 3
            pic.data = b"protected-artwork"
            audio.add_picture(pic)
            audio.save()
        else:
            from mutagen.id3 import APIC, TIT2, TPE1, TXXX

            audio.tags.add(TIT2(encoding=1, text=["Original title"]))
            audio.tags.add(TPE1(encoding=1, text=["Fixture Artist"]))
            audio.tags.add(
                TXXX(encoding=1, desc="REPLAYGAIN_TRACK_GAIN", text=["-7.23 dB"])
            )
            audio.tags.add(
                APIC(
                    encoding=1,
                    mime="image/png",
                    type=3,
                    desc="cover",
                    data=b"protected-artwork",
                )
            )
            audio.tags.save(path, v2_version=version)
        return path

    return root, make


def task(tmp_path, root, paths):
    records, errors = scan_paths(paths, root)
    output = tmp_path / "work"
    write_inventory(output, root, records, errors)
    prepare_jobs(output)
    return output, records


def research_rows(records):
    # Example.org evidence is synthetic test input, not evidence about any real song.
    return {
        "summary": {"input_count": len(records), "researched_count": len(records), "limitations": []},
        "rows": [
            {
                "file": r["path"],
                "Tempo": "Moderate",
                "mood": "Dreamy",
                "DJ_VOCALS": "instrumental",
                "DJ_ENERGY": "low",
                "DJ_SCENE": "focus;coding",
                "confidence": "high",
                "unresolved": [],
                "evidence": [
                    {
                        "url": "https://example.org/fixture",
                        "supports": ["mood", "DJ_ENERGY", "DJ_SCENE"],
                        "note": "Synthetic mechanical test fixture, not a real music claim",
                        "kind": "inference",
                    },
                    {"url": "https://example.org/fixture", "supports": ["Tempo", "DJ_VOCALS"],
                     "note": "Synthetic fixture: recording-specific BPM 100; no real claim", "kind": "source_fact"},
                ],
            }
            for r in records
        ]
    }


def record_review(work, batch, checksum, records, tmp_path):
    result = json.loads((work / "batches" / batch / "result.json").read_text(encoding="utf-8"))
    updates = read_results(work / "batches" / batch / "result.json", {r["path"]: r for r in records})
    review = {"result_sha256": checksum, "run_reference": "synthetic-successful-run",
              "decisions": [{"file": path, "field": field, "decision": "approve",
                             "note": "Synthetic source semantics, not a real music claim",
                             "url": next(e["url"] for row in result["rows"] if row["file"] == path
                                         for e in row["evidence"] if field in e["supports"]),
                             "recording_match": True}
                            for path, fields in updates.items() for field in fields]}
    payload = tmp_path / "parent-review.json"
    payload.write_text(json.dumps(review), encoding="utf-8")
    return review_batch(work, batch, checksum, payload)


@pytest.mark.parametrize("ext,version", [("flac", 4), ("mp3", 3), ("mp3", 4)])
def test_roundtrip_protects_audio_other_tags_and_exact_restore(
    media, tmp_path, ext, version
):
    root, make = media
    source = make(ext, version)
    before = digest(source)
    record = inventory(source, root)
    changes = {
        "Tempo": "Fast",
        "mood": "Upbeat",
        "DJ_VOCALS": "instrumental",
        "DJ_ENERGY": "medium",
        "DJ_SCENE": "focus;coding",
    }
    backup = tmp_path / "backups"
    with library_lock(root):
        receipt = update_one(source, changes, record, backup, root)
    assert receipt["status"] == "committed"
    assert (
        digest(
            source,
            __import__("src.core.tag_writer", fromlist=["header_end"]).header_end(
                source
            ),
        )
        == receipt["payload_sha256"]
    )
    assert inventory(source, root)["needs"] == []
    rp = next(backup.glob("*.json"))
    with library_lock(root):
        restore(source, rp, next(backup.glob("*.header")), root)
    assert digest(source) == before
    assert source.stat().st_mtime_ns == record["mtime_ns"]


def test_drift_existing_values_and_wrong_scope_deny_write(media, tmp_path):
    root, make = media
    source = make()
    audio = codec().File(source)
    audio["DJ_ENERGY"] = ["high"]
    audio.save()
    record = inventory(source, root)
    before = digest(source)
    with pytest.raises(ValueError, match="overwrite"):
        update_one(source, {"DJ_ENERGY": "low"}, record, tmp_path / "backups", root)
    drift = {**record, "mtime_ns": 0}
    with pytest.raises(ValueError, match="modification"):
        update_one(source, {"Tempo": "Fast"}, drift, tmp_path / "backups", root)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="Out-of-library"):
        update_one(source, {"Tempo": "Fast"}, record, tmp_path / "backups", other)
    assert digest(source) == before


def test_second_writer_and_stale_lock_not_silently_removed(media):
    root, _ = media
    with library_lock(root):
        with pytest.raises(FileExistsError):
            with library_lock(root):
                pass
    assert not (root / ".musicbee-dj-tag-writer.lock").exists()
    lock = root / ".musicbee-dj-tag-writer.lock"
    lock.write_text("other-owner", encoding="ascii")
    with pytest.raises(FileExistsError):
        with library_lock(root):
            pass
    assert lock.read_text() == "other-owner"


def test_corrupt_audio_is_error_not_empty_tags(media):
    root, _ = media
    source = root / "broken.mp3"
    source.write_bytes(b"not MPEG data")
    records, errors = scan_paths([source], root)
    assert records == [] and len(errors) == 1
    assert errors[0]["error_type"] == "HeaderNotFoundError"


def test_csv_exact_schema_and_serial_10_track_batches(media, tmp_path):
    root, make = media
    path = make()
    record = inventory(path, root)
    # Distinct paths fixture tests batching independently of reading 51 real files.
    records = []
    for i in range(51):
        row = {**record["row"], "文件名": str(root / f"{i}.flac")}
        records.append({**record, "path": row["文件名"], "row": row})
    output = tmp_path / "work"
    write_inventory(output, root, records, [])
    summary = prepare_jobs(output)
    assert summary["batches"] == 6 and summary["tracks"] == 51 and summary["concurrency"] == 1
    jobs = next_jobs(output)
    assert [j["count"] for j in jobs] == [10]
    assert [j["count"] for j in json.loads((output / "jobs.json").read_text())["jobs"]] == [10, 10, 10, 10, 10, 1]
    assert (output / ".pi" / "agents" / "musicbee-tags.md").is_file()
    with pytest.raises(ValueError, match="serial"):
        next_jobs(output, count=4)
    with (output / "missing_tags.csv").open(encoding="utf-8-sig", newline="") as h:
        rows = list(csv.DictReader(h))
    assert len(rows) == 51 and len(set(r["文件名"] for r in rows)) == 51
    assert list(rows[0]) == ["文件名", "标题", "演出者", "专辑 / 来源", "年份"] + FIELDS
    assert (output / "missing_tags.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(ValueError, match="overwritten"):
        prepare_jobs(output)


def test_research_gates_missing_evidence_unknown_invalid_duplicate_and_mismatch(
    media, tmp_path
):
    root, make = media
    source = make()
    record = inventory(source, root)
    report = tmp_path / "report.json"
    result = research_rows([record])
    row = result["rows"][0]
    row["evidence"] = []
    report.write_text(json.dumps(result), encoding="utf-8")
    assert read_results(report, {record["path"]: record})[record["path"]] == {}
    row["evidence"] = research_rows([record])["rows"][0]["evidence"]
    row["DJ_ENERGY"] = "unknown"
    row["unresolved"] = ["DJ_ENERGY"]
    report.write_text(json.dumps(result), encoding="utf-8")
    assert (
        "DJ_ENERGY"
        not in read_results(report, {record["path"]: record})[record["path"]]
    )
    row["Tempo"] = "200"
    report.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Tempo"):
        read_results(report, {record["path"]: record})
    row["Tempo"] = "Moderate"
    result["rows"] = [row, row]
    report.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        read_results(report, {record["path"]: record})
    result["rows"] = [row]
    report.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        read_results(report, {"other": record})
    row["DJ_SCENE"] = "unknown;focus"
    report.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid DJ_SCENE"):
        read_results(report, {record["path"]: record})
    assert incomplete("DJ_VOCALS", ["unknown"])


def test_import_pinned_apply_verify_and_idempotent_commits(media, tmp_path):
    root, make = media
    source = make()
    work, records = task(tmp_path, root, [source])
    report = tmp_path / "report.json"
    report.write_text(json.dumps(research_rows(records)), encoding="utf-8")
    accepted = import_result(work, "batch-0001", report)
    with pytest.raises(ValueError, match="SHA256"):
        apply_batch(work, "batch-0001", "wrong")
    record_review(work, "batch-0001", accepted["result_sha256"], records, tmp_path)
    first = apply_batch(work, "batch-0001", accepted["result_sha256"])
    assert first["applied_files"] == 1 and first["applied_fields"] == 5
    assert (
        apply_batch(work, "batch-0001", accepted["result_sha256"])["applied_files"] == 0
    )
    final = verify_task(work)
    assert (
        final["all_checked_commits_valid"] and final["remaining_incomplete_files"] == 0
    )
    assert final["verified_commits"] == 1


def test_manifest_csv_and_result_tamper_are_rejected(media, tmp_path):
    root, make = media
    work, records = task(tmp_path, root, [make()])
    report = tmp_path / "report.json"
    report.write_text(json.dumps(research_rows(records)), encoding="utf-8")
    accepted = import_result(work, "batch-0001", report)
    (work / "batches" / "batch-0001" / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        apply_batch(work, "batch-0001", accepted["result_sha256"])
    (work / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest changed"):
        next_jobs(work)


def test_failed_lane_prevents_new_jobs(media, tmp_path):
    root, make = media
    work, _ = task(tmp_path, root, [make()])
    mark_job(work, "batch-0001", "running")
    assert next_jobs(work) == []
    mark_job(work, "batch-0001", "blocked", "Researcher timed out before a checkpoint")
    with pytest.raises(ValueError, match="lane blocked"):
        next_jobs(work)


def curator_for(tmp_path, path, root, enabled=True):
    xml = tmp_path / "library.xml"
    with xml.open("wb") as h:
        plistlib.dump(
            {
                "Tracks": {
                    "1": {
                        "Track ID": 1,
                        "Name": "Original title",
                        "Artist": "Fixture Artist",
                        "Genre": "Ambient",
                        "Location": path.as_uri(),
                        "Total Time": 200,
                    }
                }
            },
            h,
        )
    return DJCurator(
        {
            "musicbee": {"xml_path": str(xml)},
            "playlist": {
                "output_m3u": str(tmp_path / "queue.m3u"),
                "max_tracks_per_session": 1,
            },
            "scenes": {"focus": {"genres": ["Ambient"]}, "coding": {"genres": []}},
            "tag_completion": {
                "enabled": enabled,
                "library_root": str(root),
                "candidate_limit": 100,
            },
        }
    )


def test_playlist_handoff_before_export_and_read_only_does_not_trigger(media, tmp_path):
    root, make = media
    path = make()
    before = digest(path)
    curator = curator_for(tmp_path, path, root)
    with pytest.raises(TagCompletionRequired) as caught:
        curator.generate_m3u("scene", "focus")
    assert len(caught.value.records) == 1
    assert not (tmp_path / "queue.m3u").exists()
    assert digest(path) == before
    result = curator.generate_m3u("scene", "focus", export=False)
    assert result.exported_tracks == 1 and not (tmp_path / "queue.m3u").exists()
    assert curator.last_diagnostics["tag_completion"]["reason"] == "read_only_mode"


def test_live_tags_override_stale_xml_and_mood_vocabulary(media, tmp_path):
    root, make = media
    path = make()
    audio = codec().File(path)
    for field, value in {
        "Tempo": "Moderate",
        "mood": "Dreamy",
        "DJ_VOCALS": "instrumental",
        "DJ_ENERGY": "low",
        "DJ_SCENE": "focus;coding",
    }.items():
        audio[field] = [value]
    audio.save()
    curator = curator_for(tmp_path, path, root)
    result = curator.generate_m3u("scene", "focus", explain=True)
    assert result.exported_tracks == 1
    assert (
        result.unknown_vocal_tag_tracks
        == result.unknown_energy_tag_tracks
        == result.unknown_scene_tag_tracks
        == 0
    )
    assert requested_values(["Dreamy", "Sunday Brunch"], MOOD_ALIASES, "mood") == {
        "dreamy",
        "sunday brunch",
    }


def test_unresolved_completed_attempt_does_not_loop(media, tmp_path):
    root, make = media
    path = make()
    work, records = task(tmp_path, root, [path])
    report = tmp_path / "report.json"
    rows = research_rows(records)
    for row in rows["rows"]:
        row.update(
            Tempo="",
            mood="",
            DJ_VOCALS="unknown",
            DJ_ENERGY="unknown",
            DJ_SCENE="unknown",
            unresolved=FIELDS,
            confidence="low",
            evidence=[],
        )
    report.write_text(json.dumps(rows), encoding="utf-8")
    accepted = import_result(work, "batch-0001", report)
    record_review(work, "batch-0001", accepted["result_sha256"], records, tmp_path)
    verify_task(work)
    curator = curator_for(tmp_path, path, root)
    curator.config["tag_completion"]["completed_task"] = str(work)
    result = curator.generate_m3u("scene", "focus")
    assert result.exported_tracks == 1 and result.unknown_vocal_tag_tracks == 1
    assert (
        curator.last_diagnostics["tag_completion"]["unresolved_after_completed_attempt"]
        == 1
    )


def test_generate_only_cli_never_queries_or_launches_player(
    media, tmp_path, monkeypatch, capsys
):
    import src.cli as cli

    root, make = media
    path = make()
    curator = curator_for(tmp_path, path, root, enabled=False)
    config = curator.config
    config["musicbee"]["exe_path"] = str(tmp_path / "not-installed.exe")
    monkeypatch.setattr(cli, "load_config", lambda _: config)
    monkeypatch.setattr(cli, "resolve_config_paths", lambda c, _: c)
    monkeypatch.setattr(
        cli, "musicbee_running", Mock(side_effect=AssertionError("no process query"))
    )
    monkeypatch.setattr(
        cli.subprocess, "Popen", Mock(side_effect=AssertionError("no player launch"))
    )
    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        ["cli.py", "--type", "scene", "--value", "focus", "--generate-only"],
    )
    cli.main()
    assert '"playback_requested": false' in capsys.readouterr().out
    cli.musicbee_running.assert_not_called()
    cli.subprocess.Popen.assert_not_called()


def test_cli_missing_tag_handoff_has_jobs_and_no_audio_or_player_write(
    media, tmp_path, monkeypatch, capsys
):
    import src.cli as cli

    root, make = media
    path = make()
    before = digest(path)
    config = curator_for(tmp_path, path, root).config
    config["musicbee"]["exe_path"] = str(tmp_path / "not-installed.exe")
    monkeypatch.setattr(cli, "load_config", lambda _: config)
    monkeypatch.setattr(cli, "resolve_config_paths", lambda c, _: c)
    monkeypatch.setattr(
        cli, "musicbee_running", Mock(side_effect=AssertionError("no process query"))
    )
    monkeypatch.setattr(
        cli.subprocess, "Popen", Mock(side_effect=AssertionError("no player launch"))
    )
    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        ["cli.py", "--type", "scene", "--value", "focus", "--generate-only", "--allow-tag-completion"],
    )
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 3
    from pathlib import Path

    data = next(
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith('{"status":')
    )
    assert data["status"] == "needs_tag_completion" and not data["playback_requested"]
    assert data["summary"]["incomplete_files"] == 1 and len(data["jobs"]) == 1
    assert Path(data["work_dir"], "missing_tags.csv").exists()
    assert digest(path) == before
    cli.subprocess.Popen.assert_not_called()


def test_windows_alternate_stream_and_security_survive_commit_and_restore(
    media, tmp_path
):
    import os

    if os.name != "nt":
        pytest.skip("Windows NTFS property test")
    from pathlib import Path
    from src.core.tag_writer import security_digest

    root, make = media
    source = make()
    stream = Path(str(source) + ":musicbee-test-fixture")
    stream.write_bytes(b"protected auxiliary stream")
    original_security = security_digest(source)
    baseline = inventory(source, root)
    backup = tmp_path / "backups"
    update_one(source, {"Tempo": "Fast"}, baseline, backup, root)
    assert stream.read_bytes() == b"protected auxiliary stream"
    assert security_digest(source) == original_security
    restore(source, next(backup.glob("*.json")), next(backup.glob("*.header")), root)
    assert stream.read_bytes() == b"protected auxiliary stream"
    assert security_digest(source) == original_security


def test_windows_readonly_not_silently_changed(media, tmp_path):
    import os

    if os.name != "nt":
        pytest.skip("Windows file attribute test")
    root, make = media
    source = make()
    source.chmod(0o444)
    try:
        baseline = inventory(source, root)
        before = digest(source)
        with pytest.raises(PermissionError, match="Readonly"):
            update_one(source, {"Tempo": "Fast"}, baseline, tmp_path / "backups", root)
        assert digest(source) == before
    finally:
        source.chmod(0o666)


def test_empty_trailing_space_directory_has_positive_coverage_check(media):
    import os

    if os.name != "nt":
        pytest.skip("Windows noncanonical name test")
    from pathlib import Path
    from src.core.tag_inventory import library_audio_paths

    root, _ = media
    wide = Path("\\\\?\\" + str(root / "empty-directory "))
    wide.mkdir()
    child = wide / "unexpected.flac"
    try:
        errors, notes = [], []
        assert list(library_audio_paths(root, errors, notes)) == []
        assert errors == [] and len(notes) == 1
        child.write_bytes(b"fixture")
        errors, notes = [], []
        assert list(library_audio_paths(root, errors, notes)) == []
        assert (
            len(errors) == 1 and notes == []
        )  # Never fake a nonempty directory as empty.
    finally:
        if child.exists():
            child.unlink()
        wide.rmdir()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/test",
        "http://127.0.0.1/test",
        "http://192.168.1.1/test",
        "https://host.internal/test",
        "https://fixture:fixture@example.org/test",
        "file:///example",
    ],
)
def test_nonpublic_or_authenticated_evidence_not_eligible(url):
    from src.core.tag_writer import public_source_url

    assert not public_source_url(url)
