"""Synthetic ETF contract fixtures; no real-world identity or source verification."""
import hashlib
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dashboard_catalog import resolve_dashboards
from dashboard_gate import validate_dashboard
from dashboard_math_gate import validate_math_consistency
from save_dashboard import DashboardArchiveError, archive_dashboard, render_markdown
from test_investment_controls import valid_dashboard

ROOT = Path(__file__).resolve().parent.parent


def synthetic_etf():
    data = valid_dashboard()
    data.update(stock_name="SYNTHETIC ETF — not externally verified", stock_code="SYNTHETF", market_type="ETF")
    data.pop("earnings_snapshot")
    brief = data["research_brief"]
    brief["instrument"].update(symbol="SYNTHETF", asset_type="etf")
    brief["method_profile"] = "etf_research"
    brief["research_question"] = "Synthetic NAV reference stress test, not a forecast"
    brief["market_consensus"].update(metric="nav_per_unit", value=100, unit="USD/unit", source_locator="dataset://pia/synthetic/nav", reference_type="reported_nav")
    brief["core_hypothesis"].update(statement="Explicit unchanged NAV reference assumption, not consensus", metric="nav_per_unit", independent_estimate={"value": 100, "unit": "USD/unit"}, expected_gap={"absolute": 0, "direction": "equal"})
    brief["key_variables"] = ["nav_per_unit", "index_return", "currency_return"]
    data["freshness_flags"]["info_data_status"] = "fresh"
    quote = data["evidence_items"][1]
    quote.update(symbol="SYNTHETF", price=101, source_locator="dataset://pia/synthetic/quote", fact="Synthetic quote, not live data")
    data["dashboard"]["data_perspective"]["price_position"]["current_price"] = 101
    data["dashboard"]["data_perspective"].update(valuation="not_applicable: corporate valuation; NAV stress only", atr_14="not_assessed", trend_status={"status": "not_assessed"})
    data["evidence_items"] = [quote]
    etf = {"contract_version": "1.0", "quote_evidence_index": 0, "premium_discount": 0.01, "premium_discount_basis": "quote_vs_last_published_nav", "coverage_scope": "Synthetic core ETF evidence and explicit ancillary gaps"}
    data["etf_research"] = etf

    def observation(kind, **values):
        record = {"kind": kind, "symbol": "SYNTHETF", "market": "US", "currency": "USD", **values}
        item = {"fact": "Synthetic " + kind, "connection": "Offline contract test", "deduction": "Not external verification", "source_type": "company_primary", "source_tier": "company_primary", "source_locator": "dataset://pia/synthetic/" + kind, "published_at": "2026-07-22T19:00:00+00:00", "retrieved_at": "2026-07-22T20:00:00+00:00", "content_sha256": "4" * 64, "as_of_date": "2026-07-22", "freshness": "current", "confidence": "high", "independent_source_count": 1, "etf_observation": record}
        etf[kind] = {"evidence_index": len(data["evidence_items"])}
        data["evidence_items"].append(item)

    observation("identity", asset_type="etf", benchmark="SYNTHINDEX", replication_method="physical")
    observation("nav", value=100, unit="currency_per_unit", valuation_date="2026-07-21")
    observation("fees", value=0.002, unit="ratio_per_year", fee_basis="total_expense_ratio")
    observation("tracking", value=-0.002, unit="ratio", tracking_type="tracking_difference", period_start="2025-07-21", period_end="2026-07-21", benchmark="SYNTHINDEX", methodology="Fund total return minus index total return; same currency")
    for key in ("holdings_concentration", "liquidity", "assets", "share_changes", "corporate_actions"):
        etf[key] = {"status": "gap", "reason": "Synthetic fixture intentionally has no " + key}
    data["data_gaps"] = [key + ": " + etf[key]["reason"] for key in ("holdings_concentration", "liquidity", "assets", "share_changes", "corporate_actions")]
    scenarios = data["scenario_analysis"]
    scenarios.update(valuation_contract_version="etf_nav1.0", valuation_method="nav_index_currency_stress")
    for name, index_return in (("base", 0), ("bull", 0.1), ("bear", -0.1)):
        case = scenarios[name]
        for field in ("enterprise_value", "net_debt", "equity_value", "diluted_shares"):
            case[field] = "not_applicable"
        source = {"source_locator": "dataset://pia/synthetic/assumptions", "retrieved_at": "2026-07-22T20:10:00+00:00", "content_sha256": "5" * 64, "as_of_date": "2026-07-22"}
        case.update(nav_per_unit=100, per_share_value=100 * (1 + index_return), assumptions=[dict(source, name="index_return", value=index_return, unit="ratio"), dict(source, name="currency_return", value=0, unit="ratio")], falsification_conditions=["Stress assumptions are not realized; not a forecast"])
    scenarios["sensitivity"] = [dict(source, parameter="index_return", low=-0.1, base=0, high=0.1, unit="ratio")]
    return data


