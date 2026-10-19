"""Transport-level offline counterexamples for MFA and ticket-exchange fallback."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import garmin_auth as auth
import sync_health_data as sync
from garmin_capabilities import issue_capability


def response(code=200, payload=None, headers=None):
    return types.SimpleNamespace(status_code=code, json=lambda: payload or {}, headers=headers or {})


class ScriptedSession:
    def __init__(self, *responses):
        self.network = Mock(side_effect=list(responses))
        self.close = Mock()

    def request(self, method, url, **kwargs):
        return self.network(method, url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)


class AuthFailFastTests(unittest.TestCase):
    def run_login(self, wrapper, session):
        from garminconnect import client as sdk
        with tempfile.TemporaryDirectory() as root, \
                patch.object(auth, "_load_garmin_api", return_value=lambda *a, **kw: wrapper), \
                patch.object(auth, "TOKEN_DIR", Path(root) / "tokens"), \
                patch.object(sdk.cffi_requests, "Session", return_value=session) as factory, \
                patch("builtins.input", return_value="123456"), \
                contextlib.redirect_stderr(io.StringIO()):
            result = auth.login(
                "synthetic@example.invalid", "synthetic",
                network_capability=issue_capability(scope="network", operation="garmin_auth"),
                token_write_capability=issue_capability(scope="token_store", operation="garmin_token_store_write"))
        factory.assert_called_once_with(impersonate=sdk.MOBILE_IMPERSONATIONS[0])
        return result, dict(auth._LAST_FAILURE)

    def test_mfa_first_restricted_response_never_submits_to_second_endpoint(self):
        import garminconnect
        for rejected, category in (
            (response(429), "rate_limited"),
            (response(403), "provider_blocked"),
            (response(200, {"error": {"status-code": "429"}}), "rate_limited"),
            (response(200, headers={"cf-mitigated": "challenge"}), "provider_blocked"),
        ):
            with self.subTest(category=category, http_status=rejected.status_code):
                wrapper = garminconnect.Garmin(retry_attempts=0)
                native = wrapper.client
                session = ScriptedSession(response(200, {"responseStatus": {"type": "MFA_REQUIRED"}}), rejected)
                with patch.object(native, "dump") as dump, \
                        patch.object(native, "_http_post", side_effect=AssertionError("MFA must not proceed to ticket exchange")) as exchange, \
                        patch.object(native, "connectapi", side_effect=AssertionError("MFA must not reach token verification")) as verify:
                    ok, failure = self.run_login(wrapper, session)
                self.assertFalse(ok)
                self.assertEqual(failure["status"], category)
                self.assertEqual(session.network.call_count, 2)  # SSO + first MFA, no alternate URL
                exchange.assert_not_called()
                verify.assert_not_called()
                dump.assert_not_called()
                self.assertFalse(native.is_authenticated)

    def test_di_first_restricted_response_never_tries_another_client_id_or_jwt(self):
        import garminconnect
        from garminconnect import client as sdk
        for code, category in ((429, "rate_limited"), (403, "provider_blocked")):
            with self.subTest(code=code):
                wrapper = garminconnect.Garmin(retry_attempts=0)
                native = wrapper.client
                session = ScriptedSession(response(200, {
                    "responseStatus": {"type": "SUCCESSFUL"}, "serviceTicketId": "synthetic-ticket"}))
                with patch.object(sdk.cffi_requests, "post", return_value=response(code)) as exchange, \
                        patch.object(native.cs, "get", side_effect=AssertionError("JWT fallback forbidden")) as jwt, \
                        patch.object(native, "connectapi", side_effect=AssertionError("verification after rejection forbidden")) as verify, \
                        patch.object(native, "dump") as dump:
                    ok, failure = self.run_login(wrapper, session)
                self.assertFalse(ok)
                self.assertEqual(failure["status"], category)
                session.network.assert_called_once()
                exchange.assert_called_once()
                jwt.assert_not_called()
                verify.assert_not_called()
                dump.assert_not_called()
                self.assertFalse(native.is_authenticated)

    def test_api_verification_rate_limit_cannot_become_success(self):
        import garminconnect
        wrapper = garminconnect.Garmin(retry_attempts=0)
        native = wrapper.client
        session = ScriptedSession(response(200, {
            "responseStatus": {"type": "SUCCESSFUL"}, "serviceTicketId": "synthetic-ticket"}))
        def establish(*args, **kwargs):
            native.di_token = "synthetic-candidate"
            native.di_client_id = "synthetic-client"
        with patch.object(native, "_establish_session", side_effect=establish), \
                patch.object(native, "_token_expires_soon", return_value=False), \
                patch.object(native._api_session, "request", return_value=response(429)) as verify, \
                patch.object(native, "dump") as dump:
            ok, failure = self.run_login(wrapper, session)
        self.assertFalse(ok)
        self.assertEqual(failure["status"], "rate_limited")
        verify.assert_called_once()
        dump.assert_not_called()
        self.assertFalse(native.is_authenticated)

    def test_latch_blocks_network_even_if_a_caller_swallows_the_owned_signal(self):
        guard = auth._LoginRequestGuard()
        network = Mock(return_value=response(429))
        request = guard.wrap(network)
        for _ in range(2):
            with self.assertRaises(auth._LoginTransportBlocked):
                request("POST", "https://synthetic.invalid/auth")
        network.assert_called_once()
        guard.close()

    def test_bounded_child_failure_envelope_survives_sdk_log_prefix(self):
        for status, code in (("rate_limited", sync.EXIT_RATE_LIMIT), ("provider_blocked", sync.EXIT_SYNC_FAILURE)):
            with self.subTest(status=status):
                payload = {"ok": False, "status": status, "http_status": 429 if status == "rate_limited" else 403,
                           "access_token": "must-not-propagate"}
                exit_code, result = sync.classify_process_result(1, "SDK diagnostic\n" + json.dumps(payload))
                self.assertEqual(exit_code, code)
                self.assertEqual(result["status"], status)
                self.assertNotIn("access_token", result)


if __name__ == "__main__":
    unittest.main()
