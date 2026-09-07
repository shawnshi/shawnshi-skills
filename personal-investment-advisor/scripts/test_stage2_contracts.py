"""Stage2 regressions: caller paths, nested status, snapshots, and CLI handoff."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import active_alpha_scan
import active_portfolio_constructor
import active_research_contract
import alpha_validation
import pia
import rebalance_proposal
from status_contract import MAX_STATUS_DEPTH, status_from_payload
from test_p0p1_active_research import (
    alpha_package,
    construction_policy,
    promotion_policy,
    scan_policy,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def digest(document):
    return hashlib.sha256(json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


class CallerPathTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "POSIX can resolve home through the passwd database")
    def test_missing_windows_home_returns_json_usage_error(self):
        with tempfile.TemporaryDirectory(prefix="pia missing home ") as temp:
            env = os.environ.copy()
            for key in ("USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
                env.pop(key, None)
            for key in ("TMP", "TEMP", "TMPDIR", "PIA_YFINANCE_CACHE_DIR"):
                env[key] = temp
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT_DIR / "pia.py"),
                 "research", "~/nonexistent-stage2-probe.json"],
                cwd=temp, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 3, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertEqual(envelope["status"], "failed")
            self.assertEqual(envelope["detail_status"], "cli_usage_error")
            self.assertIn("Could not determine home directory", " ".join(envelope["errors"]))
            self.assertEqual(result.stderr, "")
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_path_resolution_errors_preserve_cause_and_return_json_usage_error(self):
        for method in ("expanduser", "resolve"):
            for error_type in (OSError, RuntimeError):
                error = error_type("injected path resolution failure")
                output = io.StringIO()
                with self.subTest(method=method, error_type=error_type), mock.patch.object(
                    Path, method, side_effect=error
                ), mock.patch.object(pia, "_dispatch") as dispatch:
                    with self.assertRaises(argparse.ArgumentTypeError) as converted:
                        pia._path_argument("input.json")
                    self.assertIs(converted.exception.__cause__, error)
                    self.assertIn(str(error), str(converted.exception))
                    with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_info:
                        pia.main(["research", "input.json"])
                    self.assertEqual(exit_info.exception.code, 3)
                    envelope = json.loads(output.getvalue())
                    self.assertEqual(envelope["status"], "failed")
                    self.assertEqual(envelope["detail_status"], "cli_usage_error")
                    self.assertIn(str(error), " ".join(envelope["errors"]))
                    dispatch.assert_not_called()

    def test_all_twelve_routes_normalize_only_paths_once(self):
        name = "evidence folder/中文 file.json"
        # Route, arguments, path destinations. EDGAR has no path argument.
        cases = [
            ("research", [name], ["brief_json"]),
            ("screen", ["--tickers", "AAA", "--profile", "quality_us", "--profiles-file", name], ["profiles_file"]),
            ("edgar-fundamentals", ["AAA", "--as-of", "2026-08-20"], []),
            ("portfolio-audit", ["AAA", "--positions-file", name], ["positions_file"]),
            ("daily-sync", ["--positions-file", name, "--quotes-file", name, "--thesis-evidence-file", name], ["positions_file", "quotes_file", "thesis_evidence_file"]),
            ("scenario", [name, name, "--output", "out.json"], ["portfolio_json", "assumptions_json", "output"]),
            ("calibrate", ["--journal-path", name, "--output-path", "out.md"], ["journal_path", "output_path"]),
            ("alpha-validate", [name, "--policy-file", name], ["alpha_package", "policy_file"]),
            ("alpha-scan", [name, "--validation-report", name, "--policy-file", name], ["alpha_package", "validation_report", "policy_file"]),
            ("portfolio-construct", [name, "--policy-file", name], ["scan_report", "policy_file"]),
            ("rebalance-proposal", [name, "--policy-file", name], ["construction_report", "policy_file"]),
            ("validate", ["history", name], ["json_path"]),
        ]
        with tempfile.TemporaryDirectory() as temp:
            for cwd in (SCRIPT_DIR.parent, Path(temp)):
                with contextlib.chdir(cwd):
                    for route, argv, fields in cases:
                        with self.subTest(cwd=cwd, route=route), mock.patch.object(
                            pia, "_path_argument", wraps=pia._path_argument
                        ) as resolve, mock.patch.object(pia, "_run_child", return_value=({}, 0)) as run:
                            args = pia._build_parser().parse_args([route, *argv])
                            pia._dispatch(args)
                            self.assertEqual(resolve.call_count, len(fields))
                            child = run.call_args.kwargs["child_arguments"]
                            for field in fields:
                                value = getattr(args, field)
                                self.assertTrue(Path(value).is_absolute())
                                self.assertIn(value, child)
                                self.assertEqual(Path(value).parent, cwd / "evidence folder" if value.endswith("file.json") else cwd)
                            if route == "screen":
                                self.assertEqual(args.profile, "quality_us")
                                self.assertEqual(args.tickers, ["AAA"])

    def test_relative_research_reaches_schema_from_root_and_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "中文 brief with spaces.json"
            source.write_text("{}", encoding="utf-8")
            for cwd in (SCRIPT_DIR.parent, root):
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT_DIR / "pia.py"), "research", os.path.relpath(source, cwd)],
                    cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                envelope = json.loads(result.stdout)
                self.assertEqual(envelope["detail_status"], "research_brief_invalid")
                self.assertEqual(result.returncode, 3)
            self.assertEqual(source.read_text(encoding="utf-8"), "{}")

    def test_relative_aliases_block_before_child_and_preserve_input(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.chdir(temp):
            source = Path("input.json")
            source.write_text("{}", encoding="utf-8")
            cases = [
                ["scenario", "input.json", "other.json", "--output", "./input.json"],
                ["calibrate", "--journal-path", "input.json", "--output-path", "./input.json"],
            ]
            for argv in cases:
                with self.subTest(argv=argv), mock.patch.object(pia, "_run_child") as child:
                    result, code = pia._dispatch(pia._build_parser().parse_args(argv))
                    self.assertEqual(code, 3)
                    self.assertEqual(result["detail_status"], "output_path_conflicts_with_input")
                    child.assert_not_called()
            self.assertEqual(source.read_text(encoding="utf-8"), "{}")

    def test_relative_environment_journal_is_bound_and_alias_checked(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.chdir(temp), mock.patch.dict(
            os.environ, {"PIA_ADVICE_JOURNAL": "journal.jsonl"}
        ), mock.patch.object(pia, "_run_child") as child:
            args = pia._build_parser().parse_args(["calibrate", "--output-path", "./journal.jsonl"])
            self.assertEqual(args.journal_path, str(Path("journal.jsonl").resolve()))
            self.assertEqual(pia._dispatch(args)[1], 3)
            child.assert_not_called()

    def test_relative_output_checks_use_same_absolute_path_as_child(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.chdir(temp):
            for argv, flag in [
                (["scenario", "p.json", "a.json", "--output", "中文 out.json"], "--output"),
                (["calibrate", "--journal-path", "j.jsonl", "--output-path", "中文 out.md"], "--output-path"),
            ]:
                def child(invocation, flag=flag, **kwargs):
                    output = Path(invocation[invocation.index(flag) + 1])
                    self.assertEqual(output.parent, Path(temp))
                    self.assertEqual(Path(invocation[1]).parent, SCRIPT_DIR)
                    output.write_text('{"status":"complete"}', encoding="utf-8")
                    return subprocess.CompletedProcess(invocation, 0, "written", "")
                with self.subTest(argv=argv), mock.patch.object(pia, "_execute_child", side_effect=child) as execute, mock.patch.object(pia.subprocess, "Popen", side_effect=AssertionError("router mock boundary drift")) as spawn:
                    result, code = pia._dispatch(pia._build_parser().parse_args(argv))
                    self.assertEqual(code, 0, result)
                    execute.assert_called_once()
                    spawn.assert_not_called()


class NestedStatusTests(unittest.TestCase):
    def test_malformed_or_invalid_nested_envelopes_fail_closed(self):
        bad_stages = [{}, {"status": "unknown"}, {"status": []}, None, [],
                      {"status": "complete", "valid": False},
                      {"status": "complete", "errors": ["broken"]}]
        for bad in bad_stages:
            payload = {"status": "complete", "stages": [{"status": "complete", "stages": [bad]}]}
            with self.subTest(bad=bad):
                self.assertEqual(status_from_payload(payload, 0), "failed")
        for malformed in (None, {}, "complete"):
            self.assertEqual(status_from_payload({"status": "complete", "stages": malformed}, 0), "failed")

    def test_nested_partial_work_and_exit_mismatches(self):
        partial = {"status": "complete", "stages": [{"status": "complete", "completeness": {"complete": False}}]}
        self.assertEqual(status_from_payload(partial, 0), "incomplete")
        self.assertEqual(status_from_payload(partial, 2), "failed")
        self.assertEqual(status_from_payload({"status": "incomplete", "errors": ["missing independent stage"]}, 1), "incomplete")
        for exit_code in (1, 2, 3, 9, -1):
            self.assertEqual(status_from_payload({"status": "complete", "stages": []}, exit_code), "failed")
        self.assertEqual(status_from_payload([{"status": "complete", "valid": False}], 0), "failed")

    def test_excessive_and_cyclic_nesting_is_bounded(self):
        payload = {"status": "complete"}
        for _ in range(MAX_STATUS_DEPTH + 1):
            payload = {"status": "complete", "stages": [payload]}
        self.assertEqual(status_from_payload(payload, 0), "failed")
        cyclic: dict[str, Any] = {"status": "complete"}
        cyclic["stages"] = [cyclic]
        self.assertEqual(status_from_payload(cyclic, 0), "failed")

    def test_screen_hard_exits_and_malformed_items_outrank_evidence(self):
        for exit_code in (-9, 3, 9):
            self.assertEqual(pia._screen_status([{"status": "insufficient_data"}], exit_code), "failed")
        for item in ({}, {"status": []}, {"status": "unknown"}):
            self.assertEqual(pia._screen_status([{"status": "insufficient_data"}, item], 0), "failed")
        self.assertEqual(pia._screen_status([{"status": "fail"}], 0), "complete")
        self.assertEqual(pia._screen_status([{"status": "fail"}], 1), "failed")
        self.assertEqual(pia._screen_status([{"status": "insufficient_data"}], 2), "insufficient_evidence")


class ActiveSnapshotTests(unittest.TestCase):
    def test_snapshot_reads_once_with_compatible_canonical_unicode_digest(self):
        original = {"z": 1, "中文": [1, 2], "a": 1.0}
        stream = mock.MagicMock(wraps=io.BytesIO(json.dumps(original).encode()))
        stream.__enter__.return_value = stream
        with mock.patch.object(Path, "open", side_effect=[stream, io.BytesIO(b'{"z":2}')]) as read:
            document, sha256 = active_research_contract.read_json_snapshot("input.json", "input")
        self.assertEqual(document, original)
        self.assertEqual(sha256, digest(original))
        read.assert_called_once_with("rb")
        stream.read.assert_called_once_with(active_research_contract.MAX_JSON_BYTES + 1)

    def test_all_entrypoints_bind_every_input_before_business_mutation(self):
        cases = [
            (alpha_validation, "evaluate_alpha_package", ["package.json", "--policy-file", "policy.json"], ["package", "policy"]),
            (active_alpha_scan, "run_active_scan", ["package.json", "--validation-report", "validation.json", "--policy-file", "policy.json"], ["package", "validation", "policy"]),
            (active_portfolio_constructor, "run_construction", ["scan.json", "--policy-file", "policy.json"], ["scan", "policy"]),
            (rebalance_proposal, "run_proposal", ["construction.json", "--policy-file", "policy.json"], ["construction", "policy"]),
        ]
        for module, function, argv, names in cases:
            reads = {}
            def changing_read(path, mode, reads=reads, **kwargs):
                self.assertEqual(mode, "rb")
                name = path.stem
                reads[name] = reads.get(name, 0) + 1
                return io.BytesIO(json.dumps({"name": name, "version": reads[name]}).encode())
            def compute(*documents, names=names, **hashes):
                for name, document in zip(names, documents, strict=True):
                    self.assertEqual(document, {"name": name, "version": 1})
                    self.assertEqual(hashes[name + "_sha256"], digest(document))
                    document["sanitized"] = True
                    self.assertNotEqual(hashes[name + "_sha256"], digest(document))
                return {"status": "complete"}
            with self.subTest(module=module.__name__), mock.patch.object(
                Path, "open", autospec=True, side_effect=changing_read
            ), mock.patch.object(module, function, side_effect=compute) as business, mock.patch.object(
                sys, "argv", [module.__name__, *argv]
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(), 0)
                self.assertEqual(reads, dict.fromkeys(names, 1))
                business.assert_called_once()

    def test_snapshot_read_and_json_errors_remain_explicit(self):
        for error, message in [(PermissionError("blocked"), "input_read_error"),
                               (json.JSONDecodeError("invalid", "{", 1), "input_json_error")]:
            with (
                self.subTest(error=error),
                mock.patch.object(Path, "open", side_effect=error),
                self.assertRaisesRegex(ValueError, message),
            ):
                active_research_contract.read_json_snapshot("input.json", "input")


class DocumentedHandoffTests(unittest.TestCase):
    def test_documented_subprocess_pipeline_and_incomplete_stop(self):
        catalog = (SCRIPT_DIR.parent / "references" / "command-catalog.md").read_text(encoding="utf-8")
        example = catalog.split("```python\n", 1)[1].split("```", 1)[0]
        compile(example, "command-catalog.md", "exec")
        for eligible in (True, False):
            with self.subTest(eligible=eligible), tempfile.TemporaryDirectory(prefix="pia handoff 中文 ") as temp:
                root = Path(temp)
                package = alpha_package()
                if not eligible:
                    package["universe"]["survivorship_bias_control"] = False
                inputs = {
                    "package.json": package,
                    "promotion.json": promotion_policy(),
                    "scan-policy.json": scan_policy(),
                    "construction-policy.json": construction_policy(),
                    "proposal-policy.json": {
                        "schema_version": "pia_rebalance_proposal_policy_v1",
                        "decision_scope": "research_only", "no_trade_band": 0.01,
                        "minimum_net_expected_benefit": 0.0, "review_horizon_days": 90,
                    },
                }
                for name, document in inputs.items():
                    (root / name).write_text(json.dumps(document), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", "-c", example, str(SCRIPT_DIR / "pia.py")],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60,
                )
                if not eligible:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Stage stopped: alpha-validate", result.stderr)
                    self.assertEqual({p.name for p in root.iterdir()}, set(inputs))
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                reports = {name: json.loads((root / (name + ".json")).read_text(encoding="utf-8"))
                           for name in ("validation", "scan", "construction", "proposal")}
                self.assertEqual(reports["validation"]["alpha_package_sha256"], digest(package))
                self.assertEqual(reports["scan"]["validation_report_sha256"], digest(reports["validation"]))
                self.assertEqual(reports["construction"]["scan_report_sha256"], digest(reports["scan"]))
                self.assertEqual(reports["proposal"]["construction_report_sha256"], digest(reports["construction"]))
                for report in reports.values():
                    self.assertEqual(report["status"], "complete")
                    self.assertTrue(report["research_only"])
                self.assertEqual(reports["proposal"]["actionability"], "prohibited")
                # Exclusive publication must not overwrite even an existing valid result.
                original = (root / "validation.json").read_bytes()
                rerun = subprocess.run(
                    [sys.executable, "-B", "-c", example, str(SCRIPT_DIR / "pia.py")],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60,
                )
                self.assertNotEqual(rerun.returncode, 0)
                self.assertEqual((root / "validation.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