class EtfContractTests(unittest.TestCase):
    def test_complete_strict_etf_and_math(self):
        data = synthetic_etf()
        self.assertEqual(validate_dashboard(data, require_scenarios=True), [])
        self.assertEqual(validate_math_consistency(data), [])

    def test_actual_synthetic_save_and_render(self):
        data = synthetic_etf()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "synthetic.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            result = archive_dashboard(json.loads(source.read_text(encoding="utf-8")), root / "archive", "SYNTHETF")
            self.assertTrue(result)
            text = render_markdown(data, json.dumps(data))
            self.assertIn("ETF NAV", text)
            self.assertIn("quote_vs_last_published_nav", text)
            self.assertIn("currency_return", text)

    def test_missing_and_mismatched_etf_inputs(self):
        mutations = [
            lambda d: d.pop("etf_research"),
            lambda d: d["research_brief"].update(method_profile="quality_equity"),
            lambda d: d["research_brief"]["instrument"].update(asset_type="stock"),
            lambda d: d.update(market_type="美股"),
            lambda d: d["evidence_items"][1]["etf_observation"].update(asset_type="stock"),
            lambda d: d["evidence_items"][2]["etf_observation"].update(unit="total_currency"),
            lambda d: d["evidence_items"][2]["etf_observation"].update(currency="HKD"),
            lambda d: d["evidence_items"][2]["etf_observation"].update(valuation_date="2026-07-10"),
            lambda d: d["evidence_items"][2]["etf_observation"].update(valuation_date="2026-07-23"),
            lambda d: d["evidence_items"][2].update(published_at="2026-07-23T00:00:00+00:00"),
            lambda d: d["evidence_items"][2].pop("content_sha256"),
            lambda d: d["evidence_items"][2].update(freshness="unknown"),
            lambda d: d["etf_research"]["nav"].update(evidence_index=1),
            lambda d: d["evidence_items"][4]["etf_observation"].update(period_start="2026-07-22"),
            lambda d: d["evidence_items"][4]["etf_observation"].update(tracking_type="unknown"),
            lambda d: d["scenario_analysis"]["base"].update(enterprise_value=0),
            lambda d: d["etf_research"].update(premium_discount_basis="same_time"),
            lambda d: d["etf_research"].pop("liquidity"),
        ]
        for mutate in mutations:
            data = synthetic_etf()
            mutate(data)
            with self.subTest(mutation=mutate):
                self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_wrong_math_rejected_by_both_gates(self):
        for field in ("premium_discount", "per_share_value", "nav_per_unit"):
            data = synthetic_etf()
            if field == "premium_discount":
                data["etf_research"][field] = 0.2
            else:
                data["scenario_analysis"]["base"][field] = 123
            self.assertTrue(validate_math_consistency(data))
            self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_weekend_t_plus_one_nav_and_closed_quote(self):
        data = json.loads(json.dumps(synthetic_etf()).replace("2026-07-22", "2026-07-26"))
        # Sunday research; Friday NAV published Saturday (T+1), Friday close.
        nav = data["evidence_items"][2]
        nav["etf_observation"]["valuation_date"] = "2026-07-24"
        nav["published_at"] = "2026-07-25T19:00:00+00:00"
        data["evidence_items"][0]["observed_at"] = "2026-07-24T20:00:00+00:00"
        self.assertEqual(validate_dashboard(data, require_scenarios=True), [])
        visible = render_markdown(data, json.dumps(data)).split("<details>", 1)[0]
        comparison_text = visible.split("### 报价 / NAV 比较两端", 1)[1]
        match = re.search(r"```json\n(.*?)\n```", comparison_text, re.S)
        assert match is not None
        comparison = json.loads(match.group(1))
        self.assertEqual(comparison["premium_discount_basis"], "quote_vs_last_published_nav")
        self.assertEqual(comparison["quote"]["price"], 101)
        self.assertEqual(comparison["quote"]["currency"], "USD")
        self.assertEqual(comparison["quote"]["observed_at"], "2026-07-24T20:00:00+00:00")
        self.assertEqual(comparison["nav"]["value"], 100)
        self.assertEqual(comparison["nav"]["currency"], "USD")
        self.assertEqual(comparison["nav"]["valuation_date"], "2026-07-24")
        self.assertEqual(comparison["nav"]["published_at"], "2026-07-25T19:00:00+00:00")
        data["evidence_items"][0]["market_state"] = "REGULAR"
        self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_all_claimed_ancillary_coverage_can_close(self):
        data = synthetic_etf()
        block = data["etf_research"]
        for key in ("holdings_concentration", "liquidity", "assets", "share_changes", "corporate_actions"):
            item = json.loads(json.dumps(data["evidence_items"][1]))
            item["etf_observation"] = {"kind": key, "symbol": "SYNTHETF", "market": "US", "currency": "USD", "summary": "Synthetic observation as of 2026-07-21: scoped full sample; no real-world verification"}
            block[key] = {"status": "evidenced", "evidence_index": len(data["evidence_items"])}
            data["evidence_items"].append(item)
        data["data_gaps"] = []
        self.assertEqual(validate_dashboard(data, require_scenarios=True), [])
        self.assertEqual(validate_math_consistency(data), [])

    def test_bad_units_sources_and_numeric_types_fail(self):
        mutations = [
            lambda d: d["evidence_items"][3]["etf_observation"].update(unit="percent"),
            lambda d: d["evidence_items"][3]["etf_observation"].update(fee_basis="management_fee"),
            lambda d: d["evidence_items"][3]["etf_observation"].update(value=float("nan")),
            lambda d: d["evidence_items"][2]["etf_observation"].update(symbol="STOCK"),
            lambda d: d["evidence_items"][2].update(source_locator="https://example.com/nav"),
            lambda d: d["evidence_items"][2].update(published_at="2026-07-22T21:00:00+00:00"),
            lambda d: d["etf_research"]["nav"].update(evidence_index=True),
            lambda d: d["scenario_analysis"]["base"]["assumptions"][0].update(unit="percent"),
            lambda d: d["scenario_analysis"]["base"]["assumptions"][0].update(value="0"),
            lambda d: d["scenario_analysis"]["sensitivity"][0].update(base=0.01),
            lambda d: d["scenario_analysis"]["sensitivity"][0].update(high=-0.1),
        ]
        for mutate in mutations:
            data = synthetic_etf()
            mutate(data)
            self.assertTrue(validate_dashboard(data, require_scenarios=True))

    def test_etf_source_literals_and_canonical_archive_hash(self):
        data = synthetic_etf()
        hostile = '<em>physical</em> [unverified](https://www.sec.gov) `x` ``` ``````\n# heading\n</details><script>alert(1)</script> & \\ [ref]: https://www.sec.gov'
        data["evidence_items"][1]["etf_observation"]["replication_method"] = hostile
        data["etf_research"]["coverage_scope"] = hostile
        data["scenario_analysis"]["base"]["falsification_conditions"] = [hostile]
        self.assertEqual(validate_dashboard(data, require_scenarios=True), [])
        canonical = json.dumps(data, indent=2, ensure_ascii=False)
        before = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.json"
            source.write_bytes(canonical.encode("utf-8"))
            result = archive_dashboard(data, root / "archive", "SYNTHETF")
            text = Path(result["markdown_path"]).read_text(encoding="utf-8")
            visible = text.split("\n<details><summary>", 1)[0]
            block = visible.split("## ETF NAV 与覆盖边界", 1)[1].split("## 🔍", 1)[0]
            # Every JSON block has a fence longer than any source backtick run.
            blocks = re.findall(r"^(`{3,})json\n(.*?)\n\1$", block, re.M | re.S)
            self.assertGreaterEqual(len(blocks), 7)
            values = []
            for fence, content in blocks:
                self.assertLess(max((len(run) for run in re.findall(r"`+", content)), default=0), len(fence))
                values.append(json.loads(content))
            outside = re.sub(r"^(`{3,})json\n(.*?)\n\1$", "", block, flags=re.M | re.S)
            self.assertNotIn("<em>", outside)
            self.assertNotIn("[unverified]", outside)
            self.assertNotIn("<script>", outside)
            identity = next(value for value in values if value.get("etf_observation", {}).get("kind") == "identity")
            self.assertEqual(identity["etf_observation"]["replication_method"], hostile)
            self.assertIn(f"```json\n{canonical}\n```", text.split("\n<details><summary>", 1)[1])
            archived = Path(result["json_path"]).read_bytes()
            self.assertEqual(archived, (canonical + "\n").encode("utf-8"))
            index = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))
            self.assertEqual(index["dashboards"]["SYNTHETF"]["json_sha256"], hashlib.sha256(archived).hexdigest())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            self.assertEqual(json.dumps(data, indent=2, ensure_ascii=False), canonical)

    def test_stock_archive_contracts_remain_unchanged(self):
        data = valid_dashboard()
        self.assertEqual(validate_dashboard(data, require_scenarios=True), [])
        data.pop("scenario_analysis")
        self.assertEqual(validate_dashboard(data), [])
        self.assertTrue(validate_dashboard(data, require_scenarios=True))


