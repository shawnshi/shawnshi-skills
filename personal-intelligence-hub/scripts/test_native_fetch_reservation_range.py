"""Regression: native receipt shape supports all eight packet fetch slots."""
from copy import deepcopy

import pytest
import article_broker as broker


def native_access(reservation_id):
    request_sha = "a" * 64
    return {
        "status": "verified", "checked_at": "2026-10-14T00:00:00+00:00",
        "method": "native_readable", "requested_url": "https://example.org/article",
        "final_url": None, "http_status": None, "failure_class": "none",
        "error_code": None, "coverage": "full",
        "native_evidence": {
            "contract_version": "article-broker/3.0", "request_sha256": request_sha,
            "gap_id": "technology-supply", "reservation_id": reservation_id,
            "invocation_id": request_sha + ":technology-supply:" + reservation_id,
            "receipt_sha256": "b" * 64, "readable_text_sha256": "c" * 64,
            "transport_visibility": deepcopy(broker.NATIVE_VISIBILITY),
        },
    }


@pytest.mark.parametrize("slot", range(1, 9))
def test_native_access_accepts_all_packet_slots(slot):
    broker.validate_native_access(native_access(f"fetch-{slot}"))


@pytest.mark.parametrize("reservation_id", ["fetch-0", "fetch-9", "fetch-10", "fetch-01", "fetch-x"])
def test_native_access_rejects_out_of_range_or_malformed_slots(reservation_id):
    with pytest.raises(ValueError, match="native invocation binding invalid"):
        broker.validate_native_access(native_access(reservation_id))


def test_native_access_still_requires_exact_invocation_binding():
    access = native_access("fetch-8")
    access["native_evidence"]["invocation_id"] += "-wrong"
    with pytest.raises(ValueError, match="native invocation binding invalid"):
        broker.validate_native_access(access)
