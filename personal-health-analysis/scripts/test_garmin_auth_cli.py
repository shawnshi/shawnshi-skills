import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from garmin_capabilities import issue_capability, require_capability


SCRIPT_PATH = Path(__file__).with_name("garmin_auth.py")


def load_module():
    spec = importlib.util.spec_from_file_location("garmin_auth_cli_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GarminAuthCliTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_help_is_zero_side_effect(self):
        with (
            patch.object(self.module, "_load_garmin_api") as api,
            patch.object(self.module, "login") as login,
            patch.object(self.module, "check_status") as status,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as raised:
                self.module.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        api.assert_not_called()
        login.assert_not_called()
        status.assert_not_called()

    def test_no_subcommand_returns_machine_readable_usage_error(self):
        stdout = io.StringIO()
        with (
            patch.object(self.module, "_load_garmin_api") as api,
            patch.object(self.module, "login") as login,
            patch.object(self.module, "check_status") as status,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = self.module.main([])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, self.module.EXIT_USAGE)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "usage_error")
        api.assert_not_called()
        login.assert_not_called()
        status.assert_not_called()

    def test_password_cli_option_is_not_exposed(self):
        self.assertNotIn("--password", self.module.build_parser().format_help())

    def test_live_dependency_version_mismatch_fails_closed(self):
        with patch.object(self.module, "package_version", return_value="0.3.8"):
            with self.assertRaisesRegex(RuntimeError, "garminconnect_version_mismatch"):
                self.module._load_garmin_api()

    def test_login_dry_run_does_not_prompt_import_or_touch_tokens(self):
        stdout = io.StringIO()
        with (
            patch.object(self.module, "_load_garmin_api") as api,
            patch.object(self.module, "login") as login,
            patch.object(self.module, "check_status") as status,
            patch.object(self.module.getpass, "getpass") as prompt,
            patch.object(Path, "mkdir") as mkdir,
            patch.dict(os.environ, {}, clear=True),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = self.module.main(
                ["login", "--email", "private@example.com", "--dry-run"]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(payload["status"], "dry_run")
        self.assertNotIn("private@example.com", stdout.getvalue())
        api.assert_not_called()
        login.assert_not_called()
        status.assert_not_called()
        prompt.assert_not_called()
        mkdir.assert_not_called()

    def test_live_login_requires_explicit_network_authorization(self):
        stdout = io.StringIO()
        with (
            patch.object(self.module, "_load_garmin_api") as api,
            patch.object(self.module, "login") as login,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = self.module.main(["login", "--email", "x@example.com"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(payload["status"], "network_authorization_required")
        api.assert_not_called()
        login.assert_not_called()

    def test_live_login_requires_token_write_before_password_prompt(self):
        stdout = io.StringIO()
        with (
            patch.object(self.module, "login") as login,
            patch.object(self.module.getpass, "getpass") as prompt,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = self.module.main(
                ["login", "--email", "x@example.com", "--allow-network"]
            )
        self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
        self.assertEqual(
            json.loads(stdout.getvalue())["status"],
            "token_write_authorization_required",
        )
        prompt.assert_not_called()
        login.assert_not_called()

    def test_direct_auth_helpers_fail_closed_without_network_capability(self):
        with (
            patch.object(self.module, "_load_garmin_api") as api,
            patch.object(Path, "mkdir") as mkdir,
        ):
            with self.assertRaises(self.module.NetworkAuthorizationError):
                self.module.login("private@example.com", "secret")
            with self.assertRaises(self.module.NetworkAuthorizationError):
                self.module.get_client()
            with self.assertRaises(self.module.NetworkAuthorizationError):
                self.module.check_status()
            with self.assertRaises(self.module.NetworkAuthorizationError):
                self.module.get_client(network_capability=True)
            with self.assertRaises(self.module.NetworkAuthorizationError):
                self.module.get_client(
                    network_capability=issue_capability(
                        scope="network", operation="garmindb_sync"
                    )
                )
        api.assert_not_called()
        mkdir.assert_not_called()

    def test_main_passes_network_capability_to_login(self):
        stdout = io.StringIO()
        with (
            patch.object(self.module, "login", return_value=True) as login,
            patch.object(self.module, "check_status") as status,
            patch.dict(os.environ, {"GARMIN_PASSWORD": "secret"}, clear=True),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = self.module.main(
                [
                    "login",
                    "--email",
                    "private@example.com",
                    "--allow-network",
                    "--allow-token-write",
                ]
            )
        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "authenticated")
        login.assert_called_once()
        self.assertEqual(login.call_args.args, ("private@example.com", "secret"))
        require_capability(
            login.call_args.kwargs["network_capability"],
            scope="network",
            operation="garmin_auth",
            request={"command": "login"},
        )
        require_capability(
            login.call_args.kwargs["token_write_capability"],
            scope="token_store",
            operation="garmin_token_store_write",
            request={"command": "login"},
        )
        status.assert_not_called()

    def test_main_passes_network_capability_to_status_validation(self):
        stdout = io.StringIO()
        with (
            patch.object(self.module, "check_status", return_value=True) as status,
            patch.object(self.module, "login") as login,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = self.module.main(["status", "--allow-network"])
        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "session_valid")
        status.assert_called_once()
        require_capability(
            status.call_args.kwargs["network_capability"],
            scope="network",
            operation="garmin_auth",
            request={"command": "status"},
        )
        login.assert_not_called()

    def test_auth_failure_output_does_not_echo_identity_or_exception_message(self):
        class FakeGarmin:
            def __init__(self, *_args, **_kwargs):
                pass

            def login(self, **_kwargs):
                raise RuntimeError("private@example.com C:/secret/token.json")

        stderr = io.StringIO()
        with (
            patch.object(self.module, "_load_garmin_api", return_value=FakeGarmin),
            patch.object(self.module, "TOKEN_DIR", Path("unused-token-dir")),
            patch.object(Path, "mkdir"),
            patch.object(Path, "chmod"),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertFalse(
                self.module.login(
                    "private@example.com",
                    "secret",
                    network_capability=issue_capability(
                        scope="network", operation="garmin_auth"
                    ),
                    token_write_capability=issue_capability(
                        scope="token_store", operation="garmin_token_store_write"
                    ),
                )
            )
        emitted = stderr.getvalue()
        self.assertNotIn("private@example.com", emitted)
        self.assertNotIn("secret/token", emitted)
        self.assertIn("RuntimeError", emitted)

    def test_successful_login_does_not_probe_daily_health_summary(self):
        class FakeGarmin:
            def __init__(self, *_args, **_kwargs):
                pass

            def login(self, **_kwargs):
                return None

            def get_user_summary(self, *_args, **_kwargs):
                raise AssertionError("daily health summary must not be read by authentication")

        with tempfile.TemporaryDirectory() as temp_root, patch.object(
            self.module, "_load_garmin_api", return_value=FakeGarmin
        ), patch.object(self.module, "TOKEN_DIR", Path(temp_root) / "tokens"):
            self.assertTrue(
                self.module.login(
                    "private@example.com",
                    "secret",
                    network_capability=issue_capability(
                        scope="network", operation="garmin_auth"
                    ),
                    token_write_capability=issue_capability(
                        scope="token_store", operation="garmin_token_store_write"
                    ),
                )
            )

    def test_direct_egress_adds_garmin_hosts_and_keeps_existing_bypass_entries(self):
        environment = {"NO_PROXY": "internal.example", "no_proxy": "localhost"}
        self.assertTrue(self.module._force_direct_garmin_egress(environment))
        self.assertEqual(
            environment["NO_PROXY"], "internal.example,garmin.com,.garmin.com"
        )
        self.assertEqual(
            environment["no_proxy"], "localhost,garmin.com,.garmin.com"
        )
        self.assertFalse(self.module._force_direct_garmin_egress(environment))

    def test_direct_egress_opt_out_keeps_the_configured_proxy(self):
        environment = {"GARMIN_EGRESS_ALLOW_PROXY": "1", "NO_PROXY": ""}
        self.assertFalse(self.module._force_direct_garmin_egress(environment))
        self.assertEqual(environment["NO_PROXY"], "")

    def test_login_routes_garmin_hosts_around_the_configured_proxy(self):
        class FakeGarmin:
            def __init__(self, *_args, **_kwargs):
                pass

            def login(self, **_kwargs):
                return None

        with (
            tempfile.TemporaryDirectory() as temp_root,
            patch.object(self.module, "_load_garmin_api", return_value=FakeGarmin),
            patch.object(self.module, "TOKEN_DIR", Path(temp_root) / "tokens"),
            patch.dict(os.environ, {"NO_PROXY": "corp.example"}, clear=False),
        ):
            self.assertTrue(
                self.module.login(
                    "private@example.com",
                    "secret",
                    network_capability=issue_capability(
                        scope="network", operation="garmin_auth"
                    ),
                    token_write_capability=issue_capability(
                        scope="token_store", operation="garmin_token_store_write"
                    ),
                )
            )
            self.assertEqual(
                os.environ["NO_PROXY"], "corp.example,garmin.com,.garmin.com"
            )

    def test_failure_classifier_separates_infrastructure_from_credentials(self):
        cases = (
            (
                "rate_limited",
                "GarminConnectTooManyRequestsError",
                "429 Client Error: Too Many Requests for url",
            ),
            (
                "tls_error",
                "CurlError",
                "Failed to perform, curl: (35) TLS connect error: "
                "OPENSSL_internal:invalid library (0)",
            ),
            (
                "connection_error",
                "GarminConnectConnectionError",
                "connection reset by peer",
            ),
            ("mfa_required", "EOFError", "Garmin MFA code: "),
            ("token_store_error", "RuntimeError", "token_store_security_setup_failed"),
            ("dependency_error", "RuntimeError", "garminconnect_version_mismatch"),
            (
                "authentication_failed",
                "GarminConnectAuthenticationError",
                "Invalid credentials",
            ),
            ("auth_unclassified", "RuntimeError", "unexpected state"),
        )
        shared_types = {
            "EOFError": EOFError,
            "RuntimeError": RuntimeError,
        }
        for expected, type_name, message in cases:
            exception_type = shared_types.get(type_name) or type(
                type_name, (Exception,), {}
            )
            with self.subTest(expected=expected):
                self.assertIn(expected, self.module.AUTH_FAILURE_STATUSES)
                self.assertEqual(
                    self.module._classify_auth_failure(exception_type(message)),
                    expected,
                )

    def test_login_failure_reports_category_beside_legacy_status(self):
        rate_limited = type("GarminConnectTooManyRequestsError", (Exception,), {})(
            "429 Client Error: Too Many Requests for url"
        )

        def failing_login(*_args, **_kwargs):
            self.module._emit_safe_failure("authentication_failed", rate_limited)
            return False

        stdout = io.StringIO()
        with (
            patch.object(self.module, "login", side_effect=failing_login),
            patch.dict(os.environ, {"GARMIN_PASSWORD": "secret"}, clear=False),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = self.module.main(
                [
                    "login",
                    "--email",
                    "private@example.com",
                    "--allow-network",
                    "--allow-token-write",
                ]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, self.module.EXIT_AUTH_FAILURE)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "rate_limited")
        self.assertEqual(payload["base_status"], "authentication_failed")
        self.assertEqual(payload["error_type"], "GarminConnectTooManyRequestsError")

    def test_status_failure_reports_transport_category(self):
        tls_failure = type("CurlError", (Exception,), {})(
            "Failed to perform, curl: (35) TLS connect error"
        )

        def failing_status(*_args, **_kwargs):
            self.module._emit_safe_failure("saved_session_invalid", tls_failure)
            return False

        stdout = io.StringIO()
        with (
            patch.object(self.module, "check_status", side_effect=failing_status),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            exit_code = self.module.main(["status", "--allow-network"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, self.module.EXIT_AUTH_FAILURE)
        self.assertEqual(payload["status"], "tls_error")
        self.assertEqual(payload["base_status"], "saved_session_invalid")
        self.assertEqual(payload["error_type"], "CurlError")

    def test_success_paths_keep_legacy_status_strings(self):
        stdout = io.StringIO()
        with (
            patch.object(self.module, "login", return_value=True),
            patch.dict(os.environ, {"GARMIN_PASSWORD": "secret"}, clear=False),
            contextlib.redirect_stdout(stdout),
        ):
            self.module.main(
                [
                    "login",
                    "--email",
                    "private@example.com",
                    "--allow-network",
                    "--allow-token-write",
                ]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "authenticated")
        self.assertNotIn("base_status", payload)


if __name__ == "__main__":
    unittest.main()
