from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_transaction import (
    ArchivePostcommitError,
    ArchiveTransactionError,
    _create_staging_root,
    _create_windows_staging_root,
    _archive_metadata_lock,
    _recover_staging,
    _rollback,
    _RollbackRecord,
    _windows_mutex_name,
    commit_briefing_pair,
)
from briefing_gate import validate_briefing_data


def valid_payload() -> dict:
    return {
        "schema_version": "1.1",
        "run_id": "run-20260810",
        "report_date": "2026-08-10",
        "generated_at": "2026-08-10T12:00:00+08:00",
        "topic": "技术与医疗数字化",
        "region": "中国、美国与全球",
        "window": {
            "start": "2026-08-04",
            "end": "2026-08-10",
            "timezone": "Asia/Shanghai",
        },
        "punchline": "保留一条已核验信号。",
        "insights": "当前证据支持继续跟踪。",
        "digest": "等待下一项直接证据。",
        "market": "尚未观察到结构变化。",
        "action_levers": [],
        "mix": {
            "default_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "effective_ratio": {"technology": 0.4, "healthcare_digital": 0.6},
            "target_counts": {"technology": 0, "healthcare_digital": 1},
            "actual_counts": {"technology": 0, "healthcare_digital": 1},
            "adjustment": {
                "applied": False,
                "favored_domain": "none",
                "reason": "none",
                "trigger_urls": [],
            },
            "supply_exception": {
                "applied": False,
                "reason": "none",
                "missing_domains": [],
            },
        },
        "top_10": [
            {
                "title": "Source title",
                "title_zh": "来源标题",
                "url": "https://example.org/source",
                "source": "Example Journal",
                "event_date": "2026-08-09",
                "published_at": "2026-08-09",
                "retrieved_at": "2026-08-10T11:00:00+08:00",
                "primary_domain": "healthcare_digital",
                "secondary_domains": [],
                "major_signal": False,
                "major_signal_reason": "none",
                "fact": "来源发布了一项公告。",
                "connection": "与医疗数字化主题相关。",
                "deduction": "需要等待后续直接证据。",
                "actionability": "继续跟踪原始来源。",
                "intelligence_level": "L2",
                "confidence": "medium",
                "summary_zh": "公告摘要。",
            }
        ],
        "data_gaps": ["尚无第二独立来源"],
    }


def render_markdown(payload: dict) -> str:
    item = payload["top_10"][0]
    return (
        f"# {payload['report_date']} 资讯简报\n\n"
        f"## {item['title_zh']}\n\n"
        f"[{item['source']}]({item['url']})\n"
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def windows_owner_group_dacl_sddl(path: Path) -> str:
    import ctypes
    from ctypes import wintypes

    owner_security_information = 0x00000001
    group_security_information = 0x00000002
    dacl_security_information = 0x00000004
    security_information = (
        owner_security_information
        | group_security_information
        | dacl_security_information
    )
    se_file_object = 1
    sddl_revision_1 = 1

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.ULONG),
    ]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    security_descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path),
        se_file_object,
        security_information,
        None,
        None,
        None,
        None,
        ctypes.byref(security_descriptor),
    )
    if status:
        raise ctypes.WinError(status)
    string_descriptor = wintypes.LPWSTR()
    string_length = wintypes.ULONG()
    try:
        converted = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            security_descriptor,
            sddl_revision_1,
            security_information,
            ctypes.byref(string_descriptor),
            ctypes.byref(string_length),
        )
        if not converted:
            raise ctypes.WinError(ctypes.get_last_error())
        return string_descriptor.value
    finally:
        if string_descriptor:
            kernel32.LocalFree(ctypes.cast(string_descriptor, ctypes.c_void_p))
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)


class ArchiveTransactionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows ACL behavior")
    def test_windows_staging_collision_retries_without_touching_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collision = root / ".pih-stage-collision"
            collision.mkdir()
            collision_marker = collision / "owner.txt"
            collision_marker.write_text("unchanged", encoding="utf-8")

            colliding_uuid = unittest.mock.Mock(hex="collision")
            fresh_uuid = unittest.mock.Mock(hex="fresh")
            with patch(
                "archive_transaction.uuid.uuid4",
                side_effect=(colliding_uuid, fresh_uuid),
            ):
                created = _create_windows_staging_root(root)

            self.assertEqual(created, root / ".pih-stage-fresh")
            self.assertTrue(created.is_dir())
            self.assertEqual(collision_marker.read_text(encoding="utf-8"), "unchanged")

    @unittest.skipUnless(os.name == "nt", "Windows ACL behavior")
    def test_windows_staging_creation_failure_is_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "archive_transaction.Path.mkdir",
                side_effect=PermissionError("injected staging denial"),
            ):
                with self.assertRaisesRegex(
                    ArchiveTransactionError,
                    "could not create Windows archive staging",
                ):
                    _create_windows_staging_root(root)
            self.assertEqual(list(root.glob(".pih-stage-*")), [])

    @unittest.skipUnless(os.name == "nt", "Windows ACL behavior")
    def test_windows_promoted_files_match_direct_child_security_descriptor(self):
        base = Path(tempfile.gettempdir()).resolve()
        root = base / f"pih-acl-parity-{os.getpid()}-{os.urandom(8).hex()}"
        root.mkdir(mode=0o777, parents=False, exist_ok=False)
        try:
            reference = root / "direct-child.reference"
            reference.write_bytes(b"reference")
            expected_sddl = windows_owner_group_dacl_sddl(reference)

            result = commit_briefing_pair(
                valid_payload(),
                news_dir=root,
                report_date="2026-08-10",
                run_id="run-20260810",
                render_markdown=render_markdown,
            )

            for target in (
                result.json_path,
                result.markdown_path,
                result.manifest_path,
            ):
                self.assertEqual(
                    windows_owner_group_dacl_sddl(target),
                    expected_sddl,
                    target.name,
                )
                self.assertTrue(os.access(target, os.R_OK), target.name)
        finally:
            if root.exists():
                shutil.rmtree(root)

    @unittest.skipIf(os.name == "nt", "POSIX staging behavior")
    def test_posix_staging_uses_private_mkdtemp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / ".pih-stage-frozen"
            with patch(
                "archive_transaction.tempfile.mkdtemp",
                return_value=str(expected),
            ) as make_temp:
                self.assertEqual(_create_staging_root(root), expected)
            make_temp.assert_called_once_with(prefix=".pih-stage-", dir=root)

    def test_rollback_preserves_backups_for_repeatable_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_a = root / "a.json"
            target_b = root / "b.md"
            backup_a = root / "a.previous"
            backup_b = root / "b.previous"
            target_a.write_bytes(b"new-a")
            target_b.write_bytes(b"new-b")
            backup_a.write_bytes(b"old-a")
            backup_b.write_bytes(b"old-b")
            snapshots = {
                target_a: _RollbackRecord(
                    backup=backup_a,
                    before_sha256=hashlib.sha256(b"old-a").hexdigest(),
                    promoted_sha256=hashlib.sha256(b"new-a").hexdigest(),
                ),
                target_b: _RollbackRecord(
                    backup=backup_b,
                    before_sha256=hashlib.sha256(b"old-b").hexdigest(),
                    promoted_sha256=hashlib.sha256(b"new-b").hexdigest(),
                ),
            }

            real_copy2 = shutil.copy2
            injected = False

            def fail_once(source: Path, destination: Path):
                nonlocal injected
                if destination == target_a and not injected:
                    injected = True
                    raise OSError("injected rollback copy failure")
                return real_copy2(source, destination)

            with patch("archive_transaction.shutil.copy2", side_effect=fail_once):
                failures = _rollback(snapshots)

            self.assertEqual(len(failures), 1)
            self.assertIn("injected rollback copy failure", failures[0])
            self.assertEqual(target_a.read_bytes(), b"new-a")
            self.assertEqual(target_b.read_bytes(), b"old-b")
            self.assertTrue(backup_a.is_file())
            self.assertTrue(backup_b.is_file())

            self.assertEqual(_rollback(snapshots), [])
            self.assertEqual(target_a.read_bytes(), b"old-a")
            self.assertEqual(target_b.read_bytes(), b"old-b")
            self.assertTrue(backup_a.is_file())
            self.assertTrue(backup_b.is_file())

    def test_recovery_journal_is_fully_validated_before_any_target_change(self):
        cases = (
            "history_target",
            "other_date_target",
            "missing_target",
            "missing_report_date",
            "blank_run_id",
            "mismatched_run_id",
            "legacy_hashes",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stem = "intelligence_20260810_briefing"
                targets = (
                    root / f"{stem}.json",
                    root / f"{stem}.md",
                    root / f"{stem}.manifest.json",
                )
                originals = {}
                staging = root / ".pih-stage-forged"
                backup_root = staging / "backup"
                backup_root.mkdir(parents=True)
                snapshots = []
                for index, target in enumerate(targets):
                    original = f"current-{index}".encode("utf-8")
                    target.write_bytes(original)
                    originals[target] = original
                    backup = backup_root / f"{index}-{target.name}.previous"
                    backup.write_bytes(f"previous-{index}".encode("utf-8"))
                    snapshots.append(
                        {
                            "target": str(target.resolve()),
                            "backup": str(backup.resolve()),
                            "backup_sha256": sha256(backup),
                            "before_sha256": sha256(backup),
                            "promoted_sha256": sha256(target),
                        }
                    )

                protected = root / ".pih_history_v2.json"
                protected.write_bytes(b"protected-history")
                other_date = root / "intelligence_20260809_briefing.json"
                other_date.write_bytes(b"other-date")
                (staging / f"{stem}.manifest.json").write_text(
                    json.dumps(
                        {
                            "run_id": "run-20260810",
                            "report_date": "2026-08-10",
                            "json_file": f"{stem}.json",
                            "markdown_file": f"{stem}.md",
                        }
                    ),
                    encoding="utf-8",
                )
                if case == "history_target":
                    snapshots[0]["target"] = str(protected.resolve())
                elif case == "other_date_target":
                    snapshots[0]["target"] = str(other_date.resolve())
                elif case == "missing_target":
                    snapshots.pop(0)

                journal = {
                    "contract_version": "1.0",
                    "run_id": "run-20260810",
                    "report_date": "2026-08-10",
                    "phase": "promoting",
                    "promoted_count": 2,
                    "snapshots": snapshots,
                }
                if case == "missing_report_date":
                    del journal["report_date"]
                elif case == "blank_run_id":
                    journal["run_id"] = "  "
                elif case == "mismatched_run_id":
                    journal["run_id"] = "run-forged"
                elif case == "legacy_hashes":
                    for snapshot in journal["snapshots"]:
                        snapshot.pop("before_sha256")
                        snapshot.pop("promoted_sha256")
                (staging / "transaction.json").write_text(
                    json.dumps(journal), encoding="utf-8"
                )

                with self.assertRaisesRegex(
                    ArchiveTransactionError, "recovery journal"
                ):
                    _recover_staging(root)

                for target, original in originals.items():
                    self.assertEqual(target.read_bytes(), original)
                self.assertEqual(protected.read_bytes(), b"protected-history")
                self.assertEqual(other_date.read_bytes(), b"other-date")
                self.assertTrue(staging.is_dir())

    def test_stale_absent_snapshots_do_not_delete_new_complete_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stem = "intelligence_20260810_briefing"
            targets = (
                root / f"{stem}.json",
                root / f"{stem}.md",
                root / f"{stem}.manifest.json",
            )
            staging = root / ".pih-stage-interrupted"
            backup_root = staging / "backup"
            backup_root.mkdir(parents=True)
            markdown_backup = backup_root / f"1-{targets[1].name}.previous"
            markdown_backup.write_bytes(b"old markdown")
            promoted = (b"stale json", b"stale markdown", b"stale manifest")
            (staging / targets[2].name).write_text(
                json.dumps(
                    {
                        "run_id": "run-stale",
                        "report_date": "2026-08-10",
                        "json_file": targets[0].name,
                        "markdown_file": targets[1].name,
                    }
                ),
                encoding="utf-8",
            )
            snapshots = []
            for index, target in enumerate(targets):
                before = sha256(markdown_backup) if index == 1 else None
                snapshots.append(
                    {
                        "target": str(target.resolve()),
                        "backup": (
                            str(markdown_backup.resolve()) if index == 1 else None
                        ),
                        "backup_sha256": before,
                        "before_sha256": before,
                        "promoted_sha256": hashlib.sha256(promoted[index]).hexdigest(),
                    }
                )
            (staging / "transaction.json").write_text(
                json.dumps(
                    {
                        "contract_version": "1.0",
                        "run_id": "run-stale",
                        "report_date": "2026-08-10",
                        "phase": "promoting",
                        "promoted_count": 1,
                        "snapshots": snapshots,
                    }
                ),
                encoding="utf-8",
            )
            legitimate = (b"legitimate json", b"legitimate markdown", b"legitimate manifest")
            for target, content in zip(targets, legitimate):
                target.write_bytes(content)

            with self.assertRaisesRegex(ArchiveTransactionError, "rollback CAS mismatch"):
                _recover_staging(root)

            self.assertEqual(tuple(target.read_bytes() for target in targets), legitimate)
            self.assertTrue(staging.is_dir())

    def test_healthy_committed_recovery_only_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, _, staging = self._seed_committed_recovery(root)
            committed = {name: path.read_bytes() for name, path in targets.items()}

            _recover_staging(root)
            _recover_staging(root)

            self.assertFalse(staging.exists())
            for name, path in targets.items():
                self.assertEqual(path.read_bytes(), committed[name])

    def test_invalid_committed_recovery_with_foreign_hash_fails_closed(self):
        cases = (
            "target_missing",
            "markdown_corrupt",
            "sidecar_hash_wrong",
            "json_gate_failure",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                targets, _, staging = self._seed_committed_recovery(root)
                if case == "target_missing":
                    targets["markdown"].unlink()
                elif case == "markdown_corrupt":
                    targets["markdown"].write_bytes(b"corrupt markdown bytes")
                elif case == "sidecar_hash_wrong":
                    sidecar = json.loads(
                        targets["manifest"].read_text(encoding="utf-8")
                    )
                    sidecar["json_sha256"] = "0" * 64
                    targets["manifest"].write_text(
                        json.dumps(sidecar), encoding="utf-8"
                    )
                elif case == "json_gate_failure":
                    payload = json.loads(targets["json"].read_text(encoding="utf-8"))
                    del payload["top_10"][0]["retrieved_at"]
                    targets["json"].write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    sidecar = json.loads(
                        targets["manifest"].read_text(encoding="utf-8")
                    )
                    sidecar["json_sha256"] = sha256(targets["json"])
                    targets["manifest"].write_text(
                        json.dumps(sidecar), encoding="utf-8"
                    )

                foreign = {
                    name: path.read_bytes() if path.is_file() else None
                    for name, path in targets.items()
                }

                with self.assertRaisesRegex(
                    ArchiveTransactionError,
                    "rollback was incomplete",
                ):
                    _recover_staging(root)

                self.assertTrue(staging.is_dir())
                journal = json.loads(
                    (staging / "transaction.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    journal["recovery"]["status"],
                    "rollback_incomplete",
                )
                self.assertEqual(
                    {
                        name: path.read_bytes() if path.is_file() else None
                        for name, path in targets.items()
                    },
                    foreign,
                )
                backups = sorted((staging / "backup").glob("*.previous"))
                self.assertEqual(len(backups), 3)

                with self.assertRaisesRegex(
                    ArchiveTransactionError,
                    "previous committed recovery rollback is still incomplete",
                ):
                    _recover_staging(root)
                self.assertEqual(
                    {
                        name: path.read_bytes() if path.is_file() else None
                        for name, path in targets.items()
                    },
                    foreign,
                )
                self.assertTrue(staging.is_dir())
                self.assertEqual(len(list((staging / "backup").glob("*.previous"))), 3)

    def test_invalid_committed_recovery_without_complete_backups_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets, _, staging = self._seed_committed_recovery(root)
            targets["markdown"].write_bytes(b"corrupt markdown bytes")
            next((staging / "backup").glob("1-*.previous")).unlink()
            damaged = {name: path.read_bytes() for name, path in targets.items()}

            with self.assertRaisesRegex(ArchiveTransactionError, "backup is missing"):
                _recover_staging(root)

            self.assertTrue(staging.is_dir())
            self.assertEqual(
                {name: path.read_bytes() for name, path in targets.items()},
                damaged,
            )

    def test_windows_mutex_name_uses_machine_global_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            name = _windows_mutex_name(Path(directory))

        self.assertTrue(name.startswith("Global\\PIHArchive-"))
        self.assertEqual(len(name.removeprefix("Global\\PIHArchive-")), 64)

    def test_success_stages_pair_and_commits_verified_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = valid_payload()

            result = commit_briefing_pair(
                payload,
                news_dir=root,
                report_date="2026-08-10",
                run_id="run-20260810",
                render_markdown=render_markdown,
            )

            self.assertEqual(json.loads(result.json_path.read_text(encoding="utf-8")), payload)
            self.assertEqual(result.markdown_path.read_text(encoding="utf-8"), render_markdown(payload))
            sidecar = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(sidecar["run_id"], "run-20260810")
            self.assertEqual(sidecar["json_sha256"], sha256(result.json_path))
            self.assertEqual(sidecar["markdown_sha256"], sha256(result.markdown_path))
            self.assertEqual(result.json_sha256, sidecar["json_sha256"])
            self.assertEqual(result.markdown_sha256, sidecar["markdown_sha256"])
            self.assertFalse((root / ".pih-archive.lock").exists())
            self.assertEqual(list(root.glob(".pih-stage-*")), [])

    def test_precommit_validator_runs_under_owner_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observed: dict[str, object] = {}
            expected_state = {
                f"intelligence_20260810_briefing.{suffix}": None
                for suffix in ("json", "md", "manifest.json")
            }

            def validate_locked_state() -> dict[str, str | None]:
                lock = json.loads(
                    (root / ".pih-archive.lock").read_text(encoding="utf-8")
                )
                observed["owner_token"] = lock.get("owner_token")
                observed["staging"] = list(root.glob(".pih-stage-*"))
                return expected_state

            commit_briefing_pair(
                valid_payload(),
                news_dir=root,
                report_date="2026-08-10",
                run_id="run-20260810",
                render_markdown=render_markdown,
                precommit_validator=validate_locked_state,
            )

            self.assertRegex(str(observed["owner_token"]), r"^[0-9a-f]{32}$")
            self.assertEqual(observed["staging"], [])

    def test_precommit_failure_leaves_no_staging_or_formal_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def reject() -> None:
                raise ArchiveTransactionError("injected locked precommit rejection")

            with self.assertRaisesRegex(
                ArchiveTransactionError, "locked precommit rejection"
            ):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                    precommit_validator=reject,
                )

            self.assertEqual(list(root.glob("intelligence_*_briefing*")), [])
            self.assertEqual(list(root.glob(".pih-stage-*")), [])
            self.assertFalse((root / ".pih-archive.lock").exists())

    def test_postcommit_failure_preserves_verified_formal_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observed: dict[str, bool] = {}

            def fail_derived_update(result) -> None:
                observed["lock_held"] = (root / ".pih-archive.lock").is_file()
                observed["formal_complete"] = all(
                    path.is_file()
                    for path in (
                        result.json_path,
                        result.markdown_path,
                        result.manifest_path,
                    )
                )
                raise OSError("injected derived history failure")

            with self.assertRaisesRegex(
                ArchivePostcommitError, "derived history failure"
            ) as raised:
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                    postcommit_action=fail_derived_update,
                )

            self.assertTrue(observed["lock_held"])
            self.assertTrue(observed["formal_complete"])
            self.assertTrue(raised.exception.result.json_path.is_file())
            self.assertFalse((root / ".pih-archive.lock").exists())
            self.assertEqual(list(root.glob(".pih-stage-*")), [])

    def test_invalid_json_gate_blocks_before_any_formal_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = valid_payload()
            del payload["top_10"][0]["retrieved_at"]

            with self.assertRaisesRegex(ArchiveTransactionError, "briefing gate"):
                commit_briefing_pair(
                    payload,
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                )

            self.assertEqual(list(root.glob("intelligence_*_briefing*")), [])

    def test_second_promotion_failure_restores_existing_complete_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = self._seed_existing_set(root)
            original = {name: path.read_bytes() for name, path in targets.items()}

            def fail_markdown(source: Path, destination: Path) -> None:
                if destination == targets["markdown"] and source.name == targets["markdown"].name:
                    raise OSError("injected markdown promotion failure")
                os.replace(source, destination)

            with self.assertRaisesRegex(ArchiveTransactionError, "promotion failed"):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                    replace_fn=fail_markdown,
                )

            for name, path in targets.items():
                self.assertEqual(path.read_bytes(), original[name])

    def test_second_promotion_failure_leaves_no_fresh_half_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown_target = root / "intelligence_20260810_briefing.md"

            def fail_markdown(source: Path, destination: Path) -> None:
                if destination == markdown_target and source.name == markdown_target.name:
                    raise OSError("injected markdown promotion failure")
                os.replace(source, destination)

            with self.assertRaises(ArchiveTransactionError):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                    replace_fn=fail_markdown,
                )

            self.assertFalse((root / "intelligence_20260810_briefing.json").exists())
            self.assertFalse(markdown_target.exists())
            self.assertFalse((root / "intelligence_20260810_briefing.manifest.json").exists())

    def test_sidecar_promotion_failure_rolls_back_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = self._seed_existing_set(root)
            original = {name: path.read_bytes() for name, path in targets.items()}

            def fail_sidecar(source: Path, destination: Path) -> None:
                if destination == targets["manifest"] and source.name == targets["manifest"].name:
                    raise OSError("injected sidecar promotion failure")
                os.replace(source, destination)

            with self.assertRaisesRegex(ArchiveTransactionError, "promotion failed"):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    markdown=render_markdown(valid_payload()),
                    replace_fn=fail_sidecar,
                )

            for name, path in targets.items():
                self.assertEqual(path.read_bytes(), original[name])

    def test_target_precondition_mismatch_blocks_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = self._seed_existing_set(root)
            expected_state = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in targets.values()
            }
            targets["markdown"].write_text("concurrent replacement", encoding="utf-8")
            changed_state = {
                name: path.read_bytes() for name, path in targets.items()
            }

            with self.assertRaisesRegex(
                ArchiveTransactionError, "targets changed after the run snapshot"
            ):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                    expected_target_state=expected_state,
                )

            for name, path in targets.items():
                self.assertEqual(path.read_bytes(), changed_state[name])
            self.assertEqual(list(root.glob(".pih-stage-*")), [])
            self.assertFalse((root / ".pih-archive.lock").exists())

    def test_final_reread_failure_rolls_back_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = self._seed_existing_set(root)
            original = {name: path.read_bytes() for name, path in targets.items()}

            with patch(
                "archive_transaction._verify_committed_files",
                side_effect=ArchiveTransactionError("injected final reread failure"),
            ):
                with self.assertRaisesRegex(ArchiveTransactionError, "final verification failed"):
                    commit_briefing_pair(
                        valid_payload(),
                        news_dir=root,
                        report_date="2026-08-10",
                        run_id="run-20260810",
                        render_markdown=render_markdown,
                    )

            for name, path in targets.items():
                self.assertEqual(path.read_bytes(), original[name])

    def test_interrupted_promotion_is_recovered_before_next_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = self._seed_existing_set(root)
            calls = 0

            def interrupt_second(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise KeyboardInterrupt("simulated process interruption")
                os.replace(source, destination)

            with self.assertRaises(KeyboardInterrupt):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                    replace_fn=interrupt_second,
                )

            self.assertTrue(list(root.glob(".pih-stage-*")))
            result = commit_briefing_pair(
                valid_payload(),
                news_dir=root,
                report_date="2026-08-10",
                run_id="run-20260810",
                render_markdown=render_markdown,
            )

            self.assertEqual(
                json.loads(result.json_path.read_text(encoding="utf-8")),
                valid_payload(),
            )
            self.assertEqual(list(root.glob(".pih-stage-*")), [])
            self.assertFalse((root / ".pih-archive.lock").exists())
            self.assertEqual(result.markdown_path, targets["markdown"])

    def test_dead_owner_lock_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".pih-archive.lock").write_text(
                json.dumps(
                    {
                        "run_id": "dead-run",
                        "pid": -1,
                        "hostname": socket.gethostname(),
                        "acquired_at": "2026-08-01T00:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )

            result = commit_briefing_pair(
                valid_payload(),
                news_dir=root,
                report_date="2026-08-10",
                run_id="run-20260810",
                render_markdown=render_markdown,
            )

            self.assertTrue(result.json_path.is_file())
            self.assertFalse((root / ".pih-archive.lock").exists())

    def test_stale_reclaim_refuses_changed_owner_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / ".pih-archive.lock"
            lock.write_text(
                json.dumps(
                    {
                        "run_id": "dead-run",
                        "owner_token": "dead-token",
                        "pid": -1,
                        "hostname": socket.gethostname(),
                        "acquired_at": "2026-08-01T00:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )
            replacement = {
                "run_id": "replacement-run",
                "owner_token": "replacement-token",
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at": "2026-08-10T09:00:00+08:00",
            }

            def replace_during_recovery(_news_dir: Path) -> None:
                lock.write_text(json.dumps(replacement), encoding="utf-8")

            with patch(
                "archive_transaction._recover_staging",
                side_effect=replace_during_recovery,
            ):
                with self.assertRaisesRegex(
                    ArchiveTransactionError, "another archive transaction owns"
                ):
                    with _archive_metadata_lock(root, "new-owner"):
                        self.fail("changed owner metadata must not be reclaimed")

            self.assertEqual(
                json.loads(lock.read_text(encoding="utf-8")), replacement
            )

    def test_metadata_release_does_not_delete_replacement_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / ".pih-archive.lock"
            replacement = {
                "run_id": "replacement-run",
                "owner_token": "replacement-token",
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "acquired_at": "2026-08-10T09:00:00+08:00",
            }

            with _archive_metadata_lock(root, "first-owner"):
                first = json.loads(lock.read_text(encoding="utf-8"))
                self.assertNotEqual(first["owner_token"], replacement["owner_token"])
                lock.write_text(json.dumps(replacement), encoding="utf-8")

            self.assertEqual(
                json.loads(lock.read_text(encoding="utf-8")), replacement
            )

    def test_active_owner_lock_is_not_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / ".pih-archive.lock"
            lock.write_text(
                json.dumps(
                    {
                        "run_id": "active-run",
                        "pid": os.getpid(),
                        "hostname": socket.gethostname(),
                        "acquired_at": "2026-08-10T09:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ArchiveTransactionError, "another archive transaction owns"
            ):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                )

            self.assertTrue(lock.is_file())
            self.assertEqual(list(root.glob(".pih-stage-*")), [])

    def test_foreign_host_lock_is_not_reclaimed_without_liveness_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / ".pih-archive.lock"
            lock.write_text(
                json.dumps(
                    {
                        "run_id": "remote-run",
                        "pid": -1,
                        "hostname": "unverified-remote-host",
                        "acquired_at": "2026-08-01T00:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ArchiveTransactionError, "another archive transaction owns"
            ):
                commit_briefing_pair(
                    valid_payload(),
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                )

            self.assertTrue(lock.is_file())

    def test_concurrent_dead_lock_recovery_has_one_archive_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".pih-archive.lock").write_text(
                json.dumps(
                    {
                        "run_id": "dead-run",
                        "pid": -1,
                        "hostname": socket.gethostname(),
                        "acquired_at": "2026-08-01T00:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )
            entered = threading.Event()
            release = threading.Event()
            worker_errors: list[BaseException] = []
            first_promotion = True

            def hold_first_promotion(source: Path, destination: Path) -> None:
                nonlocal first_promotion
                if first_promotion:
                    first_promotion = False
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("concurrency test did not release first owner")
                os.replace(source, destination)

            def first_owner() -> None:
                try:
                    payload = valid_payload()
                    payload["run_id"] = "first-owner"
                    commit_briefing_pair(
                        payload,
                        news_dir=root,
                        report_date="2026-08-10",
                        run_id="first-owner",
                        markdown=render_markdown(payload),
                        replace_fn=hold_first_promotion,
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    worker_errors.append(exc)

            worker = threading.Thread(target=first_owner, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(5), "first owner did not reach promotion")
            try:
                with self.assertRaisesRegex(
                    ArchiveTransactionError, "another archive transaction owns"
                ):
                    payload = valid_payload()
                    payload["run_id"] = "second-owner"
                    commit_briefing_pair(
                        payload,
                        news_dir=root,
                        report_date="2026-08-10",
                        run_id="second-owner",
                        markdown=render_markdown(payload),
                    )
            finally:
                release.set()
                worker.join(5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(worker_errors, [])
            self.assertFalse((root / ".pih-archive.lock").exists())
            self.assertTrue((root / "intelligence_20260810_briefing.json").is_file())

    def test_report_date_and_run_id_must_match_payload_when_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = valid_payload()

            with self.assertRaisesRegex(ArchiveTransactionError, "report_date"):
                commit_briefing_pair(
                    payload,
                    news_dir=root,
                    report_date="2026-08-09",
                    run_id="run-20260810",
                    render_markdown=render_markdown,
                )
            with self.assertRaisesRegex(ArchiveTransactionError, "run_id"):
                commit_briefing_pair(
                    payload,
                    news_dir=root,
                    report_date="2026-08-10",
                    run_id="other-run",
                    render_markdown=render_markdown,
                )

    @staticmethod
    def _seed_existing_set(root: Path) -> dict[str, Path]:
        base = root / "intelligence_20260810_briefing"
        targets = {
            "json": base.with_suffix(".json"),
            "markdown": base.with_suffix(".md"),
            "manifest": root / "intelligence_20260810_briefing.manifest.json",
        }
        targets["json"].write_bytes(b'{"old":true}')
        targets["markdown"].write_text("old markdown", encoding="utf-8")
        targets["manifest"].write_bytes(b'{"old_manifest":true}')
        return targets

    @staticmethod
    def _seed_committed_recovery(
        root: Path,
    ) -> tuple[dict[str, Path], dict[str, bytes], Path]:
        targets = ArchiveTransactionTests._seed_existing_set(root)
        originals = {name: path.read_bytes() for name, path in targets.items()}
        staging = root / ".pih-stage-committed"
        backup_root = staging / "backup"
        backup_root.mkdir(parents=True)
        snapshots = []
        for index, (name, path) in enumerate(targets.items()):
            backup = backup_root / f"{index}-{path.name}.previous"
            backup.write_bytes(originals[name])
            snapshots.append(
                {
                    "target": str(path.resolve()),
                    "backup": str(backup.resolve()),
                    "backup_sha256": sha256(backup),
                    "before_sha256": sha256(backup),
                }
            )

        payload = valid_payload()
        _, gate_warnings = validate_briefing_data(payload)
        json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        markdown_bytes = render_markdown(payload).encode("utf-8")
        targets["json"].write_bytes(json_bytes)
        targets["markdown"].write_bytes(markdown_bytes)
        targets["manifest"].write_text(
            json.dumps(
                {
                    "contract_version": "1.0",
                    "run_id": "run-20260810",
                    "report_date": "2026-08-10",
                    "schema_version": payload["schema_version"],
                    "json_file": targets["json"].name,
                    "markdown_file": targets["markdown"].name,
                    "json_sha256": hashlib.sha256(json_bytes).hexdigest(),
                    "markdown_sha256": hashlib.sha256(markdown_bytes).hexdigest(),
                    "item_count": len(payload["top_10"]),
                    "committed_at": "2026-08-10T12:00:00+08:00",
                    "gate_warnings": gate_warnings,
                }
            ),
            encoding="utf-8",
        )
        for snapshot, path in zip(snapshots, targets.values()):
            snapshot["promoted_sha256"] = sha256(path)
        (staging / "transaction.json").write_text(
            json.dumps(
                {
                    "contract_version": "1.0",
                    "run_id": "run-20260810",
                    "report_date": "2026-08-10",
                    "phase": "committed",
                    "promoted_count": 3,
                    "snapshots": snapshots,
                }
            ),
            encoding="utf-8",
        )
        return targets, originals, staging


if __name__ == "__main__":
    unittest.main()
