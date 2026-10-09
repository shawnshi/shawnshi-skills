import io
import json
import os
import subprocess
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

import garmin_auth as auth
import garmin_bounded as bounded
import garmin_intelligence as intelligence
import runtime_preflight as preflight
from garmin_capabilities import issue_capability


class CanonicalRoutingTests(unittest.TestCase):
    def test_equivalent_source_syntax_and_default_share_one_reader(self):
        forms = [
            ["insight_cn", "--source", "local"],
            ["insight_cn", "--source=local"],
            ["--source=local", "insight_cn"],
            ["insight_cn"],
        ]
        calls = []
        for args in forms:
            with patch.object(bounded, "main", return_value=0) as entry:
                code = intelligence.main([*args, "--days", "14", "--allow-health-data"])
            self.assertEqual(code, 0)
            calls.append(entry.call_args.args)
        self.assertTrue(all(call == calls[0] for call in calls))
        self.assertEqual(calls[0][0], ["insight_cn", "--days", "14", "--source", "local", "--allow-health-data"])

    def test_explicit_state_output_preserves_minimal_record_only(self):
        def entry(argv, *, state_writer=None):
            state_writer({"analysis_type": "insight_cn", "status": "ok", "audit_data": {"fixture": "synthetic-private-sentinel"}})
            return 0
        with tempfile.TemporaryDirectory() as directory, patch.object(bounded, "main", side_effect=entry):
            path = Path(directory) / "state.json"
            code = intelligence.main(["insight_cn", "--days", "3", "--allow-health-data", "--state-output", str(path)])
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(set(payload), {"date", "analysis_type", "status", "medical_interpretation"})
        self.assertNotIn("synthetic-private-sentinel", json.dumps(payload))


class SharedRestorationTests(unittest.TestCase):
    def network_capability(self):
        return issue_capability(scope="network", operation=bounded.BOUNDED_LIVE_OPERATION, request={"days": 3})

    def test_insight_uses_stable_snapshot_direct_egress_and_no_sdk_retries(self):
        inner = Mock()
        inner._tokenstore_path = "old"
        client = Mock(client=inner)
        factory = Mock(return_value=client)
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "garmin_tokens.json"
            token.write_text('{"fixture":"synthetic"}', encoding="utf-8")
            original = token.read_bytes()
            with (
                patch.object(auth, "_load_garmin_api", return_value=factory),
                patch.object(bounded, "_live_token_path", return_value=token),
                patch.dict(os.environ, {"NO_PROXY": "localhost", "no_proxy": "localhost", "GARMIN_EGRESS_ALLOW_PROXY": "0"}),
            ):
                result = bounded._load_live_client(network_capability=self.network_capability(), request={"days": 3})
                self.assertIn(".garmin.com", os.environ["NO_PROXY"])
                self.assertIn(".garmin.com", os.environ["no_proxy"])
            self.assertEqual(token.read_bytes(), original)
        self.assertIs(result, client)
        factory.assert_called_once_with(retry_attempts=0)
        inner.configure.assert_called_once_with(retries=0)
        inner.loads.assert_called_once_with('{"fixture":"synthetic"}')
        client.login.assert_not_called()
        self.assertIsNone(inner._tokenstore_path)

    def test_unauthorized_restore_cannot_locate_or_read_tokens(self):
        with patch.object(bounded, "_live_token_path") as locate, patch.object(auth, "_load_garmin_api") as api:
            with self.assertRaises(auth.NetworkAuthorizationError):
                bounded._load_live_client()
        locate.assert_not_called()
        api.assert_not_called()

    def test_http_status_is_preserved_without_exception_text(self):
        error = RuntimeError("synthetic-private-sentinel")
        error.response = types.SimpleNamespace(status_code=429)
        stderr = io.StringIO()
        with (
            patch.object(auth, "_load_garmin_api", return_value=Mock()),
            patch.object(auth, "_restore_client_without_persistent_token_write", side_effect=error),
            redirect_stderr(stderr),
        ):
            with self.assertRaises(auth.SavedSessionError) as failure:
                auth.get_client(network_capability=self.network_capability(), operation=bounded.BOUNDED_LIVE_OPERATION, request={"days": 3}, raise_on_error=True)
        self.assertEqual(failure.exception.status, "rate_limited")
        self.assertEqual(failure.exception.http_status, 429)
        self.assertNotIn("synthetic-private-sentinel", str(failure.exception))
        self.assertEqual(stderr.getvalue(), "")

    def test_saved_session_transport_failure_is_not_no_data(self):
        error = auth.SavedSessionError(RuntimeError("SSL handshake synthetic failure"))
        output = io.StringIO()
        with patch.object(bounded, "fetch_live_summary", side_effect=error), patch("sys.stdout", output):
            code = bounded.main(["insight_cn", "--days", "3", "--source", "live", "--allow-health-data", "--allow-network"])
        payload = json.loads(output.getvalue())
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["status"], "tls_error")
        self.assertEqual(payload["data_status"], "read_error")


class RuntimeImportProbeTests(unittest.TestCase):
    def test_probe_uses_same_interpreter_and_removes_ambient_token_settings(self):
        completed = subprocess.CompletedProcess([], 0, '{"ok":true}', "")
        with patch.dict(os.environ, {"GARTH_HOME": "synthetic", "GARTH_TOKEN": "synthetic"}), patch.object(preflight.subprocess, "run", return_value=completed) as runner:
            self.assertTrue(preflight.probe_imports(["pandas"])["ok"])
        args = runner.call_args.args[0]
        self.assertEqual(args[:3], [preflight.sys.executable, "-I", "-B"])
        self.assertNotIn("GARTH_HOME", runner.call_args.kwargs["env"])
        self.assertNotIn("GARTH_TOKEN", runner.call_args.kwargs["env"])

    def test_module_location_cannot_hide_a_failed_import(self):
        with patch.object(preflight.metadata, "version", return_value="3.0.6"), patch.object(preflight.importlib.util, "find_spec", return_value=object()), patch.object(preflight, "probe_imports", return_value={"ok": False, "error_type": "ImportError"}):
            result = preflight.verify_runtime("local")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "RUNTIME_DEPENDENCY_UNAVAILABLE")
        self.assertEqual(result["failures"][0]["reason"], "import_probe_failed")

    def test_timeout_and_unstructured_output_fail_closed(self):
        cases = [subprocess.CompletedProcess([], 1, "synthetic-private-sentinel", ""), subprocess.TimeoutExpired("probe", 15)]
        for case in cases:
            kwargs = {"side_effect": case} if isinstance(case, Exception) else {"return_value": case}
            with self.subTest(case=type(case).__name__), patch.object(preflight.subprocess, "run", **kwargs):
                result = preflight.probe_imports(["pandas"])
            self.assertFalse(result["ok"])
            self.assertNotIn("synthetic-private-sentinel", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
