"""Dashboard 7.2 contract tests: synthetic content only, never personal holdings.

Fixtures use real temporary bytes and mocked issuer URLs; hashes demonstrate
binding, NOT that these sources contain real-world issuer observations.
"""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from dashboard_catalog import DashboardCatalogError, register_dashboard, resolve_dashboards
from dashboard_gate import validate_dashboard
from dashboard_math_gate import validate_math_consistency
from ordinary_equity_contract import BRIDGE_COMPONENTS
from research_brief_gate import validate_research_brief
from save_dashboard import DashboardArchiveError, archive_dashboard, render_markdown
from source_timing_contract import validate_source_timing, verify_source_capture
from test_investment_controls import valid_dashboard
from test_stage4a_etf import synthetic_etf

SCRIPTS = Path(__file__).resolve().parent
DAY = "2026-07-22"
OBSERVED = DAY + "T19:30:00+00:00"
RETRIEVED = DAY + "T20:00:00+00:00"
CUTOFF = DAY + "T21:00:00+00:00"


def timed_source(item, root, name, precision="unknown", valuation_date=DAY):
    item.update(source_locator="https://www.sec.gov/Archives/synthetic-contract/" + name,
                retrieved_at=RETRIEVED, timing_contract_version="1.0",
                publication_precision=precision, published_at=None,
                availability_observed_at=OBSERVED, valuation_date=valuation_date)
    if precision == "exact":
        item["published_at"] = DAY + "T19:00:00+00:00"
    elif precision == "day":
        item.update(publication_date=DAY, publication_utc_offset="+00:00")
    raw = root / (name + ".raw")
    raw.write_bytes(("SYNTHETIC OFFLINE CONTRACT ONLY: " + name).encode("utf-8"))
    item["source_capture_receipt"] = verify_source_capture(raw, source_locator=item["source_locator"], availability_observed_at=OBSERVED, retrieved_at=RETRIEVED)
    item["content_sha256"] = item["source_capture_receipt"]["content_sha256"]


def v72(data):
    data["dashboard_contract_version"] = "7.2"
    data["research_brief"]["source_policy"].update(timing_contract_version="1.0", cutoff_at=CUTOFF)
    for item in data["evidence_items"]:
        if item["source_tier"] == "market_data":
            item["published_at"] = item["observed_at"]
    return data


def component(value, claim, *, unit="currency", na=False, reported=False):
    return {"value": None if na else value, "status": "not_applicable" if na else "included",
            "unit": unit, "currency": "USD", "as_of_date": DAY, "evidence_index": 0,
            "value_type": "not_applicable" if na else "reported_fact" if reported else "analyst_estimate",
            "measurement_basis": "not_applicable" if na else "reported_amount" if reported else "estimated_economic_fair_value",
            "rationale": "Synthetic scoped model assumption; not real-world fact or book=market claim" if not na else "Synthetic source documents no applicable claim",
            "claim_ids": [] if na else [claim]}


def synthetic_stock(root, method="enterprise_value_bridge"):
    data = v72(valid_dashboard())
    data.update(stock_code="SYNTHSTK", stock_name="SYNTHETIC ordinary equity — not externally verified")
    data["research_brief"]["instrument"]["symbol"] = "SYNTHSTK"
    data["evidence_items"][1].update(symbol="SYNTHSTK", fact="Synthetic quote, not live data", source_locator="dataset://pia/synthetic/quote")
    timed_source(data["evidence_items"][0], root, "stock-source")
    data["evidence_items"][0]["fact"] = "Synthetic source for numerical contract only"
    scenarios = data["scenario_analysis"]
    scenarios.update(valuation_contract_version="3.0", valuation_method=method)
    for name, ev in (("bear", 800), ("base", 1000), ("bull", 1200)):
        case = scenarios[name]
        bridge = {"enterprise_value": component(ev, "operations"), "net_debt": component(100, "debt_less_cash", reported=True),
                  "nonoperating_assets": component(50, "investment"), "noncontrolling_interest": component(20, "subsidiary_nci"),
                  "preferred_claims": component(30, "preferred_series_a"), "other_senior_claims": component(None, "none", na=True)}
        case.update(ordinary_equity_bridge=bridge, enterprise_value=ev, net_debt=100,
                    equity_value=ev - 100 + 50 - 20 - 30, diluted_shares=10,
                    share_basis={"basis": "current_diluted", "as_of_date": DAY,
                                 "ordinary_shares": component(10, "ordinary", unit="shares", reported=True), "incremental_shares": []})
        if method in ("DDM", "FCFE"):
            case["ordinary_equity_bridge"] = {key: component(None, key, na=True) for key in BRIDGE_COMPONENTS}
            case.update(enterprise_value="not_applicable", net_debt="not_applicable")
            flow = component(ev * 1.1, "ordinary_distribution_year1")
            flow.update(cash_flow_kind="dividend" if method == "DDM" else "fcfe", years=1, discount_rate=0.1)
            case["ordinary_equity_cashflows"] = [flow]
            case["equity_value"] = ev
        case["per_share_value"] = case["equity_value"] / 10
    return data


