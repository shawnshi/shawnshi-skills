"""Prepare research jobs and apply reviewed results. No external API or player calls."""

import argparse
from contextlib import contextmanager
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.core.local_paths import local_path, local_regular_file
from src.core.tag_inventory import (
    COLS,
    FIELDS,
    VALID,
    codec,
    inventory,
    library_audio_paths,
    read_json,
    scan_paths,
    values,
    write_inventory,
)


def task_manifest(work_dir):
    work = local_path(Path(work_dir).absolute())
    manifest = read_json(work / "manifest.json")
    summary = read_json(work / "summary.json")
    actual = hashlib.sha256((work / "manifest.json").read_bytes()).hexdigest()
    if actual != summary["manifest_sha256"]:
        raise ValueError(
            "Task manifest changed; re-inventory instead of accepting stale research"
        )
    records = manifest["records"]
    if manifest.get("schema_version") != 1 or len({r["path"] for r in records}) != len(
        records
    ):
        raise ValueError("Invalid manifest schema/duplicate recording path")
    local_path(Path(manifest["library_root"]))
    return work, manifest


@contextmanager
def task_plan_lock(work_dir, timeout=10.0):
    lock_file = Path(work_dir) / ".jobs.lock"
    started = time.monotonic()
    token = uuid.uuid4().hex
    while True:
        try:
            fd = os.open(lock_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as h:
                h.write(token)
                h.flush()
                os.fsync(h.fileno())
            break
        except (FileExistsError, OSError):
            if time.monotonic() - started >= timeout:
                raise TimeoutError("Timeout waiting for task plan lock")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            if lock_file.is_file() and lock_file.read_text(encoding="ascii") == token:
                lock_file.unlink()
        except OSError:
            pass


def prepare_jobs(work_dir, batch_size=10, max_concurrency=1):
    if type(batch_size) is not int or not 1 <= batch_size <= 25:
        raise ValueError("Research batches must contain 1-25 tracks")
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 5:
        raise ValueError("Concurrency must be 1-5")
    work, manifest = task_manifest(work_dir)
    if (work / "jobs.json").exists():
        raise ValueError("Existing plan must not be overwritten")
    agent_source = Path(__file__).resolve().parent.parent / "templates" / "musicbee-tags.md"
    agent_data = local_regular_file(agent_source).read_bytes()
    agent_dir = work / ".pi" / "agents"
    agent_dir.mkdir(parents=True, exist_ok=False)
    (agent_dir / "musicbee-tags.md").write_bytes(agent_data)
    schema = {"fields": FIELDS, "enums": {field: sorted(VALID[field]) for field in FIELDS},
              "requested_fields": sorted({field for record in manifest['records']
                                          for field in record.get('requested_fields', FIELDS)}),
              "subjective_fields": ["mood", "DJ_ENERGY", "DJ_SCENE"],
              "tempo_bpm_thresholds": [60, 90, 120, 160]}
    schema_data = json.dumps(schema, ensure_ascii=False, sort_keys=True).encode("utf-8")
    (work / "tag-schema.json").write_bytes(schema_data)
    (work / "batches").mkdir(exist_ok=False)
    jobs = []
    records = manifest["records"]
    for start in range(0, len(records), batch_size):
        chunk = records[start : start + batch_size]
        key = f"batch-{len(jobs) + 1:04d}"
        folder = work / "batches" / key
        folder.mkdir()
        with (folder / "input.csv").open("w", encoding="utf-8-sig", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=COLS)
            writer.writeheader()
            writer.writerows(r["row"] for r in chunk)
        jobs.append(
            {
                "key": key,
                "cwd": str(folder),
                "input": str(folder / "input.csv"),
                "count": len(chunk),
                "paths": [r["path"] for r in chunk],
                "state": "pending",
            }
        )
    from src.core.tag_writer import save_json

    save_json(
        work / "jobs.json",
        {
            "schema_version": 1,
            "concurrency": max_concurrency,
            "agent_sha256": hashlib.sha256(agent_data).hexdigest(),
            "schema_sha256": hashlib.sha256(schema_data).hexdigest(),
            "batch_size": batch_size,
            "jobs": jobs,
            "blocked": False,
        },
    )
    return {
        "batches": len(jobs),
        "tracks": len(records),
        "batch_size": batch_size,
        "concurrency": max_concurrency,
    }


def next_jobs(work_dir, count=1):
    work, _ = task_manifest(work_dir)
    with task_plan_lock(work):
        plan = read_json(work / "jobs.json")
        if plan.get("blocked"):
            raise ValueError("Research lane blocked: " + plan.get("blocker", "unknown"))
        max_allowed = plan.get("concurrency", 1)
        if max_allowed == 1 and count != 1:
            raise ValueError("Research is serial until worktree/container isolation is authorized")
        if type(count) is not int or not 1 <= count <= 5:
            raise ValueError("Requested count must be 1-5")
        if count > max_allowed:
            raise ValueError(f"Requested count ({count}) exceeds plan concurrency ({max_allowed})")
        running = sum(1 for j in plan["jobs"] if j["state"] == "running")
        if running:
            return []
        slots = max_allowed
        selected = [j for j in plan["jobs"] if j["state"] == "pending"][:min(count, slots)]
        for job in selected:
            batch_context(
                work, job["key"]
            )  # Check scope/CSV before sending any identities to a child.
        return [{**{k: j[k] for k in ("key", "cwd", "input", "count")},
                 "schema": str(work / "tag-schema.json")} for j in selected]


def mark_job(work_dir, batch, state, reason=""):
    work, _ = task_manifest(work_dir)
    with task_plan_lock(work):
        plan = read_json(work / "jobs.json")
        matches = [j for j in plan["jobs"] if j["key"] == batch]
        if len(matches) != 1 or state not in {"running", "blocked"}:
            raise ValueError("Invalid job/state")
        if state == "running" and (plan.get("blocked") or matches[0]["state"] != "pending"):
            raise ValueError("Already claimed or blocked job")
        matches[0]["state"] = state
        if state == "blocked":
            if not reason:
                raise ValueError("Blocked jobs require observable failure evidence")
            plan.update(blocked=True, blocker=reason)
        from src.core.tag_writer import save_json

        save_json(work / "jobs.json", plan)
        return {"batch": batch, "state": state, "blocked": plan["blocked"]}


def batch_context(work_dir, batch):
    work, manifest = task_manifest(work_dir)
    plan = read_json(work / "jobs.json")
    for relative, key in ((".pi/agents/musicbee-tags.md", "agent_sha256"),
                          ("tag-schema.json", "schema_sha256")):
        payload = local_regular_file(work / relative).read_bytes()
        if hashlib.sha256(payload).hexdigest() != plan.get(key):
            raise ValueError("Research role/schema changed; prepare a new task")
    matches = [j for j in plan["jobs"] if j["key"] == batch]
    if len(matches) != 1:
        raise ValueError("Unknown batch key")
    job = matches[0]
    folder = local_path(Path(job["cwd"]))
    if folder != work / "batches" / batch:
        raise ValueError("Out-of-task batch directory denied")
    records = {
        r["path"]: r for r in manifest["records"] if r["path"] in set(job["paths"])
    }
    if set(records) != set(job["paths"]) or len(records) != job["count"]:
        raise ValueError("Batch membership drift")
    with Path(job["input"]).open(encoding="utf-8-sig", newline="") as h:
        actual = list(csv.DictReader(h))
    if actual != [records[path]["row"] for path in job["paths"]]:
        raise ValueError("Batch input CSV changed")
    return work, manifest, plan, job, folder, records


def result_snapshot(path):
    path = local_regular_file(Path(path).absolute())
    if path.stat().st_size > 2 * 1024**2:
        raise ValueError("Oversized research result; use the bounded batch schema")
    data = path.read_bytes()
    try:
        result = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid UTF-8 research JSON") from error
    return data, result


def import_result(work_dir, batch, result_path):
    from src.core.tag_writer import validate_results, save_json

    work, _, plan, job, folder, records = batch_context(work_dir, batch)
    if plan.get("blocked") or job["state"] not in {"pending", "running"}:
        raise ValueError("Failed/already accepted research cannot be imported")
    data, result = result_snapshot(result_path)
    # Validate the same immutable byte snapshot whose checksum is pinned.
    changes = validate_results(result, records)
    destination = folder / "result.json"
    if destination.exists():
        raise ValueError("Existing accepted result must not be overwritten")
    destination.write_bytes(data)
    checksum = hashlib.sha256(data).hexdigest()
    job.update(state="researched", result_sha256=checksum)
    save_json(work / "jobs.json", plan)
    summary = {
        "batch": batch,
        "rows": len(records),
        "eligible_files": sum(bool(v) for v in changes.values()),
        "eligible_fields": sum(len(v) for v in changes.values()),
        "result_sha256": checksum,
        "schema_checked": True,
        "source_semantics_checked": False,
    }
    save_json(folder / "research_summary.json", summary)
    return summary


def reviewed_updates(work, job, records):
    from src.core.tag_writer import validate_review
    folder = Path(job["cwd"])
    data, result = result_snapshot(folder / "result.json")
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != job.get("result_sha256"):
        raise ValueError("Accepted research SHA256 changed")
    if not job.get("review_sha256"):
        raise ValueError("Parent review missing; perform source/recording checks before applying")
    review_data, review = result_snapshot(folder / "review.json")
    if hashlib.sha256(review_data).hexdigest() != job.get("review_sha256"): 
        raise ValueError("Parent review missing or changed")
    return validate_review(result, records, review, checksum)


def review_batch(work_dir, batch, reviewed_sha256, review_path, expected_review_sha256=None):
    from src.core.tag_writer import validate_review, save_json
    work, _, plan, job, folder, records = batch_context(work_dir, batch)
    data, result = result_snapshot(folder / "result.json")
    checksum = hashlib.sha256(data).hexdigest()
    if (plan.get("blocked") or job["state"] != "researched"
        or checksum != job.get("result_sha256") or checksum != reviewed_sha256):
        raise ValueError("Review requires accepted research and its exact SHA256")
    review_data, review = result_snapshot(review_path)
    if expected_review_sha256 is not None and hashlib.sha256(review_data).hexdigest() != expected_review_sha256:
        raise ValueError("Parent review changed before acceptance")
    updates = validate_review(result, records, review, checksum)
    destination = folder / "review.json"
    if destination.exists():
        raise ValueError("Existing parent review must not be overwritten")
    destination.write_bytes(review_data)
    job["review_sha256"] = hashlib.sha256(review_data).hexdigest()
    save_json(work / "jobs.json", plan)
    summary = {"result_sha256": checksum, "review_sha256": job["review_sha256"],
               "source_semantics_checked": True, "verification_kind": "parent_attestation",
               "approved_fields": sum(len(update) for update in updates.values()),
               "run_reference": review["run_reference"]}
    save_json(folder / "review_summary.json", summary)
    return summary


def apply_batch(work_dir, batch, reviewed_sha256, limit=5):
    from src.core.tag_writer import (
        digest,
        library_lock,
        save_json,
        update_one,
    )

    work, manifest, plan, job, folder, records = batch_context(work_dir, batch)
    if plan.get("blocked"):
        raise ValueError("Blocked research task cannot write music files")
    result = folder / "result.json"
    data, _ = result_snapshot(result)
    actual = hashlib.sha256(data).hexdigest()
    if (
        job["state"] != "researched"
        or actual != job.get("result_sha256")
        or actual != reviewed_sha256
    ):
        raise ValueError("Apply requires the exact parent-reviewed result SHA256")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("Serial commits are limited to 1-5 files per call")
    changes = reviewed_updates(work, job, records)
    backups = work / "backups"
    started = time.monotonic()
    deadline = started + 160
    applied = []
    with library_lock(manifest["library_root"]):
        for path, update in changes.items():
            if not update:
                continue
            receipt_path = backups / (
                hashlib.sha256(path.encode("utf-8")).hexdigest() + ".json"
            )
            if receipt_path.exists():
                receipt = read_json(receipt_path)
                if (
                    receipt.get("status") == "committed"
                    and digest(Path(path)) == receipt["after_sha256"]
                ):
                    continue
                raise ValueError(
                    "Existing recovery point needs reconciliation; refusing blind retry"
                )
            if len(applied) >= limit or time.monotonic() - started >= 120:
                break
            if records[path]["size"] > 2 * 1024**3:
                raise ValueError(
                    "File above 2 GiB requires a separately bounded commit"
                )
            applied.append(
                update_one(
                    Path(path), update, records[path], backups, manifest["library_root"], deadline=deadline
                )
            )
    summary = {
        "batch": batch,
        "applied_files": len(applied),
        "applied_fields": sum(len(r["changes"]) for r in applied),
        "seconds": round(time.monotonic() - started, 2),
        "deadline_seconds": 160,
        "deadline_policy": "cooperative_checks; host_180s_timeout_required_for_blocking_IO",
        "eligible_files": sum(bool(v) for v in changes.values()),
        "atomic_commits": True,
        "payload_and_non_target_metadata_verified": True,
    }
    save_json(folder / "apply_summary.json", summary)
    return summary


def verify_task(work_dir, batch=None):
    from src.core.tag_writer import digest, save_json

    work, manifest = task_manifest(work_dir)
    plan = read_json(work / "jobs.json")
    jobs = plan["jobs"]
    records_to_check = manifest["records"]
    if batch is not None:
        _, _, _, job, _, batch_records = batch_context(work, batch)
        jobs = [job]
        records_to_check = list(batch_records.values())
    allowed = {record["path"] for record in records_to_check}
    receipts = list((work / "backups").glob("*.json"))
    verified, failures = 0, []
    for file in receipts:
        receipt = read_json(file)
        if batch is not None and receipt.get("path") not in allowed:
            continue
        if receipt.get("status") != "committed":
            failures.append({"receipt": file.name, "reason": "not committed"})
            continue
        source = Path(receipt["path"])
        if str(source) not in allowed:
            raise ValueError("Receipt outside frozen task write-set")
        actual = inventory(source, manifest["library_root"])
        current_hash = digest(source)
        hash_matched = (current_hash == receipt.get("after_sha256"))
        if not hash_matched or any(
            values(actual["tags"], k) != [v] for k, v in receipt["changes"].items()
        ):
            failures.append(
                {"file": str(source), "reason": "post-write drift/readback mismatch"}
            )
        else:
            verified += 1
    records, errors = scan_paths(
        [r["path"] for r in records_to_check], manifest["library_root"]
    )
    baselines = {r["path"]: r for r in records_to_check}
    actual_records = {r["path"]: r for r in records}
    remaining = [record for record in records if set(record['needs']) &
                 set(baselines[record['path']].get('requested_fields', FIELDS))]
    unapplied = []
    research_reconciled = not plan.get("blocked")
    for job in jobs:
        if job["state"] != "researched" or not job.get("review_sha256"):
            research_reconciled = False
            continue
        result = Path(job["cwd"]) / "result.json"
        if digest(result) != job["result_sha256"]:
            raise ValueError("Accepted research changed before verification")
        updates = reviewed_updates(work, job, {path: baselines[path] for path in job["paths"]})
        for path, changes in updates.items():
            actual = actual_records.get(path)
            receipt_file = work / "backups" / (hashlib.sha256(path.encode("utf-8")).hexdigest() + ".json")
            if changes and (not receipt_file.exists() or actual is None or any(
                values(actual["tags"], field) != [value] for field, value in changes.items()
            )):
                unapplied.append(path)
    research_reconciled = research_reconciled and not unapplied and not errors
    report_folder = work if batch is None else work / "batches" / batch
    with (report_folder / "remaining_tags.csv").open("w", encoding="utf-8-sig", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=COLS)
        writer.writeheader()
        writer.writerows(r["row"] for r in remaining)
    summary = {
        "verification_scope": batch or "task",
        "verified_commits": verified,
        "receipt_failures": len(failures),
        "failure_samples": failures[:5],
        "remaining_incomplete_files": len(remaining),
        "completion_scope": "requested_fields; not necessarily all six tags",
        "read_errors": len(errors),
        "initial_read_errors": sum(
            e.get("scope") != "library_entry" for e in manifest["errors"]
        ),
        "initial_unreadable_library_entries": sum(
            e.get("scope") == "library_entry" for e in manifest["errors"]
        ),
        "research_reconciled": research_reconciled,
        "unapplied_files": len(unapplied),
        "full_task_complete": batch is None and research_reconciled and not failures
        and not remaining
        and not errors
        and not manifest["errors"],
        "all_checked_commits_valid": not failures and not errors,
        "remaining_csv_sha256": digest(report_folder / "remaining_tags.csv"),
        "player_refresh_hint": (
            "In MusicBee, select updated tracks and press Shift+F5 or right-click 'Rescan Files' to update library UI from disk tags."
            if verified > 0
            else "No new file commits verified."
        ),
    }
    save_json(report_folder / "verification_summary.json", summary)
    return summary


def auto_commit_batch(work_dir, batch, result_path, run_reference, review_path):
    from src.core.tag_writer import validate_results, validate_review

    if not isinstance(run_reference, str) or not run_reference.strip():
        raise ValueError("A successful settled research run reference is required")
    work, _, plan, job, folder, records = batch_context(work_dir, batch)
    data, result = result_snapshot(result_path)
    incoming_sha256 = hashlib.sha256(data).hexdigest()
    review_data, review = result_snapshot(review_path)
    review_sha256 = hashlib.sha256(review_data).hexdigest()
    approved = validate_review(result, records, review, incoming_sha256)
    if review["run_reference"] != run_reference:
        raise ValueError("Parent review run reference does not match")
    changes = validate_results(result, records)
    if job["state"] in {"pending", "running"}:
        import_summary = import_result(work_dir, batch, result_path)
        checksum = import_summary["result_sha256"]
    elif job["state"] == "researched":
        checksum = job["result_sha256"]
        import_summary = read_json(folder / "research_summary.json")
    else:
        raise ValueError(f"Job {batch} in unresumable state: {job['state']}")

    if incoming_sha256 != checksum:
        raise ValueError("Accepted research SHA256 changed during automatic resume")
    if (folder / "review.json").exists() and job.get("review_sha256"):
        if review_sha256 != job["review_sha256"]:
            raise ValueError("Parent review changed during automatic resume")
        reviewed_updates(work, job, records)
        review_summary = read_json(folder / "review_summary.json")
    else:
        review_summary = review_batch(work_dir, batch, checksum, review_path,
                                      expected_review_sha256=review_sha256)
    # One invocation has the same physical write budget as one apply call.
    apply_res = apply_batch(work_dir, batch, checksum, limit=5)
    verify_summary = verify_task(work_dir, batch=batch)
    if not verify_summary["all_checked_commits_valid"]:
        raise ValueError("Automatic verification failed: " + json.dumps(verify_summary["failure_samples"], ensure_ascii=False))
    return {
        "batch": batch,
        "status": "auto_committed" if verify_summary["research_reconciled"] else "applying",
        "eligible_files": import_summary["eligible_files"],
        "eligible_fields": import_summary["eligible_fields"],
        "approved_fields": review_summary["approved_fields"],
        "rejected_fields": sum(len(fields) for fields in changes.values()) - sum(len(fields) for fields in approved.values()),
        "applied_files": apply_res["applied_files"],
        "applied_fields": apply_res["applied_fields"],
        "verified_commits": verify_summary["verified_commits"],
        "receipt_failures": verify_summary["receipt_failures"],
        "all_checked_commits_valid": verify_summary["all_checked_commits_valid"],
        "player_refresh_hint": verify_summary.get("player_refresh_hint", ""),
    }


def inspect_recovery(work_dir, receipt_path):
    from src.core.tag_writer import digest
    work, manifest = task_manifest(work_dir)
    receipt_path = local_regular_file(Path(receipt_path).absolute())
    if receipt_path.parent != work / "backups":
        raise ValueError("Recovery receipt outside this task")
    receipt = read_json(receipt_path)
    source = local_regular_file(Path(receipt["path"]))
    allowed = {record["path"] for record in manifest["records"]}
    key = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
    if str(source) not in allowed or receipt_path.name != key + ".json":
        raise ValueError("Recovery receipt outside frozen write-set")
    header = local_regular_file(receipt_path.with_suffix(".header"))
    deadline = time.monotonic() + 30
    lock = Path(manifest["library_root"]) / ".musicbee-dj-tag-writer.lock"
    if lock.exists():
        return {"receipt_status": receipt["status"], "observed_state": "writer_lock_present",
                "recovery_header_verified": False, "music_files_modified": False,
                "next_action": "Determine the lock owner's actual run state; do not guess or delete the lock"}
    if digest(header, deadline=deadline) != receipt["header_sha256"]:
        raise ValueError("Recovery header checksum mismatch")
    before = source.stat()
    actual = digest(source, deadline=deadline)
    after = source.stat()
    if lock.exists() or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Concurrent change during recovery inspection")
    observed = ("original_unchanged" if actual == receipt["before_sha256"] else
                "replacement_present" if actual == receipt.get("after_sha256") else "drifted")
    return {"receipt_status": receipt["status"], "observed_state": observed,
            "recovery_header_verified": True, "music_files_modified": False,
            "next_action": "Owner must reconcile/authorize the exact receipt; never delete a stale lock or retry blindly"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("--library-root", type=Path, required=True)
    scan.add_argument("--output-dir", type=Path, required=True)
    scan.add_argument("--paths-json", type=Path)
    scan.add_argument("--cache-file", type=Path)
    for name in ("plan", "next", "mark", "import-result", "review", "apply", "verify", "inspect-recovery", "auto-commit"):
        command = commands.add_parser(name)
        command.add_argument("--work-dir", type=Path, required=True)
        if name in ("mark", "import-result", "review", "apply", "auto-commit"):
            command.add_argument("--batch", required=True)
        if name == "inspect-recovery":
            command.add_argument("--receipt", type=Path, required=True)
        if name == "plan":
            command.add_argument("--batch-size", type=int, default=10)
            command.add_argument("--concurrency", type=int, default=1)
        if name == "next":
            command.add_argument("--count", type=int, default=1)
        if name == "mark":
            command.add_argument(
                "--state", choices=("running", "blocked"), required=True
            )
            command.add_argument("--reason", default="")
        if name in ("import-result", "auto-commit"):
            command.add_argument("--result", type=Path, required=True)
        if name == "auto-commit":
            command.add_argument("--run-reference", required=True)
            command.add_argument("--review-file", type=Path, required=True)
        if name in ("review", "apply"):
            command.add_argument("--reviewed-result-sha256", required=True)
        if name == "review":
            command.add_argument("--review-file", type=Path, required=True)
        if name == "apply":
            command.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    failure_types = (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AssertionError,
        ImportError,
    )
    try:
        module = codec()
        failure_types = failure_types + (module.MutagenError,)
        if args.command == "scan":
            root = local_path(args.library_root.absolute())
            traversal_errors, coverage_notes = [], []
            paths = (
                read_json(local_regular_file(args.paths_json.absolute()))["paths"]
                if args.paths_json
                else library_audio_paths(root, traversal_errors, coverage_notes)
            )
            cache = {}
            if args.cache_file and args.cache_file.exists():
                try:
                    cache_data = read_json(local_regular_file(args.cache_file.absolute()))
                    if isinstance(cache_data, dict):
                        cache = cache_data
                except Exception:
                    cache = {}
            records, errors = scan_paths(paths, root, cache=cache)
            if args.cache_file and cache:
                from src.core.tag_writer import save_json
                save_json(args.cache_file, cache)
            errors.extend(traversal_errors)
            result = write_inventory(
                args.output_dir, root, records, errors, coverage_notes
            )
        elif args.command == "plan":
            result = prepare_jobs(args.work_dir, args.batch_size, args.concurrency)
        elif args.command == "next":
            result = {"jobs": next_jobs(args.work_dir, args.count)}
        elif args.command == "mark":
            result = mark_job(args.work_dir, args.batch, args.state, args.reason)
        elif args.command == "import-result":
            result = import_result(args.work_dir, args.batch, args.result)
        elif args.command == "review":
            result = review_batch(args.work_dir, args.batch, args.reviewed_result_sha256, args.review_file)
        elif args.command == "apply":
            result = apply_batch(
                args.work_dir, args.batch, args.reviewed_result_sha256, args.limit
            )
        elif args.command == "inspect-recovery":
            result = inspect_recovery(args.work_dir, args.receipt)
        elif args.command == "auto-commit":
            result = auto_commit_batch(args.work_dir, args.batch, args.result, args.run_reference, args.review_file)
        else:
            result = verify_task(args.work_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except failure_types as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
