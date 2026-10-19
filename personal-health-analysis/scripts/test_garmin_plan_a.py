"""Offline regressions for Plan A. Only synthetic data and mocked transports."""
from __future__ import annotations

import argparse
import ast
import contextlib
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import garmin_auth as auth
import garmin_auto_sync as auto
import freshness_task_gate as gate
import sync_health_data as sync
from garmin_capabilities import issue_capability


def terminal(changed=False):
    end = "2026-10-18"
    return {
        "status": "success", "run_id": "synthetic-run",
        "requested_window": {"start": "2026-10-12", "end": end},
        "database_fingerprint_changed": changed,
        "component_latest_observation_dates": {name: end for name in gate.COMPONENTS},
        "health_values_persisted": False,
    }


def bounded_login_functions():
    tree = ast.parse(sync._DATE_ADAPTER_CODE)
    nodes: list[ast.stmt] = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and node.name in {"token_only_login", "monitoring_login", "_guard_sync_auth_requests", "_SyncAuthBlocked"}]
    nodes.sort(key=lambda node: getattr(node, "lineno", 0))
    namespace = {"pathlib": pathlib,
                 "HTTPAdapter": lambda **kwargs: types.SimpleNamespace(**kwargs)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<bounded-login-policy>", "exec"), namespace)
    return namespace


class PlanAProcessTests(unittest.TestCase):
    def test_nonzero_child_keeps_structured_rate_limit_and_discards_raw_output(self):
        payload = {"status": "rate_limited", "stage": "download", "retry_after_seconds": 120,
                   "token": "must-not-persist", "sleep_hours": 9.876}
        completed = subprocess.CompletedProcess(["synthetic"], 6, json.dumps(payload), "raw-secret")
        with patch.object(auto.subprocess, "run", return_value=completed):
            with self.assertRaises(auto.CommandFailure) as raised:
                auto._run_json(["synthetic"], 3)
        metadata = raised.exception.metadata
        self.assertEqual(metadata["upstream_status"], "rate_limited")
        self.assertEqual(metadata["upstream_returncode"], 6)
        self.assertEqual(metadata["upstream_stage"], "download")
        self.assertEqual(metadata["retry_after_seconds"], 120)
        self.assertNotIn("must-not-persist", json.dumps(metadata))
        self.assertNotIn("9.876", json.dumps(metadata))
        self.assertNotIn("raw-secret", str(raised.exception))

    def test_invalid_failure_json_does_not_expose_output(self):
        completed = subprocess.CompletedProcess(["synthetic"], 4, "private raw output", "")
        with patch.object(auto.subprocess, "run", return_value=completed):
            with self.assertRaises(auto.CommandFailure) as raised:
                auto._run_json(["synthetic"], 3)
        self.assertEqual(raised.exception.metadata["upstream_status"], "command_failed")
        self.assertNotIn("private", str(raised.exception))

    def test_successful_exit_with_invalid_json_is_not_success(self):
        completed = subprocess.CompletedProcess(["synthetic"], 0, "not JSON", "")
        with patch.object(auto.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(ValueError, "command_json_invalid"):
                auto._run_json(["synthetic"], 3)

    def test_cloudflare_403_is_not_misreported_as_wrong_password(self):
        code, result = sync.classify_process_result(1, "HTTP 403 Cloudflare bot challenge")
        self.assertEqual(code, sync.EXIT_SYNC_FAILURE)
        self.assertEqual(result["status"], "provider_blocked")
        error = RuntimeError("Portal login HTTP 403 Cloudflare bot challenge")
        self.assertEqual(auth._classify_auth_failure(error), "provider_blocked")

    def test_rate_limit_keeps_priority_over_later_challenge(self):
        code, result = sync.classify_process_result(1, "HTTP 429; later HTTP 403 Cloudflare")
        self.assertEqual(code, sync.EXIT_RATE_LIMIT)
        self.assertEqual(result["status"], "rate_limited")


class PlanAFreshnessTests(unittest.TestCase):
    def test_idempotent_complete_window_is_accepted(self):
        self.assertIsNone(gate.validate_terminal_state(
            terminal(False), "2026-10-18", None, "synthetic-run", "2026-10-12"))

    def test_unchanged_stale_window_is_still_rejected(self):
        state = terminal(False)
        state["component_latest_observation_dates"]["hrv"] = "2026-10-14"
        self.assertIsNotNone(gate.validate_terminal_state(
            state, "2026-10-18", None, "synthetic-run", "2026-10-12"))

    def test_missing_fingerprint_evidence_is_rejected(self):
        state = terminal(False)
        del state["database_fingerprint_changed"]
        self.assertEqual(gate.validate_terminal_state(state, "2026-10-18", None, "synthetic-run"),
                         "terminal_database_change_invalid")

    def _run_auto(self, root, *, fail=False, stale=False):
        root = Path(root)
        config = root / "config"
        config.mkdir()
        options = argparse.Namespace(
            allow_network=True, allow_sync=True, allow_health_data=True, days=7,
            garmindb_python=__file__, config_dir=str(config), scratch_dir=str(root / "scratch"),
            state_output=str(root / "state.json"), authority_config=None,
            timeout_seconds=150, total_timeout_seconds=180,
        )
        calls = []
        def runner(command, timeout):
            calls.append(command)
            if "--plan-output" in command:
                Path(command[command.index("--plan-output") + 1]).write_text("{}", encoding="utf-8")
                return {"status": "dry_run"}
            if "sync_health_data.py" in " ".join(command):
                if fail:
                    raise auto.CommandFailure(6, {"status": "rate_limited", "stage": "download"})
                return {"status": "sync_completed"}
            if command[-1] in {"live", "local"}:
                return {"ok": True, "status": "RUNTIME_READY"}
            last = "2026-10-14" if stale else "2026-10-18"
            return {"data_status": "partial", "observations": {
                "sleep": {"date": last, "observation_count": 3},
                "hrv": {"date": last, "observation_count": 3},
                "resting_heart_rate": {"date": last, "observation_count": 3},
                "body_battery": {"highest": {"date": last, "observation_count": 3}},
                "stress_average": {"date": last, "observation_count": 3},
            }}
        result = auto.run_scheduled_sync(options, runner=runner,
                                         database_fingerprinter=lambda: "same-bytes",
                                         today=date(2026, 10, 18))
        return result, calls

    def test_auto_idempotent_success_still_checks_all_components(self):
        with tempfile.TemporaryDirectory() as root:
            (code, state), calls = self._run_auto(root)
        self.assertEqual(code, 0)
        self.assertFalse(state["database_fingerprint_changed"])
        self.assertEqual(state["status"], "success")
        self.assertEqual(len(calls), 5)

    def test_auto_idempotent_stale_data_is_not_ready(self):
        with tempfile.TemporaryDirectory() as root:
            (code, state), _ = self._run_auto(root, stale=True)
        self.assertEqual(code, 1)
        self.assertEqual(state["status"], "failed")
        self.assertIn("coverage_stale", state["error_code"])

    def test_auto_persists_failure_class_and_never_proceeds_to_local_reads(self):
        with tempfile.TemporaryDirectory() as root:
            (code, state), calls = self._run_auto(root, fail=True)
        self.assertEqual(code, 1)
        self.assertEqual(state["upstream_status"], "rate_limited")
        self.assertEqual(state["upstream_stage"], "download")
        self.assertEqual(state["upstream_returncode"], 6)
        self.assertEqual(state["stage"], "sync_execution")
        self.assertEqual(len(calls), 3)
        self.assertFalse(state["health_values_persisted"])


class PlanAWriterLockTests(unittest.TestCase):
    def config(self, root, name, data):
        config = Path(root) / name
        config.mkdir()
        (Path(data) / "DBs").mkdir(parents=True, exist_ok=True)
        (config / sync.CONFIG_NAME).write_text(json.dumps({"directories": {
            "base_dir": str(Path(data).resolve()), "relative_to_home": False}}), encoding="utf-8")
        return config

    def test_different_config_dirs_for_same_resource_share_a_lock(self):
        with tempfile.TemporaryDirectory() as root:
            a = self.config(root, "a", Path(root) / "data")
            b = self.config(root, "b", Path(root) / "data")
            with sync._sync_resource_lock(a):
                with self.assertRaises(BlockingIOError):
                    with sync._sync_resource_lock(b):
                        self.fail("second writer entered")
            with sync._sync_resource_lock(b):
                pass

    def test_unrelated_resources_do_not_block_each_other(self):
        with tempfile.TemporaryDirectory() as root:
            a = self.config(root, "a", Path(root) / "data-a")
            b = self.config(root, "b", Path(root) / "data-b")
            with sync._sync_resource_lock(a), sync._sync_resource_lock(b):
                pass

    def test_exception_releases_the_lock(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.config(root, "config", Path(root) / "data")
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                with sync._sync_resource_lock(config):
                    raise RuntimeError("synthetic")
            with sync._sync_resource_lock(config):
                pass


class PlanABoundedLoginTests(unittest.TestCase):
    def fake_adapter(self, root, load_error=None):
        token = Path(root) / "garmin_tokens.json"
        token.write_text("{}", encoding="utf-8")
        native = types.SimpleNamespace(
            load=Mock(side_effect=load_error),
            _http_post=Mock(),
            cs=types.SimpleNamespace(mount=Mock(), request=Mock(), trust_env=True),
            _api_session=types.SimpleNamespace(mount=Mock(), request=Mock(), trust_env=True),
        )
        client = types.SimpleNamespace(
            client=native, login=Mock(side_effect=AssertionError("no password login")),
            connectapi=Mock(return_value={"displayName": "synthetic", "fullName": "must-not-retain"}),
        )
        config = types.SimpleNamespace(
            get_token_store_file=lambda: str(token), get_garmin_base_domain=lambda: "garmin.com",
            get_user=Mock(side_effect=AssertionError("no config username read")),
            get_password=Mock(side_effect=AssertionError("no config password read")),
        )
        adapter = types.SimpleNamespace(gc_config=config, garmin_factory=Mock(return_value=client))
        return adapter, client, token

    def test_cached_only_login_has_no_password_fallback_or_profile_retention(self):
        policy = bounded_login_functions()
        with tempfile.TemporaryDirectory() as root:
            adapter, client, token = self.fake_adapter(root)
            self.assertTrue(policy["token_only_login"](adapter))
            client.client.load.assert_called_once_with(str(token))
            client.login.assert_not_called()
            adapter.garmin_factory.assert_called_once_with(is_cn=False, retry_attempts=0)
            client.connectapi.assert_called_once_with("/userprofile-service/socialProfile")
            self.assertEqual(adapter.profile, {"displayName": "synthetic"})
            self.assertIsNone(adapter.full_name)
            self.assertFalse(client.client.cs.trust_env)

    def test_missing_token_never_calls_factory_or_credentials(self):
        policy = bounded_login_functions()
        with tempfile.TemporaryDirectory() as root:
            adapter, client, token = self.fake_adapter(root)
            token.unlink()
            with self.assertRaisesRegex(RuntimeError, "saved_session_required"):
                policy["token_only_login"](adapter)
            adapter.garmin_factory.assert_not_called()
            client.login.assert_not_called()

    def test_rejected_token_never_proceeds_to_password_or_profile(self):
        policy = bounded_login_functions()
        with tempfile.TemporaryDirectory() as root:
            adapter, client, _ = self.fake_adapter(root, RuntimeError("HTTP 429"))
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                policy["token_only_login"](adapter)
            client.login.assert_not_called()
            client.connectapi.assert_not_called()

    def test_download_login_does_not_save_personal_information(self):
        policy = bounded_login_functions()
        downloader = types.SimpleNamespace(garmin=types.SimpleNamespace(login=Mock(return_value=True), display_name="synthetic"),
                                           save_json_to_file=Mock())
        self.assertTrue(policy["monitoring_login"](downloader))
        downloader.garmin.login.assert_called_once_with()
        self.assertEqual(downloader.display_name, "synthetic")
        self.assertIsNone(downloader.full_name)
        downloader.save_json_to_file.assert_not_called()

    def test_real_adapter_bootstrap_installs_both_child_local_policies(self):
        import test_sync_health_data as fixtures
        helper = fixtures.SyncHealthDataCliTests()
        helper.setUp()
        cli = fixtures.SYNTHETIC_CLI + '''
import garmindb.download as d
import garmindb.garmin_connect_auth_adapter as a
assert d.Download.login.__name__ == "monitoring_login"
assert a.GarminConnectAuthAdapter.login.__name__ == "token_only_login"
'''
        with tempfile.TemporaryDirectory() as root:
            end = date.today()
            result = helper.run_synthetic_child(root, end - timedelta(days=1), end, cli_text=cli)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_manual_password_login_uses_one_strategy_without_cached_restore(self):
        native = types.SimpleNamespace(
            configure=Mock(), skip_strategies=set(), login=Mock(), dump=Mock(),
            _tokenstore_path=None, _http_post=Mock(),
            cs=types.SimpleNamespace(request=Mock()),
            _api_session=types.SimpleNamespace(request=Mock()),
        )
        wrapper = types.SimpleNamespace(client=native, login=Mock(side_effect=AssertionError("no cache")))
        with tempfile.TemporaryDirectory() as root, patch.object(auth, "_load_garmin_api", return_value=lambda *a, **k: wrapper), \
                patch.object(auth, "TOKEN_DIR", Path(root) / "tokens"):
            ok = auth.login("synthetic@example.invalid", "synthetic",
                            network_capability=issue_capability(scope="network", operation="garmin_auth"),
                            token_write_capability=issue_capability(scope="token_store", operation="garmin_token_store_write"))
        self.assertTrue(ok)
        wrapper.login.assert_not_called()
        native.login.assert_called_once()
        native.dump.assert_called_once()
        self.assertEqual(native.skip_strategies,
                         {"mobile+requests", "widget+cffi", "portal+cffi", "portal+requests"})

    def test_installed_manual_sdk_stops_after_first_strategy_failure(self):
        try:
            import garminconnect as sdk
            from garminconnect import client as sdk_client
        except ImportError:
            self.skipTest("analysis SDK unavailable")
        for status_code, expected in ((429, "rate_limited"), (403, "provider_blocked")):
            with self.subTest(expected=expected):
                wrapper = sdk.Garmin(retry_attempts=0)
                native = wrapper.client
                session = Mock()
                session.post.return_value.status_code = status_code
                fallback = {name: Mock(side_effect=AssertionError("strategy fallback forbidden")) for name in (
                    "_mobile_login_requests", "_widget_web_login", "_portal_web_login_cffi", "_portal_web_login_requests")}
                with tempfile.TemporaryDirectory() as root, \
                        patch.object(auth, "_load_garmin_api", return_value=lambda *a, **k: wrapper), \
                        patch.object(auth, "TOKEN_DIR", Path(root) / "tokens"), \
                        patch.object(sdk_client.cffi_requests, "Session", return_value=session) as transport, \
                        patch.multiple(native, **fallback), patch.object(native, "dump") as dump, \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertFalse(auth.login(
                        "synthetic@example.invalid", "synthetic",
                        network_capability=issue_capability(scope="network", operation="garmin_auth"),
                        token_write_capability=issue_capability(scope="token_store", operation="garmin_token_store_write")))
                    self.assertEqual(auth._LAST_FAILURE["status"], expected)
                transport.assert_called_once_with(impersonate=sdk_client.MOBILE_IMPERSONATIONS[0])
                session.post.assert_called_once()
                for method in fallback.values():
                    method.assert_not_called()
                dump.assert_not_called()

    def test_native_token_verification_failures_never_persist_or_report_success(self):
        import garminconnect as sdk
        from garminconnect import client as sdk_client
        for error, expected in (
            (sdk.GarminConnectTooManyRequestsError("HTTP 429"), "rate_limited"),
            (sdk.GarminConnectConnectionError("HTTP 403 Cloudflare bot challenge"), "provider_blocked"),
            (sdk.GarminConnectConnectionError("HTTP 503"), "connection_error"),
        ):
            with self.subTest(expected=expected):
                wrapper = sdk.Garmin(retry_attempts=0)
                native = wrapper.client
                session = Mock()
                session.post.return_value.status_code = 200
                session.post.return_value.json.return_value = {"responseStatus": {"type": "SUCCESSFUL"}, "serviceTicketId": "synthetic"}
                with tempfile.TemporaryDirectory() as root, \
                        patch.object(auth, "_load_garmin_api", return_value=lambda *a, **k: wrapper), \
                        patch.object(auth, "TOKEN_DIR", Path(root) / "tokens"), \
                        patch.object(sdk_client.cffi_requests, "Session", return_value=session) as transport, \
                        patch.object(native, "_establish_session") as establish, \
                        patch.object(native, "connectapi", side_effect=error) as verify, \
                        patch.object(native, "dump") as dump, contextlib.redirect_stderr(io.StringIO()):
                    self.assertFalse(auth.login(
                        "synthetic@example.invalid", "synthetic",
                        network_capability=issue_capability(scope="network", operation="garmin_auth"),
                        token_write_capability=issue_capability(scope="token_store", operation="garmin_token_store_write")))
                    self.assertEqual(auth._LAST_FAILURE["status"], expected)
                establish.assert_called_once()
                verify.assert_called_once_with("/userprofile-service/socialProfile")
                transport.assert_called_once()
                session.post.assert_called_once()
                dump.assert_not_called()

    def test_single_transport_keeps_mfa_session_alive_until_code_completion(self):
        import garminconnect as sdk
        from garminconnect import client as sdk_client
        wrapper = sdk.Garmin(retry_attempts=0)
        native = wrapper.client
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {"responseStatus": {"type": "MFA_REQUIRED"}}
        def complete(code):
            self.assertEqual(code, "123456")
            session.close.assert_not_called()
        with tempfile.TemporaryDirectory() as root, \
                patch.object(auth, "_load_garmin_api", return_value=lambda *a, **k: wrapper), \
                patch.object(auth, "TOKEN_DIR", Path(root) / "tokens"), \
                patch.object(sdk_client.cffi_requests, "Session", return_value=session), \
                patch.object(native, "_complete_mfa", side_effect=complete) as mfa, \
                patch.object(native, "connectapi", return_value={"displayName": "synthetic"}), \
                patch.object(native, "dump") as dump, patch("builtins.input", return_value="123456"):
            self.assertTrue(auth.login(
                "synthetic@example.invalid", "synthetic",
                network_capability=issue_capability(scope="network", operation="garmin_auth"),
                token_write_capability=issue_capability(scope="token_store", operation="garmin_token_store_write")))
        mfa.assert_called_once_with("123456")
        dump.assert_called_once()

    def test_installed_sync_sdk_supports_the_bounded_token_only_adapter(self):
        interpreter = os.environ.get("GARMIN_A_SYNC_TEST_PYTHON")
        if not interpreter or not Path(interpreter).is_file():
            self.skipTest("explicit sync interpreter not selected")
        program = r'''
import ast, pathlib, types, sys
from unittest.mock import Mock, patch
sys.path.insert(0, '__SCRIPTS__')
import sync_health_data as sync
from garminconnect.client import Client
from garminconnect import Garmin
from garmindb.garmin_connect_auth_adapter import GarminConnectAuthAdapter
from garmindb.download import Download
nodes=[n for n in ast.walk(ast.parse(sync._DATE_ADAPTER_CODE)) if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in {'token_only_login','monitoring_login','_guard_sync_auth_requests','_SyncAuthBlocked'}]
nodes.sort(key=lambda n:n.lineno)
ns={'pathlib':pathlib,'HTTPAdapter':lambda **k:types.SimpleNamespace(**k)}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'<bounded-login-policy>','exec'),ns)
token=pathlib.Path(sys.argv[1]);token.write_text('{}',encoding='utf-8')
config=types.SimpleNamespace(get_token_store_file=lambda:str(token),get_garmin_base_domain=lambda:'garmin.com')
downloader=Download(config)
adapter=downloader.garmin
adapter.login=types.MethodType(ns['token_only_login'],adapter)
with patch.object(Client,'load') as load, patch.object(Client,'connectapi',return_value={'displayName':'synthetic'}), patch.object(Client,'login',side_effect=AssertionError('password login forbidden')):
 assert ns['monitoring_login'](downloader) is True
 load.assert_called_once_with(str(token))
 assert adapter.profile=={'displayName':'synthetic'}
 assert downloader.display_name=='synthetic'
 assert downloader.full_name is None
 # The actual old SDK suppresses Exception in refresh. The owned control
 # signal must still escape and prevent any subsequent API request.
 for http_code in (429,403):
  downloader=Download(config);adapter=downloader.garmin
  wrapper=Garmin(retry_attempts=0)
  adapter.garmin_factory=lambda **kwargs:wrapper
  adapter.login=types.MethodType(ns['token_only_login'],adapter)
  rejection=types.SimpleNamespace(status_code=http_code,json=lambda:{})
  with patch.object(wrapper.client,'_http_post',return_value=rejection) as post:
   assert ns['monitoring_login'](downloader) is True
   native=wrapper.client
   native.di_token='synthetic';native.di_refresh_token='synthetic';native.di_client_id='synthetic'
   try:
    native._refresh_session()
   except ns['_SyncAuthBlocked'] as blocked:
    assert blocked.category==('rate_limited' if http_code==429 else 'provider_blocked')
   else:
    raise AssertionError('refresh swallowed the limited response')
   post.assert_called_once()
print('bounded-sync-sdk-compatible')
'''.replace("__SCRIPTS__", str(Path(__file__).parent).replace("\\", "/"))
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([interpreter, "-B", "-c", program, str(Path(root) / "token.json")],
                                    capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bounded-sync-sdk-compatible", result.stdout)


class PlanATaskProbeTests(unittest.TestCase):
    def test_probe_missing_result_survives_continue_default_parameter_policy(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell unavailable")
        path = Path(__file__).with_name("scheduled_task_probe.ps1")
        program = r'''
function Get-ScheduledTask {
 [CmdletBinding()]param($TaskName,$TaskPath)
 $record=[System.Management.Automation.ErrorRecord]::new([Exception]::new('synthetic missing'),'CmdletizationQuery_NotFound',[System.Management.Automation.ErrorCategory]::ObjectNotFound,$null)
 $PSCmdlet.WriteError($record)
}
$PSDefaultParameterValues['Get-ScheduledTask:ErrorAction']='Continue'
& '__PATH__' -Mode Inspect -TaskName 'Synthetic-Garmin-Test'
'''.replace("__PATH__", str(path).replace("'", "''"))
        result = subprocess.run([shell, "-NoProfile", "-Command", program], capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["exists"])
        self.assertEqual(payload["reason"], "task_missing")

    def test_powershell_classifies_missing_permission_and_unknown_separately(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell unavailable")
        path = Path(__file__).with_name("scheduled_task_probe.ps1")
        program = r'''
$tokens=$null; $errors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseFile('__PATH__',[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'probe parse error'}
$fn=$tree.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-TaskProbeErrorCode'},$true)
Invoke-Expression $fn.Extent.Text
$cases=@(
 @('CmdletizationQuery_NotFound,Get-ScheduledTask','ObjectNotFound'),
 @('AccessDenied,Get-ScheduledTask','PermissionDenied'),
 @('Unexpected,Get-ScheduledTask','ObjectNotFound'))
$result=@($cases | ForEach-Object {
 $e=[System.Management.Automation.ErrorRecord]::new([Exception]::new('synthetic'),$_[0],[System.Management.Automation.ErrorCategory]($_[1]),$null)
 Get-TaskProbeErrorCode -Record $e
})
ConvertTo-Json -InputObject $result -Compress
'''.replace("__PATH__", str(path).replace("'", "''"))
        result = subprocess.run([shell, "-NoProfile", "-Command", program], capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         ["task_missing", "task_probe_permission_denied", "task_probe_failed"])


if __name__ == "__main__":
    unittest.main()