def synthetic_timed_etf(root, precision="unknown"):
    data = v72(synthetic_etf())
    data["etf_research"].update(contract_version="1.1", premium_discount_basis="quote_vs_observed_nav")
    data["scenario_analysis"]["valuation_contract_version"] = "etf_nav1.1"
    for item in data["evidence_items"][1:]:
        observation = item["etf_observation"]
        valuation = observation.get("valuation_date", observation.get("period_end", DAY))
        timed_source(item, root, "etf-" + observation["kind"], precision, valuation)
    return data


class DashboardV72Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def assert_valid(self, data):
        self.assertEqual(validate_research_brief(data["research_brief"]), [])
        self.assertEqual(validate_dashboard(data, require_scenarios=True), [])
        self.assertEqual(validate_math_consistency(data), [])

    def test_exact_day_unknown_all_etf_core_fields_positive(self):
        for precision in ("exact", "day", "unknown"):
            with self.subTest(precision=precision):
                data = synthetic_timed_etf(self.root, precision)
                self.assert_valid(data)
                self.assertEqual(data["evidence_items"][2]["publication_precision"], precision)

    def test_bridge_and_direct_equity_recompute_without_fake_ev(self):
        for method in ("enterprise_value_bridge", "DDM", "FCFE"):
            with self.subTest(method=method):
                data = synthetic_stock(self.root, method)
                self.assert_valid(data)
                if method != "enterprise_value_bridge":
                    self.assertEqual(data["scenario_analysis"]["base"]["enterprise_value"], "not_applicable")
                data["scenario_analysis"]["base"]["equity_value"] += 20
                self.assertTrue(validate_math_consistency(data))
                self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_negative_net_debt_is_real_net_cash_not_redefined(self):
        data = synthetic_stock(self.root)
        for name in ("base", "bull", "bear"):
            case = data["scenario_analysis"][name]
            case["ordinary_equity_bridge"]["net_debt"]["value"] = -100
            case["net_debt"] = -100
            case["equity_value"] += 200
            case["per_share_value"] += 20
        self.assert_valid(data)

    def test_component_missing_unknown_sign_unit_currency_fact_basis(self):
        mutations = {
            "missing-nci": lambda c: c["ordinary_equity_bridge"].pop("noncontrolling_interest"),
            "unknown-adjustment": lambda c: c["ordinary_equity_bridge"].update(mystery=component(1, "mystery")),
            "negative-preferred": lambda c: c["ordinary_equity_bridge"]["preferred_claims"].update(value=-30),
            "million-units": lambda c: c["ordinary_equity_bridge"]["net_debt"].update(unit="USD_millions"),
            "currency-mismatch": lambda c: c["ordinary_equity_bridge"]["nonoperating_assets"].update(currency="HKD"),
            "unknown-na": lambda c: c["ordinary_equity_bridge"]["other_senior_claims"].update(status="unknown"),
            "na-zero": lambda c: c["ordinary_equity_bridge"]["other_senior_claims"].update(value=0),
            "book-as-market": lambda c: c["ordinary_equity_bridge"]["nonoperating_assets"].update(value_type="reported_fact", measurement_basis="reported_amount"),
            "missing-source": lambda c: c["ordinary_equity_bridge"]["net_debt"].pop("evidence_index"),
            "duplicate-claims": lambda c: c["ordinary_equity_bridge"]["preferred_claims"].update(claim_ids=["subsidiary_nci"]),
            "unknown-field": lambda c: c["ordinary_equity_bridge"]["net_debt"].update(sign="add"),
            "net-debt-plug": lambda c: c.update(net_debt=150),
            "future-component": lambda c: c["ordinary_equity_bridge"]["net_debt"].update(as_of_date="2999-01-01"),
            "boolean": lambda c: c["ordinary_equity_bridge"]["net_debt"].update(value=True),
        }
        for label, mutate in mutations.items():
            with self.subTest(blocker=label):
                data = synthetic_stock(self.root)
                mutate(data["scenario_analysis"]["base"])
                self.assertTrue(validate_dashboard(data, require_scenarios=True))
                self.assertTrue(validate_math_consistency(data))

    def test_hypothetical_conversion_positive_and_preferred_double_count_negative(self):
        data = synthetic_stock(self.root)
        for name in ("base", "bull", "bear"):
            case = data["scenario_analysis"][name]
            case["ordinary_equity_bridge"]["preferred_claims"] = component(None, "none", na=True)
            case["share_basis"].update(basis="hypothetical_as_converted", incremental_shares=[component(2, "preferred_series_a", unit="shares")])
            case.update(diluted_shares=12, equity_value=case["equity_value"] + 30)
            case["per_share_value"] = case["equity_value"] / 12
        self.assert_valid(data)
        data["scenario_analysis"]["base"]["ordinary_equity_bridge"]["preferred_claims"] = component(30, "preferred_series_a")
        self.assertTrue(any("double counting" in e for e in validate_math_consistency(data)))

    def test_missing_share_date_current_vs_hypothetical_and_wrong_share_sum(self):
        for field, value in (("basis", "unknown"), ("as_of_date", "2999-01-01"), ("incremental_shares", None)):
            data = synthetic_stock(self.root)
            data["scenario_analysis"]["base"]["share_basis"][field] = value
            self.assertTrue(validate_math_consistency(data))
        data = synthetic_stock(self.root)
        data["scenario_analysis"]["base"]["diluted_shares"] = 12
        self.assertTrue(validate_math_consistency(data))

    def test_direct_equity_invalid_discount_units_duplicate_cashflows_and_ev(self):
        mutations = [lambda c: c.update(enterprise_value=1000), lambda c: c["ordinary_equity_cashflows"][0].update(discount_rate=10),
                     lambda c: c["ordinary_equity_cashflows"][0].update(years=-1),
                     lambda c: c["ordinary_equity_cashflows"][0].update(cash_flow_kind="enterprise_terminal_value"),
                     lambda c: c["ordinary_equity_cashflows"].append(copy.deepcopy(c["ordinary_equity_cashflows"][0])),
                     lambda c: c["ordinary_equity_bridge"]["net_debt"].update(status="included", value=0)]
        for mutate in mutations:
            data = synthetic_stock(self.root, "DDM")
            mutate(data["scenario_analysis"]["base"])
            self.assertTrue(validate_math_consistency(data))

    def test_direct_equity_terminal_and_fcfe_negative_cashflow(self):
        data = synthetic_stock(self.root, "FCFE")
        for name in ("base", "bull", "bear"):
            case = data["scenario_analysis"][name]
            flow = case["ordinary_equity_cashflows"][0]
            flow["value"] = -11
            terminal = component((case["equity_value"] + 10) * 1.1**2, "terminal_ordinary")
            terminal.update(cash_flow_kind="terminal_ordinary_equity", years=2, discount_rate=0.1)
            case["ordinary_equity_cashflows"].append(terminal)
        self.assert_valid(data)

    def test_all_precision_modes_reject_future_lookahead_and_naive_observation(self):
        for precision in ("exact", "day", "unknown"):
            for value in ("2026-07-22T21:01:00+00:00", "2999-01-01T00:00:00+00:00", "2026-07-22T19:30:00", "bad", None):
                data = synthetic_timed_etf(self.root, precision)
                item = data["evidence_items"][2]
                item["availability_observed_at"] = value
                item["source_capture_receipt"]["availability_observed_at"] = value
                with self.subTest(precision=precision, value=value):
                    self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_unknown_missing_availability_secondary_source_hash_receipt_negatives(self):
        mutations = {
            "missing-observation": lambda i: i.pop("availability_observed_at"),
            "missing-precision": lambda i: i.pop("publication_precision"),
            "invented-publication": lambda i: i.update(published_at=RETRIEVED),
            "unknown-mode": lambda i: i.update(publication_precision="approximately"),
            "secondary": lambda i: i.update(source_tier="secondary"),
            "missing-hash": lambda i: i.pop("content_sha256"),
            "hash-mismatch": lambda i: i.update(content_sha256="0" * 64),
            "bad-hash": lambda i: i.update(content_sha256="not-a-hash"),
            "missing-receipt": lambda i: i.pop("source_capture_receipt"),
            "source-binding": lambda i: i.update(source_locator="https://www.sec.gov/Archives/other"),
            "future-valuation": lambda i: i.update(valuation_date="2026-07-23"),
            "late-verification": lambda i: i["source_capture_receipt"].update(verified_at="2999-01-01T00:00:00Z"),
        }
        for label, mutate in mutations.items():
            for index in (1, 2, 3, 4):
                with self.subTest(blocker=label, core_index=index):
                    data = synthetic_timed_etf(self.root)
                    mutate(data["evidence_items"][index])
                    self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_day_publication_cannot_satisfy_earlier_intraday_cutoff(self):
        data = synthetic_timed_etf(self.root, "day")
        data["research_brief"]["source_policy"]["cutoff_at"] = DAY + "T10:00:00Z"
        self.assertTrue(validate_dashboard(data, require_scenarios=True))
        for field, value in (("publication_date", "2026-07-23"), ("publication_utc_offset", "bad"), ("published_at", DAY + "T00:00:00Z")):
            data = synthetic_timed_etf(self.root, "day")
            data["evidence_items"][2][field] = value
            self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_day_offset_and_exact_timestamp_order(self):
        data = synthetic_timed_etf(self.root, "day")
        for item in data["evidence_items"][1:]:
            item["publication_utc_offset"] = "+08:00"
        self.assert_valid(data)
        data = synthetic_timed_etf(self.root, "exact")
        data["evidence_items"][2]["published_at"] = DAY + "T19:31:00Z"
        self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_quote_seconds_freshness_unchanged_and_no_availability_substitution(self):
        data = synthetic_timed_etf(self.root)
        quote = data["evidence_items"][0]
        quote.update(market_state="REGULAR", observed_at=DAY + "T19:00:00Z")
        self.assertTrue(any("quote age" in e for e in validate_dashboard(data, require_scenarios=True)))
        quote["availability_observed_at"] = quote["retrieved_at"]
        self.assertTrue(any("substitutes" in e for e in validate_dashboard(data, require_scenarios=True)))

    def test_core_nav_ter_tracking_not_weakened(self):
        for index, field, value in ((2, "kind", "quote"), (2, "unit", "price"), (3, "fee_basis", "management_fee"), (4, "tracking_type", "unknown")):
            data = synthetic_timed_etf(self.root)
            data["evidence_items"][index]["etf_observation"][field] = value
            self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_brief_and_assumptions_intraday_cutoff(self):
        data = synthetic_stock(self.root)
        data["research_brief"]["source_policy"]["cutoff_at"] = "bad"
        self.assertTrue(validate_research_brief(data["research_brief"]))
        data = synthetic_stock(self.root)
        data["scenario_analysis"]["base"]["assumptions"][0]["retrieved_at"] = DAY + "T22:00:00Z"
        self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_explicit_invalid_versions_fail_gate(self):
        for version in (None, 7.2, True, [], {}, "", "7.3"):
            with self.subTest(version=version):
                data = valid_dashboard()
                data["dashboard_contract_version"] = version
                self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_null_version_archive_rejected_without_new_or_existing_root_mutation(self):
        data = valid_dashboard()
        data["dashboard_contract_version"] = None
        for existing in (False, True):
            with self.subTest(existing=existing):
                root = self.root / ("existing" if existing else "new")
                if existing:
                    legacy = valid_dashboard()
                    archive_dashboard(legacy, root, legacy["stock_code"])
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} if existing else {}
                candidate = copy.deepcopy(data)
                with self.assertRaises(DashboardArchiveError):
                    archive_dashboard(data, root, data["stock_code"])
                self.assertEqual(data, candidate)
                self.assertEqual(root.exists(), existing)
                after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} if root.exists() else {}
                self.assertEqual(before, after)

    def test_omitted_legacy_version_archive_is_readable(self):
        data = valid_dashboard()
        self.assertNotIn("dashboard_contract_version", data)
        self.assertEqual(validate_dashboard(data, require_scenarios=True), [])
        root = self.root / "omitted-legacy"
        result = archive_dashboard(data, root, data["stock_code"])
        self.assertTrue(result["index_updated"] and result["is_latest"])
        self.assertTrue(resolve_dashboards(root, [data["stock_code"]])["complete"])
        index = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))
        self.assertEqual(index["dashboards"][data["stock_code"]]["dashboard_contract_version"], "7.1")
        self.assertNotIn("dashboard_contract_version", json.loads(Path(result["json_path"]).read_text(encoding="utf-8")))

    def test_registration_checks_incoming_entry_before_lock_or_index_mutation(self):
        for invalid in ("null-version", "invalid-hash"):
            with self.subTest(invalid=invalid):
                data = valid_dashboard()
                if invalid == "null-version":
                    data["dashboard_contract_version"] = None
                root = self.root / invalid
                generation = root / data["stock_code"] / "generations" / "synthetic"
                generation.mkdir(parents=True)
                source, markdown = generation / "dashboard.json", generation / "dashboard.md"
                canonical = json.dumps(data, ensure_ascii=False, indent=2)
                source.write_bytes(canonical.encode("utf-8"))
                markdown.write_bytes(render_markdown(data, canonical).encode("utf-8"))
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                # Independent entry guard: even if payload validation is bypassed,
                # malformed incoming metadata must never enter the write lock.
                with patch("dashboard_catalog.validate_dashboard", return_value=[]), patch("dashboard_catalog._catalog_lock", side_effect=AssertionError("must reject before mutation")):
                    if invalid == "invalid-hash":
                        with patch("dashboard_catalog._sha256", return_value="bad"), self.assertRaisesRegex(DashboardCatalogError, "dashboard index entry"):
                            register_dashboard(root, data, source, markdown, datetime.now(timezone.utc), "synthetic")
                    else:
                        with self.assertRaisesRegex(DashboardCatalogError, "dashboard index entry"):
                            register_dashboard(root, data, source, markdown, datetime.now(timezone.utc), "synthetic")
                self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_registration_missing_artifacts_does_not_create_root(self):
        root = self.root / "missing-registration"
        data = valid_dashboard()
        generation = root / data["stock_code"] / "generations" / "synthetic"
        with self.assertRaises(DashboardCatalogError):
            register_dashboard(root, data, generation / "dashboard.json", generation / "dashboard.md", datetime.now(timezone.utc), "synthetic")
        self.assertFalse(root.exists())

    def test_timing_utc_and_shanghai_midnight_are_equivalent(self):
        for precision in ("exact", "day", "unknown"):
            for include_retrieval in (False, True):
                with self.subTest(precision=precision, include_retrieval=include_retrieval):
                    data = synthetic_timed_etf(self.root, precision)
                    self.assert_valid(data)
                    equivalent = copy.deepcopy(data)
                    for item in equivalent["evidence_items"][1:]:
                        fields = ["availability_observed_at"] + (["retrieved_at"] if include_retrieval else [])
                        if precision == "exact":
                            fields.append("published_at")
                        for field in fields:
                            item[field] = datetime.fromisoformat(item[field]).astimezone(timezone(timedelta(hours=8))).isoformat()
                            if field in item["source_capture_receipt"]:
                                item["source_capture_receipt"][field] = item[field]
                    self.assert_valid(equivalent)
                    self.assertEqual(validate_dashboard(data), validate_dashboard(equivalent))
        # Exact publication freshness also uses UTC for timing1.0; the
        # equivalent negative offset must not mark a current filing historical.
        stock = synthetic_stock(self.root)
        stock["freshness_flags"]["info_data_status"] = "fresh"
        stock["evidence_items"][0].update(freshness="current", publication_precision="exact", published_at=DAY + "T01:00:00Z")
        self.assert_valid(stock)
        stock["evidence_items"][0]["published_at"] = "2026-07-21T20:00:00-05:00"
        self.assert_valid(stock)

    def test_timing_actual_future_in_shanghai_still_fails(self):
        data = synthetic_timed_etf(self.root)
        item = data["evidence_items"][2]
        for field in ("availability_observed_at", "retrieved_at"):
            item[field] = "2026-07-23T05:01:00+08:00"  # 21:01 UTC exceeds21:00 cutoff.
            item["source_capture_receipt"][field] = item[field]
        self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_legacy_evidence_retains_local_calendar_rule(self):
        data = valid_dashboard()
        data["evidence_items"][0]["retrieved_at"] = "2026-07-23T03:30:00+08:00"
        errors = validate_dashboard(data, require_scenarios=True)
        self.assertTrue(any("retrieved_at cannot be after as_of_date" in error for error in errors))

    def test_versions_do_not_auto_upgrade_or_silently_accept_new_fields(self):
        self.assertEqual(validate_dashboard(valid_dashboard(), require_scenarios=True), [])
        self.assertEqual(validate_dashboard(synthetic_etf(), require_scenarios=True), [])
        legacy = synthetic_etf()
        for item in legacy["evidence_items"][1:]:
            item["published_at"] = "2026-07-22 19:00+00:00"
            item["valuation_date"] = "2026-07-21"  # Old optional metadata, not a timing-version switch.
        self.assertEqual(validate_dashboard(legacy, require_scenarios=True), [])
        for method in ("enterprise_value_bridge", "DDM"):
            data = synthetic_stock(self.root, method)
            data.pop("dashboard_contract_version")
            self.assertTrue(validate_dashboard(data, require_scenarios=True))
        data = synthetic_timed_etf(self.root)
        data["scenario_analysis"]["valuation_contract_version"] = "etf_nav1.0"
        self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_render_save_index_load_roundtrip_isolated_and_source_unchanged(self):
        for name, builder in (("stock", synthetic_stock), ("etf", synthetic_timed_etf)):
            data = builder(self.root)
            before = json.dumps(data, ensure_ascii=False, sort_keys=True)
            root = self.root / name
            result = archive_dashboard(data, root, data["stock_code"])
            loaded = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(data, loaded)
            self.assertEqual(before, json.dumps(data, ensure_ascii=False, sort_keys=True))
            index = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))
            self.assertEqual(index["dashboards"][data["stock_code"]]["dashboard_contract_version"], "7.2")
            with patch("source_timing_contract.verify_source_capture", side_effect=AssertionError("no implicit verification")):
                report = resolve_dashboards(root, [data["stock_code"]])
            self.assertTrue(report["complete"], report)
            visible = render_markdown(data, json.dumps(data)).split("\n<details><summary>")[0]
            for field in ("publication_precision", "availability_observed_at", "source_capture_receipt", "verified_at"):
                self.assertIn(field, visible)
            if name == "stock":
                self.assertIn("ordinary_equity_bridge", visible)
            else:
                self.assertIn("quote_vs_observed_nav", visible)

    def test_catalog_rejects_v72_relabeling_and_retains_older_entry(self):
        root = self.root / "mixed"
        old = valid_dashboard()
        old_result = archive_dashboard(old, root, old["stock_code"])
        old_bytes = Path(old_result["json_path"]).read_bytes()
        data = synthetic_timed_etf(self.root)
        result = archive_dashboard(data, root, data["stock_code"])
        self.assertTrue(resolve_dashboards(root, [old["stock_code"], data["stock_code"]])["complete"])
        self.assertEqual(Path(old_result["json_path"]).read_bytes(), old_bytes)
        index_path = Path(result["index_path"])
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(index["dashboards"][old["stock_code"]]["dashboard_contract_version"], "7.1")
        index["dashboards"][data["stock_code"]]["dashboard_contract_version"] = "7.1"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        self.assertFalse(resolve_dashboards(root, [data["stock_code"]])["complete"])

    def test_non_strict_load_cannot_drop_v72_quote_or_scenarios(self):
        for field in ("scenario_analysis", "evidence_items"):
            data = synthetic_stock(self.root)
            if field == "evidence_items":
                data[field] = data[field][:1]
            else:
                data.pop(field)
            self.assertTrue(validate_dashboard(data))

    def test_model_estimate_can_use_older_report_not_claim_future_cashflows_as_fact(self):
        data = synthetic_stock(self.root, "DDM")
        # Model valuations dated today may reference older observations;
        # reported share facts keep the source observation date.
        data["evidence_items"][0]["valuation_date"] = "2026-07-21"
        for name in ("base", "bull", "bear"):
            shares = data["scenario_analysis"][name]["share_basis"]
            shares["as_of_date"] = "2026-07-21"
            shares["ordinary_shares"]["as_of_date"] = "2026-07-21"
        self.assert_valid(data)
        flow = data["scenario_analysis"]["base"]["ordinary_equity_cashflows"][0]
        flow.update(value_type="reported_fact", measurement_basis="reported_market_value")
        self.assertTrue(validate_math_consistency(data))

    def test_exact_publication_cannot_precede_valuation_date(self):
        data = synthetic_timed_etf(self.root, "exact")
        item = data["evidence_items"][2]
        item["published_at"] = "2026-07-20T19:00:00Z"
        self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_invalid_new_save_does_not_publish_or_mutate_candidate(self):
        data = synthetic_timed_etf(self.root)
        data["evidence_items"][2].pop("availability_observed_at")
        root = self.root / "blocked"
        before = copy.deepcopy(data)
        with self.assertRaises(DashboardArchiveError):
            archive_dashboard(data, root, data["stock_code"])
        self.assertFalse(root.exists())
        self.assertEqual(data, before)

    def test_fresh_python_process_gates_for_three_builders(self):
        for name, data in (("stock", synthetic_stock(self.root)), ("ddm", synthetic_stock(self.root, "DDM")), ("etf", synthetic_timed_etf(self.root))):
            path = self.root / (name + ".json")
            path.write_text(json.dumps(data), encoding="utf-8")
            for script, args in (("dashboard_gate.py", ["--strict-current-contract"]), ("dashboard_math_gate.py", [])):
                result = subprocess.run([sys.executable, "-B", str(SCRIPTS / script), str(path), *args], capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(json.loads(result.stdout)["valid"])


class SourceCaptureVerificationTests(unittest.TestCase):
    def test_recompute_actual_bytes_and_receipt_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = synthetic_timed_etf(root)
            item = data["evidence_items"][2]
            receipt = item["source_capture_receipt"]
            path = Path(receipt["raw_artifact"])
            kwargs = {"source_locator": item["source_locator"], "availability_observed_at": OBSERVED, "retrieved_at": RETRIEVED, "expected_sha256": item["content_sha256"], "expected_receipt": receipt}
            self.assertEqual(verify_source_capture(path, **kwargs)["content_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            path.write_bytes(b"changed synthetic NAV bytes")
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                verify_source_capture(path, **kwargs)

    def test_missing_nonregular_empty_oversize_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kwargs = {"source_locator": "https://www.sec.gov/Archives/synthetic", "availability_observed_at": OBSERVED, "retrieved_at": RETRIEVED}
            with self.assertRaises(OSError):
                verify_source_capture(root / "missing", **kwargs)
            with self.assertRaises(ValueError):
                verify_source_capture(root, **kwargs)
            file = root / "empty"
            file.write_bytes(b"")
            with self.assertRaises(ValueError):
                verify_source_capture(file, **kwargs)
            file.write_bytes(b"12345")
            with patch("source_timing_contract.MAX_CAPTURE_BYTES", 4), self.assertRaises(ValueError):
                verify_source_capture(file, **kwargs)

    def test_receipt_locator_hash_time_reverification_mismatches(self):
        with tempfile.TemporaryDirectory() as temp:
            item = synthetic_timed_etf(Path(temp))["evidence_items"][2]
            receipt = item["source_capture_receipt"]
            for field, value in (("source_locator", "https://www.sec.gov/other"), ("content_sha256", "0" * 64), ("availability_observed_at", DAY + "T01:00:00Z"), ("verified_at", "2999-01-01T00:00:00Z")):
                altered = dict(receipt, **{field: value})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    verify_source_capture(receipt["raw_artifact"], source_locator=item["source_locator"], availability_observed_at=OBSERVED, retrieved_at=RETRIEVED, expected_receipt=altered)

    def test_verification_time_does_not_backfill_historical_availability(self):
        with tempfile.TemporaryDirectory() as temp:
            data = synthetic_timed_etf(Path(temp))
            item = data["evidence_items"][2]
            self.assertNotEqual(item["source_capture_receipt"]["verified_at"], item["availability_observed_at"])
            self.assertIsNone(item["published_at"])
            self.assertEqual(validate_source_timing(item, data["research_brief"]["source_policy"]), [])
            with self.assertRaises(ValueError):
                verify_source_capture(item["source_capture_receipt"]["raw_artifact"], source_locator=item["source_locator"], availability_observed_at="2999-01-01T00:00:00Z", retrieved_at=RETRIEVED)


if __name__ == "__main__":
    unittest.main()
