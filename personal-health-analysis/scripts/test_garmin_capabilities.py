import unittest
import threading
from datetime import datetime, timedelta, timezone

from garmin_capabilities import (
    CapabilityError,
    consume_capability,
    issue_capability,
    require_capability,
)


class ScopedCapabilityTests(unittest.TestCase):
    def test_plain_bool_and_lookalike_are_not_capabilities(self):
        for candidate in (True, False, object(), {"scope": "network"}):
            with self.subTest(candidate=type(candidate).__name__):
                with self.assertRaisesRegex(
                    CapabilityError, "capability_object_required"
                ):
                    require_capability(
                        candidate,
                        scope="network",
                        operation="garmin_auth",
                    )

    def test_capability_is_immutable_and_module_issued(self):
        capability = issue_capability(
            scope="network",
            operation="garmin_auth",
        )
        with self.assertRaises(AttributeError):
            capability.scope = "sync"
        require_capability(
            capability,
            scope="network",
            operation="garmin_auth",
        )

    def test_wrong_scope_and_operation_are_rejected(self):
        capability = issue_capability(
            scope="network",
            operation="garmin_auth",
        )
        with self.assertRaisesRegex(CapabilityError, "capability_scope_mismatch"):
            require_capability(
                capability,
                scope="sync",
                operation="garmin_auth",
            )
        with self.assertRaisesRegex(
            CapabilityError, "capability_operation_mismatch"
        ):
            require_capability(
                capability,
                scope="network",
                operation="garmindb_sync",
            )

    def test_expired_capability_is_rejected(self):
        issued_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        capability = issue_capability(
            scope="network",
            operation="garmin_auth",
            ttl_seconds=1,
            now=issued_at,
        )
        with self.assertRaisesRegex(CapabilityError, "capability_expired"):
            require_capability(
                capability,
                scope="network",
                operation="garmin_auth",
                now=issued_at + timedelta(seconds=2),
            )

    def test_request_binding_rejects_scope_drift_without_exposing_values(self):
        request = {"metric": "hrv", "date": "2026-08-08"}
        capability = issue_capability(
            scope="health_data",
            operation="health_data_live",
            request=request,
        )
        require_capability(
            capability,
            scope="health_data",
            operation="health_data_live",
            request=request,
        )
        self.assertNotIn("2026-08-08", repr(capability))
        with self.assertRaisesRegex(CapabilityError, "capability_request_mismatch"):
            require_capability(
                capability,
                scope="health_data",
                operation="health_data_live",
                request={"metric": "sleep", "date": "2026-08-08"},
            )

    def test_consumed_capability_cannot_be_reused(self):
        request = {"activity_id": 123}
        capability = issue_capability(
            scope="download",
            operation="activity_download",
            request=request,
        )
        consume_capability(
            capability,
            scope="download",
            operation="activity_download",
            request=request,
        )
        with self.assertRaisesRegex(CapabilityError, "capability_consumed"):
            consume_capability(
                capability,
                scope="download",
                operation="activity_download",
                request=request,
            )

    def test_concurrent_consumers_allow_exactly_one_success(self):
        request = {"metric": "sleep", "date": "2026-08-08"}
        capability = issue_capability(
            scope="health_data",
            operation="health_data_live",
            request=request,
        )
        barrier = threading.Barrier(3)
        outcomes = []

        def worker():
            barrier.wait()
            try:
                consume_capability(
                    capability,
                    scope="health_data",
                    operation="health_data_live",
                    request=request,
                )
                outcomes.append("ok")
            except CapabilityError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["ok", "capability_consumed"])


if __name__ == "__main__":
    unittest.main()
