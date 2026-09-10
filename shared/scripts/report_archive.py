#!/usr/bin/env python3
"""Bounded Windows Markdown archive: validate to a snapshot, then commit it.

No shell hooks, automatic privilege changes, automatic rollback, or POSIX claims.
Cooperative writers share an exclusive lock. Non-cooperating writers can race the
last check and rename: conflicts preserve recovery evidence, never blind rollback.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path

SKILLS = {"hit-weekly-brief": "validate_weekly_brief", "hit-lectures-scout": "validate_lectures_scout",
          "hit-industry-radar": "validate_industry_radar"}
MAX_BYTES = 8 * 1024 * 1024


class Blocked(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def backend():
    if os.name != "nt":
        raise Blocked("CAPABILITY", "POSIX owner/ACL fidelity is not implemented")
    try:
        import report_archive_windows
    except ImportError as exc:
        raise Blocked("CAPABILITY", f"installed Windows bindings unavailable: {exc}") from exc
    return report_archive_windows


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exact_path(value: str | Path, *, missing: bool = False) -> Path:
    path = Path(os.path.abspath(value))
    if str(path).startswith("\\\\") or ":" in str(path)[2:]:
        raise Blocked("INPUT", "only local non-stream paths supported")
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if part == path and missing:
                continue
            raise Blocked("INPUT", f"path ancestor missing: {part}") from None
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Blocked("INPUT", f"symlink/reparse path forbidden: {part}")
        if part.name.endswith((".", " ")):
            raise Blocked("INPUT", "Windows normalized name alias forbidden")
    if path.is_file() and path.stat().st_nlink != 1:
        raise Blocked("INPUT", "hardlinked report forbidden")
    return path


def read_source(path: Path) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise Blocked("INPUT", "source must be a regular Markdown file <=8 MiB")
        data = path.read_bytes()
        text = data.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise Blocked("SOURCE_IO", str(exc)) from exc
    if not text.strip() or "\ufffd" in text or path.suffix.lower() != ".md":
        raise Blocked("INPUT", "source must be nonempty intact UTF-8 Markdown")
    return data


def identity(path: Path, skill: str, *, validate: bool, custom_filename: bool,
             custom_period: bool, target_name: str) -> dict:
    if skill not in SKILLS:
        raise Blocked("INPUT", "skill not whitelisted")
    if skill == "hit-industry-radar" and custom_period:
        raise Blocked("INPUT", "--allow-custom-period is weekly-only; radar uses 窗口模式")
    script = Path(__file__).resolve().parents[2] / skill / "scripts" / (SKILLS[skill] + ".py")
    spec = importlib.util.spec_from_file_location(SKILLS[skill], script)
    if spec is None or spec.loader is None:
        raise Blocked("CAPABILITY", "validator unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        if skill == "hit-industry-radar" and not all(callable(getattr(module, name, None))
                for name in ("metadata", "canonical_title", "validate_report", "parse_date", "ZoneInfo")):
            raise Blocked("CAPABILITY", "radar validator interface unavailable")
    except (OSError, ImportError, SyntaxError) as exc:
        if skill != "hit-industry-radar":
            raise
        raise Blocked("CAPABILITY", f"radar validator unavailable: {exc}") from exc
    text = read_source(path).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    try:
        start, end = module.metadata(text, "报告周期").split(" 至 ")
        issue = module.metadata(text, "出刊日期")
        cutoff = datetime.fromisoformat(module.metadata(text, "生成时点"))
        zone = module.metadata(text, "报告时区")
        arguments = dict(file_path=path, period_start=date.fromisoformat(start),
            period_end=date.fromisoformat(end), issue_date=date.fromisoformat(issue), cutoff=cutoff,
            report_timezone=zone, allow_custom_filename=True)
        if skill == "hit-industry-radar":
            window_mode = module.metadata(text, "窗口模式")
        else:
            window_mode = module.metadata(text, "命名依据") if skill == "hit-lectures-scout" else None
        if window_mode is not None:
            arguments["window_mode"] = window_mode
        else:
            arguments["allow_custom_period"] = custom_period
        # Derive report type from its own canonical title/naming fields even
        # for existing targets; a custom filename is not a skill identity.
        heading = next((line.strip() for line in text.splitlines() if line.strip().startswith("# ")), "")
        if skill == "hit-weekly-brief":
            expected_title = module.canonical_title(arguments["period_start"], arguments["period_end"])
            if re.search(r"^命名依据：", text.split("\n## ", 1)[0], re.M):
                raise ValueError("weekly identity must not contain scout naming metadata")
            if arguments["issue_date"] != arguments["period_end"]:
                raise ValueError("weekly issue identity must equal period end")
        elif skill == "hit-industry-radar":
            expected_title = module.canonical_title(arguments["period_start"], arguments["period_end"])
            scope = module.metadata(text, "报告范围").strip()
            status = module.metadata(text, "检索状态")
            if not scope or status not in {"complete", "partial", "blocked"}:
                raise ValueError("invalid radar scope/search status")
            if validate and status == "blocked":
                raise ValueError("blocked retrieval is diagnostic only, not an archive source")
            if re.search(r"^命名依据：", text.split("\n## ", 1)[0], re.M):
                raise ValueError("radar identity must not contain scout naming metadata")
            if window_mode not in {"rolling7", "natural_week", "explicit"} or cutoff.utcoffset() is None:
                raise ValueError("invalid radar window identity")
            try:
                module.ZoneInfo(zone)
            except (KeyError, ValueError) as exc:
                raise ValueError("radar report timezone unavailable or invalid") from exc
            if (module.parse_date(start) > module.parse_date(end)
                    or module.parse_date(issue) != arguments["period_end"]):
                raise ValueError("radar issue identity must equal valid period end")
        else:
            expected_title = f"# 医疗数字化文献侦察报告 - {issue}"
            if window_mode not in {"explicit", "generated"} or cutoff.utcoffset() is None:
                raise ValueError("invalid scout naming identity")
            expected_issue = (arguments["period_end"] if window_mode == "explicit" else
                              cutoff.astimezone(module.ZoneInfo(zone)).date())
            if arguments["issue_date"] != expected_issue:
                raise ValueError("scout issue identity does not match naming mode")
        if heading != expected_title:
            raise ValueError("skill-specific canonical title identity mismatch; review legacy metadata manually")
        prefix = {"hit-weekly-brief": "DHWB", "hit-lectures-scout": "DHLS",
                  "hit-industry-radar": "DHWB-Radar"}[skill]
        expected_name = f"{prefix}-{date.fromisoformat(issue):%Y%m%d}.md"
        if not custom_filename and target_name != expected_name:
            raise ValueError(f"target filename must be {expected_name}")
        if validate:
            errors = module.validate_report(**arguments)
            if errors:
                raise ValueError("; ".join(errors))
    except (ValueError, TypeError, KeyError) as exc:
        raise Blocked("INPUT", f"report identity/validation: {exc}") from exc
    result = dict(skill=skill, period_start=start, period_end=end, issue_date=issue, window_mode=window_mode)
    if skill == "hit-industry-radar":
        # Timezone affects cutoff calendar dates; even custom names cannot merge it.
        result.update(scope=scope, report_timezone=zone)
    return result


def snapshot(path: Path, security) -> dict | None:
    exact_path(path, missing=True)
    if not path.exists():
        return None
    info = path.stat()
    data = read_source(path)
    return {"sha256": digest(data), "size": len(data), "file_id": [info.st_dev, info.st_ino],
            "mtime_ns": info.st_mtime_ns, "security": security.descriptor(path)}


def parent_snapshot(path: Path, security) -> dict:
    exact_path(path)
    info = path.stat()
    return {"file_id": [info.st_dev, info.st_ino], "security": security.descriptor(path)}


def validate(source: Path, target: Path, allow_target: Path, skill: str,
             custom_filename: bool = False, custom_period: bool = False) -> dict:
    security = backend()
    try:
        source = exact_path(source)
    except OSError as exc:
        raise Blocked("SOURCE_IO", str(exc)) from exc
    target = exact_path(target, missing=True)
    allowed = exact_path(allow_target, missing=True)
    if target != allowed or target == source or (target.exists() and os.path.samefile(source, target)):
        raise Blocked("INPUT", "target must equal exact caller whitelist and differ from source")
    if target.suffix.lower() != ".md" or not target.parent.is_dir():
        raise Blocked("INPUT", "target must be Markdown in an existing directory")
    ident = identity(source, skill, validate=True, custom_filename=custom_filename,
                     custom_period=custom_period, target_name=target.name)
    old = snapshot(target, security)
    if old is not None:
        try:
            original_identity = identity(target, skill, validate=False, custom_filename=custom_filename,
                                         custom_period=custom_period, target_name=target.name)
        except Blocked as exc:
            raise Blocked("COLLISION", f"existing identity requires manual review: {exc}") from exc
        if original_identity != ident:
            raise Blocked("COLLISION", "existing target has different semantic identity")
        security.effective_access(target, read_source(target))
    return {"schema": 1, "source": str(source), "target": str(target), "identity": ident,
            "source_sha256": digest(read_source(source)), "expected_target": old,
            "expected_parent": parent_snapshot(target.parent, security),
            "custom_filename": custom_filename, "custom_period": custom_period}


def write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def commit(plan: dict, allow_target: Path) -> dict:
    """Retain original + journal on replacement/failure; no destructive recovery."""
    receipt = {"status": "BLOCKED", "code": "INPUT", "target": plan.get("target"),
               "sha256": plan.get("source_sha256"), "security": None,
               "rollback": "not_started", "recovery_directory": None}
    stage = None
    lock = None
    lock_fd = None
    committed = False
    phase = "precommit"
    try:
        required = {"schema", "source", "target", "identity", "source_sha256", "expected_target",
                    "expected_parent", "custom_filename", "custom_period"}
        if set(plan) != required or plan["schema"] != 1 or not isinstance(plan["identity"], dict):
            raise Blocked("INPUT", "malformed validation snapshot")
        if type(plan["custom_filename"]) is not bool or type(plan["custom_period"]) is not bool:
            raise Blocked("INPUT", "custom flags must be booleans")
        security = backend()
        target = exact_path(plan["target"], missing=True)
        if target != exact_path(allow_target, missing=True):
            raise Blocked("INPUT", "commit target differs from exact whitelist")
        source = exact_path(plan["source"])
        lock = target.parent / (".report-archive-" + digest(target.name.lower().encode())[:24] + ".lock")
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise Blocked("COLLISION", "cooperative writer lock exists; no automatic stale-lock removal") from exc
        refreshed = validate(source, target, allow_target, plan["identity"]["skill"],
                             plan["custom_filename"], plan["custom_period"])
        if refreshed != plan:
            raise Blocked("COLLISION", "content, identity, source, or security snapshot drift")
        data = read_source(source)
        stage = target.parent / (".report-archive-" + uuid.uuid4().hex)
        # Windows mkdir777 inherits the confirmed parent, unlike private mkdtemp700.
        stage.mkdir(mode=0o777)
        receipt["recovery_directory"] = str(stage)
        # An immediate-child FILE gets the parent's one-generation ACEs;
        # a file inside stage would incorrectly inherit as a grandchild.
        candidate = target.parent / (stage.name + ".candidate.md")
        original = stage / "original.md"
        journal = {"plan": plan, "candidate_sha256": digest(data), "candidate": str(candidate),
                   "original": str(original) if plan["expected_target"] is not None else None,
                   "recovery": "inspect exact state; validate a fresh recovery plan; never blind overwrite"}
        write_exclusive(stage / "journal.json", json.dumps(journal, ensure_ascii=False, indent=2).encode("utf-8"))
        write_exclusive(candidate, b"")
        policy = (plan["expected_target"]["security"] if plan["expected_target"] is not None
                  else security.parent_owner_policy(target.parent, candidate))
        security.apply(candidate, policy)  # final owner/group/DACL before report bytes
        with candidate.open("r+b") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        access = security.effective_access(candidate, data)
        if plan["expected_target"] is not None:
            write_exclusive(original, b"")
            security.apply(original, policy)
            with original.open("r+b") as handle:
                handle.write(read_source(target))
                handle.flush()
                os.fsync(handle.fileno())
            if digest(original.read_bytes()) != plan["expected_target"]["sha256"]:
                raise Blocked("COLLISION", "original drift while backing up")
        if (snapshot(target, security) != plan["expected_target"]
                or parent_snapshot(target.parent, security) != plan["expected_parent"]
                or digest(read_source(source)) != plan["source_sha256"]):
            raise Blocked("COLLISION", "precommit drift; original and candidate retained")
        phase = "rename"
        if plan["expected_target"] is None:
            os.rename(candidate, target)  # Windows atomic no-replace
        else:
            os.replace(candidate, target)  # staged owner/group/DACL, not ReplaceFile merge semantics
        committed = True
        phase = "postcommit"
        receipt["rollback"] = "original_retained" if original.exists() else "new_file_no_original"
        final = snapshot(target, security)
        if final is None or final["sha256"] != digest(data) or final["security"] != policy:
            raise Blocked("POSTCOMMIT", "published content/security mismatch; target NOT rolled back")
        access = security.effective_access(target, data)
        if snapshot(target, security) != final or parent_snapshot(target.parent, security) != plan["expected_parent"]:
            raise Blocked("POSTCOMMIT", "postverification drift; target NOT rolled back")
        receipt.update(status="COMMITTED", code="OK", security={"descriptor": policy, **access},
                       target=str(target), sha256=final["sha256"])
    except (Blocked, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        receipt["code"] = ("POSTCOMMIT" if committed or phase == "rename" else
                           exc.code if isinstance(exc, Blocked) else "ACCESS_CHECK")
        receipt["detail"] = str(exc)
        receipt["rollback"] = ("not_attempted_preserve_evidence" if stage is not None else "not_started")
    finally:
        if lock_fd is not None and lock is not None:
            os.close(lock_fd)
            try:
                lock.unlink()
            except OSError as exc:
                receipt.update(status="BLOCKED", code="COLLISION", detail=f"lock cleanup failed: {exc}")
    return receipt


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate", help="read-only dry-run; stdout is the expected snapshot")
    check.add_argument("--source", required=True, type=Path)
    check.add_argument("--target", required=True, type=Path)
    check.add_argument("--allow-target", required=True, type=Path)
    check.add_argument("--skill", required=True, choices=SKILLS)
    check.add_argument("--allow-custom-filename", action="store_true")
    check.add_argument("--allow-custom-period", action="store_true")
    publish = commands.add_parser("commit")
    publish.add_argument("--plan", required=True, type=Path)
    publish.add_argument("--allow-target", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validate(args.source, args.target, args.allow_target, args.skill,
                              args.allow_custom_filename, args.allow_custom_period)
        else:
            plan = json.loads(args.plan.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
            if not isinstance(plan, dict):
                raise ValueError("plan must be a JSON object")
            result = commit(plan, args.allow_target)
    except (Blocked, OSError, RuntimeError, ValueError, TypeError) as exc:
        result = {"status": "BLOCKED", "code": exc.code if isinstance(exc, Blocked) else "INPUT",
                  "detail": str(exc), "rollback": "not_started"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
