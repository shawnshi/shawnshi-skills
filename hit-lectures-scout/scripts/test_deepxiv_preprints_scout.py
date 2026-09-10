"""Offline regressions for the optional deepxiv candidate CLI (no network/cache)."""

import contextlib
import hashlib
from html import unescape
import importlib.util
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from zoneinfo import ZoneInfoNotFoundError

SCRIPT = Path(__file__).resolve().parents[1] / "assets/deepxiv_preprints_scout.py"
spec = importlib.util.spec_from_file_location("deepxiv_preprints_scout", SCRIPT)
assert spec is not None and spec.loader is not None
scout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scout)


def response(*papers):
    # Legacy fixture labels are syntactically valid synthetic arXiv IDs, not real studies.
    ids: dict[object, str] = {
        "a": "2609.00001",
        "b": "2609.00002",
        "0000.00001": "2609.00001",
    }
    rows = [
        {**p, "arxiv_id": ids.get(p.get("arxiv_id"), p.get("arxiv_id"))}
        if isinstance(p, dict)
        else p
        for p in papers
    ]
    return {"status": "success", "total_count": len(rows), "result": rows}


class DeepxivPreprintsScoutTests(unittest.TestCase):
    def setUp(self):
        # All SDK HTTP is forbidden unless a test installs a narrower local fake.
        self.network = patch(
            "requests.get", side_effect=AssertionError("network forbidden")
        )
        self.network.start()
        self.addCleanup(self.network.stop)
        self.clock = patch.object(
            scout,
            "current_time",
            return_value=datetime.fromisoformat("2026-09-10T10:00:00+08:00"),
        )
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def run_candidate(self, reader, extra=()):
        with tempfile.TemporaryDirectory(prefix="dhls-candidate-test-") as tmp:
            output = Path(tmp) / "candidate.md"
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.object(scout, "build_reader", return_value=reader),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = scout.main(["--output", str(output), *extra])
            text = output.read_text(encoding="utf-8") if output.exists() else None
            terminal = json.loads(stderr.getvalue().splitlines()[-1])
            if text is not None:
                embedded = json.loads(text.split("```json\n")[1].split("\n```")[0])
                self.assertEqual(embedded, terminal["retrieval"])
                self.assertEqual(terminal["publication"]["state"], "verified")
                self.assertEqual(
                    terminal["publication"]["sha256"],
                    hashlib.sha256(output.read_bytes()).hexdigest(),
                )
            # Existing phase1 oracles consume retrieval; publication has separate tests.
            return code, text, stdout.getvalue(), json.dumps(terminal["retrieval"])

    def test_sdk_result_nonempty_enters_candidate(self):
        reader = Mock()
        reader.search.return_value = response(
            {"arxiv_id": "0000.00001", "title": "Synthetic"}
        )
        reader.brief.return_value = {
            "arxiv_id": "2609.00001",
            "tldr": "Synthetic brief",
        }
        code, text, _, stderr = self.run_candidate(reader)
        self.assertEqual(code, 0)
        assert text is not None
        self.assertIn("Synthetic brief", text)
        receipt = json.loads(stderr.splitlines()[-1])
        self.assertEqual(receipt["status"], "success")
        self.assertEqual(
            json.loads(text.split("```json\n")[1].split("\n```")[0]), receipt
        )
        self.assertNotIn("search_mode", reader.search.call_args.kwargs)

    def test_all_search_failed_is_error_without_file(self):
        scout._load_deepxiv_sdk()
        reader = Mock()
        reader.search.side_effect = scout.APIError("synthetic failure")
        code, text, _, stderr = self.run_candidate(reader)
        self.assertEqual(code, 1)
        self.assertIsNone(text)
        self.assertEqual(json.loads(stderr.splitlines()[-1])["status"], "error")
        self.assertEqual(reader.search.call_count, 1)

    def test_invalid_envelopes_are_not_empty(self):
        for raw in (
            None,
            {},
            {"results": []},
            {"status": "error", "result": []},
            {"status": "success", "result": {}},
            response("bad row"),
        ):
            with self.subTest(raw=raw):
                reader = Mock()
                reader.search.return_value = raw
                code, text, _, _ = self.run_candidate(reader)
                self.assertEqual(code, 1)
                self.assertIsNone(text)

    def test_brief_failure_is_disclosed_partial(self):
        scout._load_deepxiv_sdk()
        reader = Mock()
        reader.search.return_value = response({"arxiv_id": "0000.00001"})
        reader.brief.side_effect = scout.APIError("synthetic brief failure")
        code, text, _, stderr = self.run_candidate(reader)
        self.assertEqual(code, 3)
        assert text is not None
        self.assertIn('"status": "partial"', text)
        receipt = json.loads(stderr.splitlines()[-1])
        self.assertEqual(receipt["brief"]["failed"], 1)
        self.assertEqual(
            json.loads(text.split("```json\n")[1].split("\n```")[0]), receipt
        )

    def test_null_and_zero_citations_remain_distinct(self):
        reader = Mock()
        reader.search.return_value = response(
            {"arxiv_id": "a", "citations": None}, {"arxiv_id": "b", "citations": 0}
        )
        reader.brief.return_value = {"tldr": "brief"}
        code, text, _, _ = self.run_candidate(reader)
        self.assertEqual(code, 0)
        assert text is not None
        self.assertIn("**Citations**: N&#47;A", text)
        self.assertIn("**Citations**: 0", text)

    def test_true_empty_and_receipt_match(self):
        reader = Mock()
        reader.search.return_value = response()
        code, text, stdout, stderr = self.run_candidate(reader)
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        receipt = json.loads(stderr.splitlines()[-1])
        self.assertEqual(receipt["status"], "empty")
        self.assertEqual(receipt["search"]["succeeded"], 7)
        self.assertEqual(reader.brief.call_count, 0)
        assert text is not None
        self.assertEqual(
            json.loads(text.split("```json\n")[1].split("\n```")[0]), receipt
        )

    def test_partial_search_stops_all_later_calls(self):
        from deepxiv_sdk import AuthenticationError, RateLimitError, ServerError
        from requests.exceptions import ConnectionError, Timeout

        for failure in (
            AuthenticationError("private"),
            RateLimitError("private"),
            ServerError("Server error 503"),
            ConnectionError("private"),
            Timeout("private"),
        ):
            with self.subTest(kind=type(failure).__name__):
                reader = Mock()
                reader.search.side_effect = [response({"arxiv_id": "a"}), failure]
                code, text, _, stderr = self.run_candidate(
                    reader, ["--include-trending"]
                )
                self.assertEqual(code, 3)
                self.assertIsNotNone(text)
                receipt = json.loads(stderr.splitlines()[-1])
                self.assertEqual(
                    receipt["search"],
                    {"planned": 7, "attempted": 2, "succeeded": 1, "failed": 1},
                )
                self.assertEqual(reader.trending.call_count, 0)
                self.assertEqual(reader.brief.call_count, 0)
                self.assertNotIn("private", stderr)

    def test_first_authentication_failure_stops_without_file(self):
        from deepxiv_sdk import AuthenticationError

        reader = Mock()
        reader.search.side_effect = AuthenticationError("private")
        code, text, _, stderr = self.run_candidate(reader, ["--include-trending"])
        self.assertEqual((code, text), (1, None))
        self.assertEqual(reader.search.call_count, 1)
        self.assertEqual(reader.trending.call_count, 0)
        self.assertEqual(
            json.loads(stderr)["errors"][0]["chain"][0]["codes"]["status_code"], 401
        )

    def test_invalid_metadata_is_schema_error_not_sort_or_render_crash(self):
        for field, value in (
            ("citations", "1"),
            ("citations", True),
            ("citations", -1),
            ("score", float("nan")),
            ("categories", [1]),
            ("keywords", {}),
            ("abstract", 1),
            ("title", []),
            ("arxiv_id", None),
        ):
            with self.subTest(field=field, value=value):
                reader = Mock()
                reader.search.return_value = response({"arxiv_id": "a", field: value})
                code, text, _, stderr = self.run_candidate(reader)
                self.assertEqual((code, text), (1, None))
                self.assertEqual(
                    json.loads(stderr)["errors"][0]["category"], "schema_error"
                )

    def test_bad_brief_retains_search_metadata(self):
        for raw in (
            None,
            {},
            [],
            {"status": "error", "title": "bad"},
            {"abstract": []},
            {"arxiv_id": "other"},
        ):
            with self.subTest(raw=raw):
                reader = Mock()
                reader.search.return_value = response(
                    {"arxiv_id": "a", "title": "original"}
                )
                reader.brief.return_value = raw
                code, text, _, _ = self.run_candidate(reader)
                self.assertEqual(code, 3)
                assert text is not None
                self.assertIn("original", text)

    def test_all_null_brief_is_schema_error_and_retains_candidate(self):
        for raw in ({"arxiv_id": None}, dict.fromkeys(scout.PAPER_FIELDS)):
            with self.subTest(raw=raw):
                reader = Mock()
                reader.search.return_value = response(
                    {"arxiv_id": "a", "title": "original"}
                )
                reader.brief.return_value = raw
                code, text, _, stderr = self.run_candidate(reader)
                self.assertEqual(code, 3)
                assert text is not None
                self.assertIn("original", text)
                receipt = json.loads(stderr)
                self.assertEqual(receipt["status"], "partial")
                self.assertEqual(
                    receipt["brief"],
                    {"planned": 1, "attempted": 1, "succeeded": 0, "failed": 1},
                )
                self.assertEqual(receipt["errors"][0]["category"], "schema_error")
                self.assertEqual(
                    json.loads(text.split("```json\n")[1].split("\n```")[0]), receipt
                )

    def test_nonempty_brief_keeps_zero_and_valid_metadata_with_null(self):
        for raw, expected in (
            ({"citations": 0}, "**Citations**: 0"),
            (
                {"tldr": "valid brief", "arxiv_id": None, "citations": None},
                "valid brief",
            ),
        ):
            with self.subTest(raw=raw):
                reader = Mock()
                reader.search.return_value = response({"arxiv_id": "a"})
                reader.brief.return_value = raw
                code, text, _, stderr = self.run_candidate(reader)
                self.assertEqual(code, 0)
                assert text is not None
                self.assertIn(expected, text)
                receipt = json.loads(stderr)
                self.assertEqual(receipt["status"], "success")
                self.assertEqual(
                    receipt["brief"],
                    {"planned": 1, "attempted": 1, "succeeded": 1, "failed": 0},
                )
                self.assertEqual(receipt["errors"], [])

    def test_trending_failure_is_not_success_or_empty(self):
        reader = Mock()
        reader.search.return_value = response()
        reader.trending.return_value = {}
        code, text, _, stderr = self.run_candidate(reader, ["--include-trending"])
        self.assertEqual((code, text), (1, None))
        self.assertEqual(json.loads(stderr)["trending"]["failed"], 1)

    def test_null_optional_fields_and_legacy_citation(self):
        reader = Mock()
        reader.search.return_value = response(
            {
                "arxiv_id": "a",
                "title": None,
                "abstract": None,
                "keywords": None,
                "categories": None,
                "score": None,
                "citations": None,
                "citation": 0,
            }
        )
        reader.brief.return_value = {"tldr": "brief", "citations": None}
        code, text, _, _ = self.run_candidate(reader)
        self.assertEqual(code, 0)
        assert text is not None
        self.assertIn("**Citations**: 0", text)

    def test_requested_row_limit_is_enforced(self):
        reader = Mock()
        reader.search.return_value = response(
            *[{"arxiv_id": str(i)} for i in range(16)]
        )
        code, text, _, stderr = self.run_candidate(reader)
        self.assertEqual((code, text), (1, None))
        self.assertIn("schema_error", stderr)

    def test_candidate_selection_counts_are_disclosed(self):
        reader = Mock()
        reader.search.side_effect = [
            response(*[{"arxiv_id": f"2609.{q * 15 + i:05d}"} for i in range(15)])
            for q in range(7)
        ]
        reader.brief.return_value = {"tldr": "brief"}
        code, _, _, stderr = self.run_candidate(reader)
        self.assertEqual(code, 0)
        receipt = json.loads(stderr)
        self.assertEqual((receipt["pool_count"], receipt["rendered_count"]), (105, 105))
        self.assertEqual(reader.brief.call_count, 30)

    def test_output_failure_and_existing_target_are_errors(self):
        reader = Mock()
        reader.search.return_value = response()
        with tempfile.TemporaryDirectory(prefix="dhls-output-test-") as tmp:
            output = Path(tmp) / "existing.md"
            output.write_text("unchanged", encoding="utf-8")
            with (
                patch.object(scout, "build_reader", return_value=reader) as build,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(scout.main(["--output", str(output)]), 1)
            build.assert_not_called()
            self.assertEqual(output.read_text(encoding="utf-8"), "unchanged")

    def test_invalid_arguments_do_not_build_reader(self):
        for value in ("0", "-1", "bad", "9999999999999999999"):
            with (
                patch.object(scout, "build_reader") as build,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as caught:
                    scout.main(["--window", value])
                self.assertEqual(caught.exception.code, 2)
                build.assert_not_called()

    def test_missing_sdk_is_error_and_log_state_restored(self):
        logger = logging.getLogger("deepxiv_sdk.reader")
        previous = logger.disabled
        stderr = io.StringIO()
        with (
            tempfile.TemporaryDirectory(prefix="dhls-missing-sdk-") as tmp,
            patch.object(scout, "build_reader", side_effect=ImportError("private")),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(scout.main(["--output", str(Path(tmp) / "c.md")]), 1)
        self.assertEqual(logger.disabled, previous)
        self.assertEqual(json.loads(stderr.getvalue())["retrieval"]["status"], "error")

    def test_help_fresh_process_forbids_sdk_import(self):
        code = "import runpy,sys; sys.modules['deepxiv_sdk']=None; sys.argv=[sys.argv[1],'--help']; runpy.run_path(sys.argv[0],run_name='__main__')"
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", code, str(SCRIPT)],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--window", result.stdout)

    def test_installed_sdk_raw_contracts_and_request_mapping(self):
        from deepxiv_sdk import Reader as NativeReader

        scout._load_deepxiv_sdk()
        checked = scout.Reader(token=None, max_retries=2)
        with patch.object(
            NativeReader, "_make_request", return_value=response({"arxiv_id": "a"})
        ) as request:
            receipt = scout.new_receipt(False)
            pool = scout.search_phase(checked, "2000-01-01", "2000-01-07", receipt)
            self.assertEqual(list(pool), ["2609.00001"])
            params = request.call_args.args[1]
            self.assertEqual(params["top_k"], 15)
            self.assertEqual(params["source"], "arxiv")
            self.assertEqual(params["date_search_type"], "between")
            self.assertEqual(params["date_str"], ["2000-01-01", "2000-01-07"])
            self.assertEqual(params["categories"], scout.CATEGORIES)
            self.assertEqual(params["use_fine_rerank"], "false")
            self.assertNotIn("search_mode", params)
        operations = (
            (
                lambda: checked.search("synthetic"),
                [response(), response({"arxiv_id": "a"})],
            ),
            (lambda: checked.brief("a"), [{"arxiv_id": "a"}, {"tldr": "brief"}]),
            (
                lambda: checked.trending(),
                [
                    {"data": {"papers": [], "total": 0}},
                    {"data": {"papers": [{"arxiv_id": "a"}], "total": 1}},
                ],
            ),
        )
        for call, valid in operations:
            for raw in valid:
                with patch.object(NativeReader, "_make_request", return_value=raw):
                    self.assertIsInstance(call(), dict)
            for raw in (None, {}, [], {"status": "error"}):
                with (
                    patch.object(NativeReader, "_make_request", return_value=raw),
                    self.assertRaises(scout.SchemaError),
                ):
                    call()
        # Native behavior is the reason the private seam must be checked.
        with patch.object(NativeReader, "_make_request", return_value=None):
            self.assertEqual(NativeReader(token=None).search("synthetic"), response())
            self.assertEqual(
                NativeReader(token=None).trending(), {"papers": [], "total": 0}
            )

    def test_installed_sdk_retry_budget_and_private_diagnostics(self):
        from requests.exceptions import ConnectionError, Timeout

        scout._load_deepxiv_sdk()
        for failure in (ConnectionError, Timeout):
            with self.subTest(failure=failure.__name__):
                checked = scout.Reader(token=None, max_retries=2)
                marker = "SYNTHETIC_PRIVATE_VALUE"
                logger = logging.getLogger("deepxiv_sdk.reader")
                previous = logger.disabled
                with (
                    patch(
                        "requests.get",
                        side_effect=failure(
                            "https://invalid.example/full?token=" + marker
                        ),
                    ) as request,
                    patch("deepxiv_sdk.reader.time.sleep") as sleep,
                ):
                    code, text, stdout, stderr = self.run_candidate(
                        checked, ["--include-trending"]
                    )
                self.assertEqual((code, text), (1, None))
                self.assertEqual(request.call_count, 3)
                self.assertEqual(sleep.call_count, 2)
                self.assertNotIn(marker, stdout + stderr)
                self.assertNotIn("https://", stdout + stderr)
                self.assertNotIn("full?", stdout + stderr)
                self.assertIn(failure.__name__, stderr)
                self.assertIn('"traceback"', stderr)
                self.assertEqual(logger.disabled, previous)

    def test_installed_sdk_http_status_and_logs_are_safe(self):
        scout._load_deepxiv_sdk()
        for status in (401, 429, 503):
            with self.subTest(status=status):
                checked = scout.Reader(token=None, max_retries=2)
                raw = Mock(status_code=status, text="SYNTHETIC_PRIVATE_VALUE")
                captured = io.StringIO()
                handler = logging.StreamHandler(captured)
                logger = logging.getLogger("deepxiv_sdk.reader")
                previous = (logger.level, logger.disabled)
                logger.setLevel(logging.DEBUG)
                logger.disabled = False
                logger.addHandler(handler)
                try:
                    with patch("requests.get", return_value=raw) as request:
                        code, text, stdout, stderr = self.run_candidate(checked)
                    self.assertEqual((code, text), (1, None))
                    self.assertEqual(request.call_count, 1)
                    self.assertEqual(
                        json.loads(stderr)["errors"][0]["chain"][0]["codes"][
                            "status_code"
                        ],
                        status,
                    )
                    self.assertEqual(captured.getvalue(), "")
                    self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", stdout + stderr)
                    self.assertFalse(logger.disabled)
                finally:
                    logger.removeHandler(handler)
                    logger.setLevel(previous[0])
                    logger.disabled = previous[1]

    def test_urllib3_connection_logs_private_and_state_restored(self):
        logger = logging.getLogger("urllib3.connection")
        root = logging.getLogger()
        marker = "SYNTHETIC_CONNECTION_TOKEN"
        url = "https://invalid.example/full?token=" + marker
        for destination in ("root", "direct"):
            for exceptional in (False, True):
                for disabled in (False, True):
                    with self.subTest(
                        destination=destination,
                        exceptional=exceptional,
                        disabled=disabled,
                    ):
                        captured, stdout, stderr = (
                            io.StringIO(),
                            io.StringIO(),
                            io.StringIO(),
                        )
                        handler = logging.StreamHandler(captured)
                        with (
                            patch.object(
                                root,
                                "handlers",
                                [handler] if destination == "root" else [],
                            ),
                            patch.object(
                                logger,
                                "handlers",
                                [handler] if destination == "direct" else [],
                            ),
                            patch.object(logger, "level", logging.WARNING),
                            patch.object(logger, "propagate", True),
                            patch.object(logger, "disabled", disabled),
                            contextlib.redirect_stdout(stdout),
                            contextlib.redirect_stderr(stderr),
                        ):
                            before = (
                                logger.disabled,
                                logger.level,
                                list(logger.handlers),
                                logger.propagate,
                                list(root.handlers),
                            )
                            try:
                                with scout.private_sdk_logs():
                                    try:
                                        raise ValueError(url)
                                    except ValueError:
                                        logger.warning(
                                            "Failed to parse headers: %s",
                                            url,
                                            exc_info=True,
                                        )
                                    if exceptional:
                                        raise RuntimeError("synthetic exit")
                            except RuntimeError:
                                if not exceptional:
                                    raise
                            self.assertEqual(
                                (
                                    logger.disabled,
                                    logger.level,
                                    logger.handlers,
                                    logger.propagate,
                                    root.handlers,
                                ),
                                before,
                            )
                            self.assertEqual(captured.getvalue(), "")
                            self.assertNotIn(
                                marker, stdout.getvalue() + stderr.getvalue()
                            )
                            self.assertNotIn(url, stdout.getvalue() + stderr.getvalue())
                            # Enabled logging resumes after either exit, including root propagation.
                            logger.warning("synthetic restored")
                            self.assertEqual(
                                captured.getvalue(),
                                "" if disabled else "synthetic restored\n",
                            )

    def test_cause_and_context_chains_do_not_expose_private_messages(self):
        marker = "SYNTHETIC_CHAIN_TOKEN"
        url = "https://invalid.example/full?token=" + marker
        for explicit_cause in (False, True):
            with self.subTest(explicit_cause=explicit_cause):

                def fail(*args, explicit_cause=explicit_cause, **kwargs):
                    try:
                        raise ValueError(url)
                    except ValueError as inner:
                        if explicit_cause:
                            raise RuntimeError(url) from inner
                        raise RuntimeError(url)  # noqa: B904 - exercise implicit context.

                reader = Mock()
                reader.search.side_effect = fail
                code, text, stdout, stderr = self.run_candidate(reader)
                self.assertEqual((code, text), (1, None))
                self.assertNotIn(marker, stdout + stderr)
                self.assertNotIn(url, stdout + stderr)
                chain = json.loads(stderr)["errors"][0]["chain"]
                self.assertEqual(
                    [entry["type"] for entry in chain],
                    ["builtins.RuntimeError", "builtins.ValueError"],
                )
                for entry in chain:
                    self.assertTrue(entry["traceback"])
                    self.assertTrue(
                        any(frame["function"] == "fail" for frame in entry["traceback"])
                    )
                    self.assertEqual(set(entry), {"type", "codes", "traceback"})
                    for frame in entry["traceback"]:
                        self.assertEqual(set(frame), {"file", "function", "line"})

    def test_trending_success_and_raw_invalid_nested_shapes(self):
        from deepxiv_sdk import Reader as NativeReader

        scout._load_deepxiv_sdk()
        checked = scout.Reader(token=None)
        reader = Mock()
        reader.search.return_value = response()
        reader.trending.return_value = {
            "papers": [{"arxiv_id": "2609.00001"}],
            "total": 1,
        }
        reader.brief.return_value = {"tldr": "brief"}
        code, text, _, stderr = self.run_candidate(reader, ["--include-trending"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stderr)["trending"]["succeeded"], 1)
        assert text is not None
        self.assertIn("Trending", text)
        for raw in (
            {"data": None},
            {"data": {}},
            {"status": "error", "data": {"papers": [], "total": 0}},
            {"data": {"papers": [], "total": 1}},
            {"data": {"papers": [], "total": True}},
        ):
            with (
                patch.object(NativeReader, "_make_request", return_value=raw),
                self.assertRaises(scout.SchemaError),
            ):
                checked.trending()

    def test_invalid_counts_and_mixed_batches_are_not_empty(self):
        for raw in (
            {"status": "success", "total_count": True, "result": []},
            {"status": "success", "total_count": 1, "result": []},
            {"status": "success", "result": []},
            response({"arxiv_id": "a"}, "invalid"),
        ):
            with self.subTest(raw=raw):
                reader = Mock()
                reader.search.return_value = raw
                code, text, _, stderr = self.run_candidate(reader)
                self.assertEqual((code, text), (1, None))
                self.assertEqual(json.loads(stderr)["pool_count"], 0)

    def test_basename_output_and_write_failure_have_truthful_exit(self):
        reader = Mock()
        reader.search.return_value = response()
        for failure in (False, True):
            with (
                tempfile.TemporaryDirectory(prefix="dhls-basename-") as tmp,
                contextlib.chdir(tmp),
            ):
                stderr = io.StringIO()
                with (
                    patch.object(scout, "build_reader", return_value=reader),
                    patch.object(
                        scout.os,
                        "fsync",
                        side_effect=OSError(28, "synthetic") if failure else None,
                    ),
                    contextlib.redirect_stderr(stderr),
                ):
                    code = scout.main(["--output", "candidate.md"])
                terminal = json.loads(stderr.getvalue())
                self.assertEqual(code, 1 if failure else 0)
                self.assertEqual(terminal["retrieval"]["status"], "empty")
                self.assertEqual(
                    terminal["publication"]["state"], "error" if failure else "verified"
                )
                self.assertEqual(Path("candidate.md").exists(), not failure)
                self.assertTrue(Path(terminal["publication"]["draft"]).exists())

    def test_frozen_default_historical_single_day_and_query_override(self):
        cases = [
            ([], "2026-09-04", "2026-09-10"),
            (["--window", "1"], "2026-09-10", "2026-09-10"),
            (
                ["--date-from", "2026-08-01", "--date-to", "2026-08-01"],
                "2026-08-01",
                "2026-08-01",
            ),
            (["--cutoff", "2026-08-10T23:00:00+00:00"], "2026-08-05", "2026-08-11"),
        ]
        for args, start, end in cases:
            reader = Mock()
            reader.search.return_value = response()
            code, _, _, raw = self.run_candidate(
                reader, [*args, "--query", "one", "--query", "two"]
            )
            receipt = json.loads(raw)
            self.assertEqual(code, 0)
            self.assertEqual((receipt["date_from"], receipt["date_to"]), (start, end))
            self.assertEqual(receipt["queries"], ["one", "two"])
            self.assertEqual(reader.search.call_count, 2)
            self.assertTrue(receipt["cutoff"].endswith("+08:00"))
            self.assertEqual(reader.search.call_args.kwargs["date_from"], start)

    def test_scope_and_budget_argument_limits_before_reader(self):
        invalid = [
            ["--window", "367"],
            ["--date-from", "2026-09-01"],
            ["--date-from", "2026-09-11", "--date-to", "2026-09-11"],
            ["--date-from", "2026-09-02", "--date-to", "2026-09-01"],
            ["--date-from", "2025-01-01", "--date-to", "2026-09-01"],
            ["--date-from", "2026-01-01", "--date-to", "2026-01-02", "--window", "7"],
            ["--cutoff", "2026-09-11T00:00:00+08:00"],
            ["--cutoff", "2026-09-01T00:00:00"],
            ["--query", " "],
            ["--query", "q" * 301],
            ["--query", "q"] * 21,
            ["--max-enrich", "-1"],
            ["--max-enrich", "31"],
            ["--budget-seconds", "nan"],
            ["--budget-seconds", "0"],
            ["--request-timeout", "121"],
        ]
        for args in invalid:
            with (
                self.subTest(args=args),
                patch.object(scout, "build_reader") as build,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as caught:
                    scout.main(args)
                self.assertEqual(caught.exception.code, 2)
                build.assert_not_called()
        reader = Mock(search=Mock(return_value=response()))
        self.assertEqual(
            self.run_candidate(reader, ["--window", "366", "--max-enrich", "0"])[0], 0
        )

    def test_trending_historical_skipped_and_streams_never_mixed(self):
        reader = Mock()
        reader.search.return_value = response(
            {"arxiv_id": "a", "publish_at": "2026-09-10"}
        )
        reader.trending.return_value = {
            "papers": [
                {"arxiv_id": "2609.00001", "publish_at": "2026-09-10"},
                {"arxiv_id": "2608.00002", "publish_at": "2026-08-01"},
                {"arxiv_id": "unknown"},
            ],
            "total": 3,
        }
        _, text, _, raw = self.run_candidate(
            reader, ["--include-trending", "--max-enrich", "0"]
        )
        counts = json.loads(raw)["counts"]
        self.assertEqual(
            (
                counts["eligible"],
                counts["supplemental"],
                counts["out_of_range"],
                counts["unverified"],
            ),
            (1, 1, 1, 1),
        )
        self.assertEqual(counts["rendered"], 4)
        self.assertIn("Trending source (not topic match)", text)
        reader.reset_mock()
        self.run_candidate(
            reader,
            [
                "--date-from",
                "2026-08-01",
                "--date-to",
                "2026-08-07",
                "--include-trending",
                "--max-enrich",
                "0",
            ],
        )
        reader.trending.assert_not_called()

    def test_all_105_retained_without_enrichment_and_discovery_order(self):
        for limit in (0, 1, 30):
            reader = Mock()
            reader.search.side_effect = [
                response(
                    *[
                        {
                            "arxiv_id": f"2609.{q * 15 + i:05d}",
                            "publish_at": "2026-09-10",
                            "citations": q * 15 + i,
                        }
                        for i in range(15)
                    ]
                )
                for q in range(7)
            ]
            reader.brief.return_value = {"tldr": "brief"}
            code, text, _, raw = self.run_candidate(
                reader, ["--max-enrich", str(limit)]
            )
            counts = json.loads(raw)["counts"]
            self.assertEqual(code, 0)
            self.assertEqual(
                [counts[k] for k in ("retrieved", "dedup", "eligible", "rendered")],
                [105] * 4,
            )
            self.assertEqual(counts["enriched"], limit)
            self.assertEqual(reader.brief.call_count, limit)
            assert text is not None
            self.assertEqual(text.count("### "), 105)
            if limit:
                self.assertEqual(reader.brief.call_args_list[0].args, ("2609.00000",))

    def test_versions_multi_query_provenance_and_sdk_only_fields(self):
        reader = Mock()
        reader.search.return_value = response(
            {
                "arxiv_id": "2609.00001v1",
                "publish_at": "2026-09-10",
                "authors": ["Synthetic A"],
                "version_date": "2026-09-10",
            },
            {"arxiv_id": "2609.00001v2", "publish_at": "2026-09-10"},
        )
        code, text, _, raw = self.run_candidate(
            reader, ["--query", "one", "--query", "two", "--max-enrich", "0"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(raw)["counts"]["dedup"], 2)
        assert text is not None
        self.assertEqual(text.count("**Matched queries**: one"), 2)
        self.assertEqual(text.count("**Matched queries**: two"), 2)
        self.assertIn("2609.00001v1)", text)
        self.assertIn("2609.00001v2)", text)
        self.assertIn("Synthetic A", text)
        self.assertIn("**SDK version**: N&#47;A", text)

    def test_brief_date_author_and_version_conflict_retains_original(self):
        for field in ("publish_at", "authors", "version_date", "version", "arxiv_id"):
            reader = Mock()
            row = {
                "arxiv_id": "2609.00001v1",
                "publish_at": "2026-09-10",
                "authors": "Original",
                "version_date": "2026-09-10",
                "version": "v1",
            }
            reader.search.return_value = response(row)
            reader.brief.return_value = {field: "conflicting", "tldr": "must not merge"}
            code, text, _, raw = self.run_candidate(reader)
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(raw)["brief"]["failed"], 1)
            self.assertIn("Identity conflict; original retained", text)
            self.assertNotIn("must not merge", text)
            self.assertIn("**Authors**: Original", text)

    def test_unknown_dates_bad_ids_and_markdown_are_isolated(self):
        reader = Mock()
        payload = "```\n# INJECT [link](javascript:bad) <img src=x> |"
        reader.search.return_value = response(
            {
                "arxiv_id": "bad](https://bad)",
                "title": payload,
                "publish_at": "unknown",
                "github_url": "javascript:alert(1)",
                "src_url": 'https://example.org/a)evil("',
            },
            {"arxiv_id": "2609.00001", "publish_at": None},
        )
        code, text, _, raw = self.run_candidate(
            reader, ["--query", "```query", "--max-enrich", "0"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(raw)["counts"]["unverified"], 2)
        assert text is not None
        self.assertEqual(text.count("```"), 2)
        self.assertNotIn("# INJECT", text)
        self.assertNotIn("<img", text)
        self.assertNotIn("javascript:", text)
        self.assertIn("%29evil%28%22", text)
        self.assertIn("invalid syntax; isolated", text)
        for value in (
            "https://u:p@example.org",
            "https://example.org/\n#bad",
            "file:///c:/bad",
            "https://example.org/\\bad",
        ):
            self.assertIsNone(scout.safe_url(value))
        for field, value in (
            ("title", "x" * 4001),
            ("authors", ["x"] * 51),
            ("categories", ["ok", 1]),
        ):
            with self.assertRaises(scout.SchemaError):
                scout.normalize_paper({"arxiv_id": "2609.00001", field: value})

    def test_native_private_staging_publish_and_acl_failure_closed(self):
        import win32security as security

        with tempfile.TemporaryDirectory(prefix="dhls-native-private-") as tmp:
            output = scout.preflight_output(str(Path(tmp) / "候选.md"))
            publication = {}
            stage = scout.prepare_output(output, publication)
            scout.publish_candidate(
                output, stage, b"synthetic candidate draft", publication
            )
            self.assertEqual(publication["state"], "verified")
            for path in (stage / "candidate.draft.md", output):
                scout.check_private_acl(path)
                self.assertEqual(path.read_bytes(), b"synthetic candidate draft")
            sd = security.GetFileSecurity(
                str(stage), security.DACL_SECURITY_INFORMATION
            )
            acl = sd.GetSecurityDescriptorDacl()
            acl.AddAccessAllowedAce(
                security.ACL_REVISION,
                0x1F01FF,
                security.CreateWellKnownSid(security.WinWorldSid),
            )
            sd.SetSecurityDescriptorDacl(1, acl, 0)
            security.SetFileSecurity(str(stage), security.DACL_SECURITY_INFORMATION, sd)
            with self.assertRaises(PermissionError):
                scout.check_private_acl(stage, directory=True)

    def test_output_preflight_blocks_before_sdk(self):
        with tempfile.TemporaryDirectory(prefix="dhls-preflight-") as tmp:
            invalid = [
                "",
                str(Path(tmp) / "missing" / "c.md"),
                str(Path(tmp) / "DHLS-20260910.md"),
                str(Path(tmp) / "c.md:ads"),
                str(Path(tmp) / "NUL.md"),
                str(Path(tmp) / "bad?.md"),
                str(Path(tmp) / "bad.md."),
                "\\\\server\\share\\c.md",
            ]
            for path in invalid:
                with (
                    self.subTest(path=path),
                    patch.object(scout, "build_reader") as build,
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(scout.main(["--output", path]), 1)
                    build.assert_not_called()
            with (
                patch.object(scout.sys, "version_info", (3, 12)),
                self.assertRaises(OSError),
            ):
                scout.preflight_output(str(Path(tmp) / "c.md"))

    def test_native_publish_race_never_overwrites_or_deletes_competitor(self):
        with tempfile.TemporaryDirectory(prefix="dhls-native-race-") as tmp:
            output = scout.preflight_output(str(Path(tmp) / "c.md"))
            publication = {}
            stage = scout.prepare_output(output, publication)
            rename = os.rename

            def race(source, target):
                Path(target).write_bytes(b"competitor")
                rename(source, target)

            with (
                patch.object(scout.os, "rename", side_effect=race),
                self.assertRaises(FileExistsError),
            ):
                scout.publish_candidate(output, stage, b"our draft", publication)
            self.assertEqual(output.read_bytes(), b"competitor")
            self.assertEqual(publication["state"], "error")
            self.assertEqual((stage / "candidate.draft.md").read_bytes(), b"our draft")

    def test_readback_failure_terminal_not_success_and_draft_retained(self):
        reader = Mock(search=Mock(return_value=response()))
        with tempfile.TemporaryDirectory(prefix="dhls-readback-") as tmp:
            output = Path(tmp) / "c.md"
            original = Path.read_bytes

            def fail_target(path):
                if path == output:
                    raise OSError(5, "synthetic readback")
                return original(path)

            stderr = io.StringIO()
            with (
                patch.object(scout, "build_reader", return_value=reader),
                patch.object(Path, "read_bytes", fail_target),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(scout.main(["--output", str(output)]), 1)
            terminal = json.loads(stderr.getvalue())
            self.assertEqual(terminal["retrieval"]["status"], "empty")
            self.assertEqual(terminal["publication"]["state"], "error")
            self.assertIn("post_rename", terminal["publication"]["failure_scope"])
            self.assertEqual(
                output.read_bytes(), Path(terminal["publication"]["draft"]).read_bytes()
            )
            self.assertIn("CANDIDATE DRAFT ONLY", output.read_text(encoding="utf8"))

    def test_monotonic_budget_stop_partial_and_final_inflight_overrun(self):
        for queries in (1, 2):
            ticks = [0.0]
            reader = Mock()

            def slow(ticks=ticks, **kwargs):
                ticks[0] += 2
                return response({"arxiv_id": "2609.00001"})

            reader.search.side_effect = slow
            args = ["--budget-seconds", "1", "--max-enrich", "0"] + [
                "--query",
                "synthetic",
            ] * queries
            with patch.object(
                scout.time, "monotonic", side_effect=lambda ticks=ticks: ticks[0]
            ):
                code, text, _, raw = self.run_candidate(reader, args)
            self.assertEqual(code, 3)
            self.assertEqual(reader.search.call_count, 1)
            self.assertEqual(
                json.loads(raw)["errors"][0]["category"], "budget_exhausted"
            )
            self.assertIn('"status": "partial"', text)
            reader.brief.assert_not_called()
        receipt = scout.new_receipt(False)
        budget = scout.CallBudget(300, 1)
        self.assertTrue(budget.admit(receipt, "search"))
        self.assertFalse(budget.admit(receipt, "search"))

    def test_arxiv_formats_duplicate_metadata_and_implicit_version_conflict(self):
        for aid, base in (
            ("0704.0001v1", "0704.0001"),
            ("1501.00001", "1501.00001"),
            ("hep-th/9901001v2", "hep-th/9901001"),
        ):
            self.assertEqual(scout.arxiv_base(aid), base)
        for aid in (
            "0000.00001",
            "2609.1234",
            "0704.12345",
            "２６０９.１２３４５",
            "2609.00001v0",
            "bad](https://bad)",
        ):
            self.assertIsNone(scout.arxiv_base(aid))
        reader = Mock()
        reader.search.side_effect = [
            response({"arxiv_id": "2609.00001v1"}),
            response(
                {
                    "arxiv_id": "2609.00001v1",
                    "authors": "Later source",
                    "publish_at": "2026-09-10",
                }
            ),
        ]
        reader.brief.return_value = {"version": "v2"}
        code, text, _, raw = self.run_candidate(
            reader, ["--query", "first", "--query", "second"]
        )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(raw)["counts"]["eligible"], 1)
        self.assertIn("Later source", text)
        self.assertIn("Identity conflict; original retained", text)
        self.assertIn("**SDK version**: N&#47;A", text)

    def test_duplicate_identity_conflict_does_not_merge_any_metadata(self):
        original = {"arxiv_id": "2609.00001", "title": "Original", "version": "v1"}
        incoming = {
            "arxiv_id": "2609.00001", "title": "Conflicting", "version": "v2",
            "authors": "Other authors", "publish_at": "2026-09-10",
            "tldr": "Other summary", "citations": 10,
        }
        pool, receipt = {}, scout.new_receipt(False, ["first", "second"])
        scout.add_candidates(pool, [dict(original)], "first", receipt)
        scout.add_candidates(pool, [dict(incoming)], "second", receipt)
        paper = pool[original["arxiv_id"]]
        self.assertEqual({k: v for k, v in paper.items() if not k.startswith("_")}, original)
        self.assertEqual(paper["_sources"], ["first", "second"])
        self.assertEqual(set(paper["_conflicts"]), {"title", "version"})
        self.assertEqual({e["field"] for e in receipt["errors"]}, {"title", "version"})
        reader = Mock()
        reader.search.side_effect = [response(original), response(incoming)]
        code, text, _, raw = self.run_candidate(
            reader, ["--query", "first", "--query", "second", "--max-enrich", "0"]
        )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(raw)["counts"]["eligible"], 0)
        self.assertEqual(json.loads(raw)["counts"]["unverified"], 1)
        self.assertNotIn("Other summary", text)
        self.assertIn("Identity conflict; original retained", text)
        reader.brief.assert_not_called()

    def test_duplicate_without_identity_conflict_still_fills_missing_fields(self):
        reader = Mock()
        reader.search.side_effect = [
            response({"arxiv_id": "2609.00001v1", "title": "Original"}),
            response({"arxiv_id": "2609.00001v1", "title": "Original",
                      "authors": "Later authors", "publish_at": "2026-09-10",
                      "version": "v1", "tldr": "Later summary"}),
        ]
        code, text, _, raw = self.run_candidate(
            reader, ["--query", "first", "--query", "second", "--max-enrich", "0"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(raw)["counts"]["eligible"], 1)
        self.assertIn("Later summary", text)
        self.assertIn("**SDK version**: v1", text)

    def test_search_trending_and_duplicate_id_version_conflicts_stop_calls(self):
        for stream in ("search", "trending", "duplicate"):
            for enrich in (0, 1):
                with self.subTest(stream=stream, enrich=enrich):
                    reader = Mock()
                    row = {"arxiv_id": "2609.00001v1", "version": "v2",
                           "publish_at": "2026-09-10", "tldr": "Incoming summary"}
                    args = ["--max-enrich", str(enrich)]
                    if stream == "trending":
                        reader.search.return_value = response()
                        reader.trending.return_value = {"papers": [row], "total": 1}
                        args += ["--include-trending"]
                    elif stream == "duplicate":
                        reader.search.side_effect = [
                            response({"arxiv_id": row["arxiv_id"]}), response(row)
                        ]
                    else:
                        reader.search.return_value = response(row)
                    reader.brief.return_value = {"tldr": "brief only"}
                    code, text, _, raw = self.run_candidate(reader, args)
                    self.assertEqual(code, 3)
                    receipt = json.loads(raw)
                    self.assertEqual(receipt["status"], "partial")
                    self.assertTrue(any(e.get("field") == "version" for e in receipt["errors"]))
                    self.assertIn("Identity conflict; original retained", text)
                    reader.brief.assert_not_called()
                    self.assertEqual(reader.search.call_count, {"search": 1, "duplicate": 2, "trending": 7}[stream])
                    if stream == "duplicate":
                        self.assertIn("**SDK version**: N&#47;A", text)
                        self.assertNotIn("Incoming summary", text)
                        self.assertEqual(receipt["counts"]["eligible"], 0)

    def test_real_id_version_comparison_does_not_invent_fields(self):
        for aid, version in (("2609.00001v1", None), ("2609.00001v1", "v1"),
                             ("hep-th/9901001v2", "v2"), ("2609.00001", "v2")):
            with self.subTest(aid=aid, version=version):
                pool, receipt = {}, scout.new_receipt(False)
                row = {"arxiv_id": aid}
                if version is not None:
                    row["version"] = version
                scout.add_candidates(pool, [dict(row)], "synthetic", receipt)
                self.assertEqual(receipt["errors"], [])
                self.assertEqual({k: v for k, v in pool[aid].items() if not k.startswith("_")}, row)
        pool, receipt = {}, scout.new_receipt(False)
        scout.add_candidates(pool, [{"arxiv_id": "hep-th/9901001v2", "version": "v1"}], "synthetic", receipt)
        self.assertEqual(pool["hep-th/9901001v2"].get("_conflicts"), ["version"])

    def test_markdown_url_target_entities_and_ipv6_are_preserved(self):
        # Direct output oracle: a CommonMark destination entity is decoded once.
        # Escaping the ampersand must preserve the ORIGINAL entity-looking URL,
        # not create userinfo; IPv6 brackets belong to the validated authority.
        cases = (
            ("https://good.example&commat;evil.example/", "https://good.example&amp;commat;evil.example/"),
            ("https://good.example&#64;evil.example/", "https://good.example&amp;#64;evil.example/"),
            ("https://example.org/a?x=1&y=2", "https://example.org/a?x=1&amp;y=2"),
            ("https://[2001:db8::1]/paper", "https://[2001:db8::1]/paper"),
            ("https://[2001:db8::1]:8443/a(b)?x=1&y=2", "https://[2001:db8::1]:8443/a%28b%29?x=1&amp;y=2"),
        )
        for original, destination in cases:
            for field, label in (("src_url", "Source URL"), ("github_url", "GitHub")):
                with self.subTest(original=original, field=field):
                    text = scout.render_markdown(
                        [{"arxiv_id": "2609.00001", field: original}],
                        "2026-09-04", "2026-09-10", scout.new_receipt(False),
                    )
                    line = next(line for line in text.splitlines() if line.startswith(f"- **{label}**:"))
                    self.assertEqual(line, f"- **{label}**: [source]({destination})")
                    href = unescape(destination)
                    self.assertEqual(href, scout.safe_url(original))
                    self.assertEqual(urlsplit(href).hostname, urlsplit(original).hostname)
                    self.assertIsNone(urlsplit(href).username)
        for unsafe in ("https://u:p@[2001:db8::1]/paper", "https://[broken]/paper"):
            self.assertIsNone(scout.safe_url(unsafe))

    def test_timezone_capability_failure_has_controlled_setup_receipt(self):
        for seam in ("current_time", "ZoneInfo"):
            with self.subTest(seam=seam):
                stderr, stdout = io.StringIO(), io.StringIO()
                with (
                    patch.object(scout, seam, side_effect=ZoneInfoNotFoundError("PRIVATE_ZONE_MESSAGE")),
                    patch.object(scout, "build_reader") as build,
                    patch.object(scout, "preflight_output") as preflight,
                    patch.object(scout, "prepare_output") as prepare,
                    patch.object(scout, "publish_candidate") as publish,
                    contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout),
                ):
                    code = scout.main(["--max-enrich", "0"])
                self.assertEqual(code, 1)
                terminal = json.loads(stderr.getvalue())
                self.assertEqual(terminal["publication"]["state"], "not_attempted")
                receipt = terminal["retrieval"]
                self.assertEqual(receipt["status"], "error")
                self.assertEqual(receipt["errors"][0]["phase"], "setup")
                self.assertIn("ZoneInfoNotFoundError", receipt["errors"][0]["chain"][0]["type"])
                self.assertTrue(receipt["errors"][0]["chain"][0]["traceback"])
                self.assertNotIn("PRIVATE_ZONE_MESSAGE", stderr.getvalue() + stdout.getvalue())
                for operation in ("search", "trending", "brief"):
                    self.assertEqual(receipt[operation]["attempted"], 0)
                for call in (build, preflight, prepare, publish):
                    call.assert_not_called()

    def test_build_reader_budget_and_unknown_version_fail_closed(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            scout.private_sdk_logs(),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            reader = scout.build_reader()
        self.assertEqual(reader.max_retries, 2)
        self.assertEqual(reader.timeout, 45)
        with (
            patch.object(scout, "Reader", None),
            patch.object(scout, "version", return_value="unknown"),
            self.assertRaises(scout.SchemaError),
        ):
            scout._load_deepxiv_sdk()


if __name__ == "__main__":
    unittest.main()
