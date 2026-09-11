#!/usr/bin/env python3
"""Prepare a correctly named isolated draft; finalize metadata without approving it."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import init_workspace as init
import runtime_tx as tx
import validate_outputs as val
from draft_fields import render_strategy


def prepare(workspace: Path, parent: Path) -> Path:
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("正式工作区必须为普通目录。")
    workspace = workspace.resolve()
    manifest = tx.load_manifest(workspace)
    tx.verify_manifest_artifacts(workspace, manifest)
    if tx.unfinished_transaction(workspace):
        raise ValueError("请先恢复未完成事务。")
    candidate = parent.resolve() / workspace.name
    if candidate == workspace or workspace in candidate.parents or candidate.exists():
        raise ValueError("候选必须位于独立父目录且尚不存在。")
    # Copy only managed ordinary files, never an external link or transaction journal.
    selected = list(workspace.glob("*.md"))
    runtime = workspace / "runtime"
    selected += list(runtime.glob("*.json"))
    if runtime.is_symlink() or any(p.is_symlink() or not p.is_file() for p in selected):
        raise ValueError("拒绝链接或非普通文件。")
    candidate.mkdir(parents=True)
    try:
        for source in selected:
            target = candidate / source.relative_to(workspace)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (candidate / "runtime" / "candidate-base.json").write_text(
            json.dumps(
                {
                    "workspace": str(workspace),
                    "manifest_sha256": tx.sha256_bytes(
                        (workspace / tx.MANIFEST_REL).read_bytes()
                    ),
                    "transaction_sequence": manifest["transaction_sequence"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(candidate)
        raise
    return candidate


def finalize_letter_history(text: str, original_text: str, meta: dict[str, str]) -> str:
    """Render this draft run from formal history, never from a prior finalize."""

    def section(lines: list[str]) -> tuple[int, int]:
        headings = [
            i
            for i, line in enumerate(lines)
            if line.strip() == val.LETTER_REVIEW_HEADING
        ]
        if len(headings) != 1:
            raise ValueError("内部稿须保留唯一版本与审核记录章节。")
        start = headings[0]
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        return start, end

    original_lines = original_text.splitlines()
    start, end = section(original_lines)
    history = original_lines[start:end]
    rows = [
        (i, init.split_markdown_cells(line))
        for i, line in enumerate(history)
        if line.lstrip().startswith("|")
    ]
    current = [
        i for i, cells in rows if len(cells) == 6 and cells[2] == meta["latest_run_id"]
    ]
    if current:
        if len(current) != 1 or current[0] != rows[-1][0]:
            raise ValueError("只允许更新信件最后一条当前run草稿记录。")
        history[current[0]] = (
            "| "
            + " | ".join(
                init.markdown_cell(value)
                for value in (
                    meta["updated_at"],
                    meta["content_version"],
                    meta["latest_run_id"],
                    "生成待审核草稿",
                    meta["runtime_owner"],
                    meta["review_status"],
                )
            )
            + " |"
        )
    lines = text.splitlines()
    start, end = section(lines)
    lines[start:end] = history
    text = "\n".join(lines) + "\n"
    if not current:
        text = val.append_letter_review_record(
            text,
            timestamp=meta["updated_at"],
            version=meta["content_version"],
            run_id=meta["latest_run_id"],
            summary="生成待审核草稿",
            owner=meta["runtime_owner"],
            review_status=meta["review_status"],
        )
    return text


def finalize(workspace: Path, candidate: Path) -> dict:
    if (
        workspace.absolute() != workspace.resolve()
        or candidate.absolute() != candidate.resolve()
    ):
        raise ValueError("工作区路径不得含链接或重定向。")
    workspace, candidate = workspace.resolve(), candidate.resolve()
    if (
        candidate == workspace
        or workspace in candidate.parents
        or candidate.name != workspace.name
    ):
        raise ValueError("候选路径必须隔离且继承正式目录名。")
    base = json.loads(
        (candidate / "runtime/candidate-base.json").read_text(encoding="utf-8")
    )
    if base["workspace"] != str(workspace):
        raise ValueError("候选来源不匹配。")
    manifest = tx.assert_manifest_cas(
        workspace, base["transaction_sequence"], base["manifest_sha256"]
    )
    tx.verify_manifest_artifacts(workspace, manifest)
    now = init.now_utc().isoformat().replace("+00:00", "Z")
    paths = init.collect_artifact_paths(
        candidate,
        manifest["safe_name"]
        if "safe_name" in manifest
        else tx.parse_frontmatter(
            next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(
                encoding="utf-8"
            )
        )["safe_name"],
    )
    total_path = paths["comprehensive_report"]
    total = total_path.read_text(encoding="utf-8")
    selected = init.selected_callable_modules(total)
    updates = {}
    for kind, path in paths.items():
        if path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError("拒绝候选符号链接或硬链接。")
        original_path = workspace / path.name
        original_text = original_path.read_text(encoding="utf-8")
        original = tx.parse_frontmatter(original_text)
        text = path.read_text(encoding="utf-8")
        logical = {
            "institution_research": "institution",
            "leader_research": "leader",
            "internal_retrieval": "internal",
            "visit_strategy": "strategy",
            "customer_letter_internal": "letter",
        }.get(kind)
        if kind != "comprehensive_report" and logical not in selected:
            if path.read_bytes() != original_path.read_bytes():
                raise ValueError("不得修改未选中成果：" + kind)
            continue
        meta = tx.parse_frontmatter(text)
        for key in (
            "context_id",
            "customer_id",
            "customer_display_name",
            "organization_scope",
            "safe_name",
            "artifact_type",
            "task_timezone",
            "tenant_id",
            "project_id",
            "authorization_owner",
            "authorization_expires_at",
        ):
            if meta.get(key) != original.get(key):
                raise ValueError("候选不得改变身份或授权字段：" + key)
        if (
            original.get("review_status") == "approved"
            or original.get("ready_for_use") == "true"
        ):
            raise ValueError("构建器仅用于未批准草稿；已批准成果先按治理流程开启修订。")
        if (
            meta.get("review_status") == "approved"
            or meta.get("ready_for_use") == "true"
        ):
            raise ValueError("构建器不得批准或设置ready。")
        new = dict(meta)
        # init/resume already allocated the total's version for this run.
        # Letter history also permits exactly one version per run.
        same_letter_run = (
            kind == "customer_letter_internal"
            and original["latest_run_id"] == manifest["latest_run_id"]
        )
        version = (
            original["content_version"]
            if kind == "comprehensive_report" or same_letter_run
            else str(int(original["content_version"]) + 1)
        )
        new.update(
            content_version=version,
            updated_at=now,
            latest_run_id=manifest["latest_run_id"],
        )
        for key in (
            "reviewer",
            "reviewed_at",
            "reviewed_content_version",
            "reviewed_body_sha256",
        ):
            if key in new:
                new[key] = ""
        if kind != "comprehensive_report":
            new["review_status"] = (
                "not_required"
                if kind == "institution_research"
                else "changes_requested"
                if new.get("freshness_status") in ("stale", "invalidated")
                else "pending"
                if new.get("module_status") == "completed"
                else "not_started"
            )
        text = init.replace_frontmatter(text, new)
        if kind == "visit_strategy":
            text = render_strategy(text, new)
        elif kind == "customer_letter_internal":
            text = finalize_letter_history(text, original_text, new)
        updates[kind] = (path, text, new)
    total_path, total, total_meta = updates["comprehensive_report"]
    all_complete = all(
        meta.get("module_status") == "completed"
        for kind, (_, _, meta) in updates.items()
        if kind != "comprehensive_report"
    )
    total_meta.update(
        ready_for_use="false",
        module_status="completed" if all_complete else "partial",
        workflow_stage="review" if all_complete else "paused",
    )
    for key in (
        "readiness_reviewer",
        "readiness_reviewed_at",
        "readiness_content_version",
        "readiness_body_sha256",
    ):
        total_meta[key] = ""
    total = init.replace_frontmatter(total, total_meta)
    actions = {}
    for kind, label in init.STATUS_LABELS.items():
        if kind not in updates:
            continue
        path, text, meta = updates[kind]
        original = tx.parse_frontmatter(
            (workspace / path.name).read_text(encoding="utf-8")
        )
        action = (
            "created"
            if original.get("module_status") in ("queued", "running", "not_called")
            else "updated"
        )
        module = {
            "institution_research": "institution",
            "leader_research": "leader",
            "internal_retrieval": "internal",
            "visit_strategy": "strategy",
            "customer_letter_internal": "letter",
        }.get(kind)
        if module:
            actions[module] = action
        extras = init.existing_status_extras(total, label)
        gap = extras.get("gaps_blockers", "")
        if meta.get("module_status") in ("partial", "blocked") and gap in (
            "",
            "无",
            "待评估",
        ):
            raise ValueError(label + "须在状态表填写具体缺口，不自动编造。")
        refs = (
            ",".join(sorted(set(val.CLAIM_RE.findall(text.split("---", 2)[-1]))))
            or "无"
        )
        row = init.status_row(
            label,
            init.status_values(
                kind,
                path,
                selected_in_run=True,
                run_action=action,
                frontmatter=meta,
                summary_sync_status="synced",
                key_claim_ids=refs,
                gaps_blockers=gap or "无",
            ),
        )
        total, count = re.subn(
            r"^\|\s*" + re.escape(label) + r"\s*\|.*$",
            lambda _: row,
            total,
            count=1,
            flags=re.M,
        )
        if count != 1:
            raise ValueError("总报告须保留模板状态表：" + label)
    total = init.ensure_refresh_section(total)
    for module in (
        "institution",
        "leader",
        "internal",
        "strategy",
        "letter",
        "external_letter",
    ):
        actions.setdefault(module, "not_called")
    summary = init.run_summary(
        route=total_meta["route"],
        depth=total_meta["depth"],
        objective="生成待审核草稿",
        action_map=actions,
        target_cutoff=total_meta["evidence_cutoff_date"],
    )
    row = (
        "| "
        + " | ".join(
            init.markdown_cell(x)
            for x in (
                now,
                total_meta["content_version"],
                total_meta["latest_run_id"],
                summary,
                total_meta["runtime_owner"],
            )
        )
        + " |"
    )
    lines = total.splitlines()
    found = 0
    in_history = False
    for index, line in enumerate(lines):
        if line.startswith("## "):
            in_history = line.strip() == "## 9. 版本与同步记录"
        if in_history and line.startswith("|"):
            cells = init.split_markdown_cells(line)
            if len(cells) == 5 and cells[2] == total_meta["latest_run_id"]:
                lines[index] = row
                found += 1
    if found != 1:
        raise ValueError("须保留当前run唯一版本记录。")
    total = "\n".join(lines) + "\n"
    updates["comprehensive_report"] = (total_path, total, total_meta)
    # Validate content before writing managed metadata. Actual commit remains CAS protected.
    if total_meta.get("business_mode") == "briefing":
        doc = val.Document(total_path, total, total_meta, total.split("---", 2)[-1])
        body = val.briefing_body(doc)
        val.briefing_lines(body)
        val.validate_briefing_content(body)
    for path, text, _ in updates.values():
        init.atomic_write(path, text)
    # Candidate manifest uses current candidate bytes; never changes the formal manifest.
    fresh = tx.build_manifest(
        candidate,
        identity={
            k: manifest[k]
            for k in (
                "context_id",
                "customer_id",
                "customer_display_name",
                "organization_scope",
            )
        },
        business_mode=total_meta["business_mode"],
        route=total_meta["route"],
        depth=total_meta["depth"],
        latest_run_id=total_meta["latest_run_id"],
        content_version=total_meta["content_version"],
        stage=total_meta["workflow_stage"],
        ready_for_use=False,
        selected_modules=selected,
        authorization=manifest.get("authorization", {}),
        transaction_sequence=manifest["transaction_sequence"],
    )
    tx.atomic_write_json(candidate / tx.MANIFEST_REL, fresh)
    issues, _, _, _ = val.validate(candidate, False, False)
    return {
        "candidate_workspace": str(candidate),
        "errors": [
            {"code": i.code, "message": i.message}
            for i in issues
            if i.severity == "error"
        ],
        "expected_manifest_revision": base["transaction_sequence"],
        "expected_manifest_sha256": base["manifest_sha256"],
        "ready_for_use": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workspace", type=Path)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--output-root", type=Path)
    g.add_argument("--finalize", type=Path)
    a = p.parse_args()
    try:
        result = (
            {
                "candidate_workspace": str(prepare(a.workspace, a.output_root)),
                "ready_for_use": False,
            }
            if a.output_root
            else finalize(a.workspace, a.finalize)
        )
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get("errors") else 0
    except (OSError, ValueError, RuntimeError, KeyError) as e:
        print("ERROR: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