class ArchiveVersionCompatibilityTests(unittest.TestCase):
    def legacy_archive(self, root, header="7.0", entry_version="7.0"):
        data = valid_dashboard()
        data.pop("scenario_analysis")  # Readable legacy research is not a strict-current pass.
        symbol = data["stock_code"]
        generation = root / symbol / "generations" / "legacy"
        generation.mkdir(parents=True)
        canonical = json.dumps(data, indent=2, ensure_ascii=False)
        json_file, markdown_file = generation / "dashboard.json", generation / "dashboard.md"
        json_file.write_bytes(canonical.encode("utf-8"))
        markdown_file.write_bytes(render_markdown(data, canonical).encode("utf-8"))
        entry = {"stock_code": symbol, "dashboard_contract_version": entry_version, "generation_id": "legacy", "json_path": json_file.relative_to(root).as_posix(), "markdown_path": markdown_file.relative_to(root).as_posix(), "json_sha256": hashlib.sha256(json_file.read_bytes()).hexdigest(), "markdown_sha256": hashlib.sha256(markdown_file.read_bytes()).hexdigest(), "archived_at": "2026-07-22T21:00:00+00:00"}
        index = {"schema_version": 3, "dashboard_contract_version": header, "updated_at": entry["archived_at"], "dashboards": {symbol: entry}}
        (root / "dashboard_index.json").write_text(json.dumps(index), encoding="utf-8")
        return data, index, {path: path.read_bytes() for path in (json_file, markdown_file)}

    def test_7_0_and_7_1_headers_and_entries_read_independently(self):
        for header in ("7.0", "7.1"):
            for version in ("7.0", "7.1"):
                with self.subTest(header=header, version=version), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    data, _, old_files = self.legacy_archive(root, header, version)
                    report = resolve_dashboards(root, [data["stock_code"]])
                    self.assertTrue(report["complete"], report)
                    self.assertEqual(report["dashboard_contract_version"], "7.1")
                    self.assertEqual(report["entries"][0]["dashboard_contract_version"], version)
                    self.assertTrue(validate_dashboard(data, require_scenarios=True))
                    for path, original in old_files.items():
                        self.assertEqual(path.read_bytes(), original)

    def test_mixed_append_preserves_old_version_and_immutable_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, old_index, old_files = self.legacy_archive(root)
            result = archive_dashboard(synthetic_etf(), root, "SYNTHETF")
            self.assertTrue(result["index_updated"])
            index = json.loads((root / "dashboard_index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["dashboard_contract_version"], "7.1")
            self.assertEqual(index["dashboards"][data["stock_code"]], old_index["dashboards"][data["stock_code"]])
            self.assertEqual(index["dashboards"]["SYNTHETF"]["dashboard_contract_version"], "7.1")
            report = resolve_dashboards(root, [data["stock_code"], "SYNTHETF"])
            self.assertTrue(report["complete"], report)
            self.assertEqual([entry["dashboard_contract_version"] for entry in report["entries"]], ["7.0", "7.1"])
            for path, original in old_files.items():
                self.assertEqual(path.read_bytes(), original)

    def test_sort_uses_timestamp_and_generation_not_contract_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data, _, old_files = self.legacy_archive(root)
            now = datetime(2026, 7, 22, 21, tzinfo=timezone.utc)
            for generation, hour in (("zz-older", 20), ("aa-tied", 21)):
                result = archive_dashboard(valid_dashboard(), root, data["stock_code"], now=now.replace(hour=hour), generation_id=generation)
                self.assertFalse(result["index_updated"])
                self.assertEqual(resolve_dashboards(root, [data["stock_code"]])["entries"][0]["dashboard_contract_version"], "7.0")
            result = archive_dashboard(valid_dashboard(), root, data["stock_code"], now=now, generation_id="zz-tied")
            self.assertTrue(result["index_updated"])
            self.assertEqual(resolve_dashboards(root, [data["stock_code"]])["entries"][0]["generation_id"], "zz-tied")
            for path, original in old_files.items():
                self.assertEqual(path.read_bytes(), original)

    def test_bad_versions_and_invalid_indexes_rejected_without_overwrite(self):
        mutations = []
        for version in ("6.9", "7.2", "arbitrary", 7.0, None, [], {}):
            mutations.extend((
                lambda index, symbol, value=version: index.update(dashboard_contract_version=value),
                lambda index, symbol, value=version: index["dashboards"][symbol].update(dashboard_contract_version=value),
            ))
        mutations.extend((
            lambda index, symbol: index.update(schema_version=2),
            lambda index, symbol: index.update(updated_at="invalid"),
            lambda index, symbol: index["dashboards"][symbol].update(json_sha256="bad"),
        ))
        for number, mutate in enumerate(mutations):
            with self.subTest(case=number), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                data, index, old_files = self.legacy_archive(root)
                mutate(index, data["stock_code"])
                index_file = root / "dashboard_index.json"
                index_file.write_text(json.dumps(index), encoding="utf-8")
                before = index_file.read_bytes()
                self.assertFalse(resolve_dashboards(root, [data["stock_code"]])["complete"])
                with self.assertRaises(DashboardArchiveError):
                    archive_dashboard(synthetic_etf(), root, "SYNTHETF")
                self.assertEqual(index_file.read_bytes(), before)
                for path, original in old_files.items():
                    self.assertEqual(path.read_bytes(), original)


class TaskApplicabilityTests(unittest.TestCase):
    def test_scoped_tasks_do_not_require_company_forecasts(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("基础事实与披露", skill)
        self.assertIn("不要求 Brief、预期差或公司估值", skill)
        self.assertIn("不得称为完整深度研究", skill)
        company = (ROOT / "references/company-research.md").read_text(encoding="utf-8")
        self.assertIn("etf_nav1.0", company)
        self.assertIn("not_applicable", company)
        self.assertIn("5 个日历日", company)


if __name__ == "__main__":
    unittest.main()
