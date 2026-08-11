from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_transaction import (
    ArchivePostcommitError,
    ArchiveTransactionError,
    _archive_metadata_lock,
    _windows_mutex_name,
    commit_briefing_pair,
)


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


class ArchiveTransactionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
