"""Automated primary-source evidence collection for the Daily Sync Thesis red team.

Why this exists: the Thesis evidence package must bind real publication times and
content hashes for every holding plus macro, sector and regulatory coverage.  Doing
that by hand each run is slow and easy to get wrong, so this command fetches the
machine-readable disclosure channels, records per-channel health, and refuses to
emit an item from a channel that answered without usable data.
"""

from __future__ import annotations

import argparse
import datetime
import json
import time
from pathlib import Path
from typing import Any

import requests

import evidence_channels as ec
from status_contract import STATUS_COMPLETE, STATUS_INCOMPLETE, exit_code_for

SCHEMA_VERSION = "pia_evidence_collection_v1"
DECISION_SCOPE = "advisory"
SCOPES = ("macro", "sector", "regulatory")
MATERIAL_SEC_FORMS = {"10-K", "10-Q", "8-K", "20-F", "6-K", "40-F", "DEF 14A", "S-1", "424B4"}


def _timestamp(value: str, label: str) -> float:
    try:
        parsed = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must carry a timezone: {value!r}")
    return parsed.timestamp()


def _parse_scope_source(spec: str) -> dict[str, str]:
    if "=" not in spec or "@" not in spec.split("=", 1)[1]:
        raise ValueError(
            "scope source must be <macro|sector|regulatory>=<https url>@<published_at>")
    scope, rest = spec.split("=", 1)
    scope = scope.strip().lower()
    url, published_at = rest.rsplit("@", 1)
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; expected one of {', '.join(SCOPES)}")
    if not url.strip().startswith(("http://", "https://")):
        raise ValueError(f"scope source must be a public http(s) URL: {url!r}")
    _timestamp(published_at, f"scope_source[{scope}].published_at")
    return {"scope": scope, "url": url.strip(), "published_at": published_at.strip()}


def _symbol_key(symbol: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in symbol.strip().upper())


def _material_forms(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in records if str(row.get("form") or "") in MATERIAL_SEC_FORMS]


def _choose(records: list[dict[str, Any]], window_start: float, window_end: float
            ) -> dict[str, Any] | None:
    inside = []
    for row in records:
        try:
            stamp = _timestamp(str(row.get("published_at")), "record.published_at")
        except ValueError:
            continue
        if window_start <= stamp <= window_end:
            inside.append((stamp, row))
    if not inside:
        return None
    inside.sort(key=lambda item: item[0])
    return inside[-1][1]


def _attempt_channel(
    adapter: Any,
    *,
    max_attempts: int,
    retry_delay_seconds: float,
    sleep: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a channel adapter with a bounded retry on a broken verdict.

    A channel that answered HTTP 200 without usable data (rate limit, session
    cookie, WAF) is often transient; retrying a bounded number of times keeps a
    routine run complete without ever converting a persistent failure into
    "no announcements".  Empty is never retried: it is a faithful answer.
    """
    attempts = 0
    while True:
        result = adapter(**kwargs)
        attempts += 1
        if result.get("health") != ec.HEALTH_BROKEN or attempts >= max_attempts:
            result["attempts_made"] = attempts
            return result
        fetcher = kwargs.get("fetcher")
        if fetcher is not None:
            # A retry must never be served the cached broken body.
            fetcher.bypass_cache = True
        sleep(retry_delay_seconds)


def collect_symbol(
    fetcher: ec.ChannelFetcher,
    *,
    symbol: str,
    window_start: float,
    window_end: float,
    evidence_dir: Path,
    max_attempts: int = 2,
    retry_delay_seconds: float = 2.0,
    sleep: Any = None,
) -> dict[str, Any]:
    """Try the applicable channels for one symbol and return a per-symbol report."""
    report: dict[str, Any] = {"symbol": symbol, "attempts": [], "records_found": 0,
                              "chosen": None, "artifact": None,
                              "document_retrieval": None, "health": ec.HEALTH_BROKEN}
    date_from = datetime.datetime.fromtimestamp(window_start, datetime.timezone.utc
                                                ).date().isoformat()
    date_to = datetime.datetime.fromtimestamp(window_end, datetime.timezone.utc).date().isoformat()
    suffix = symbol.rsplit(".", 1)[1].upper() if "." in symbol else ""
    code = symbol.split(".", 1)[0]

    listings: list[dict[str, Any]] = []
    sleep_fn = sleep or time.sleep
    if suffix in {"SS", "SZ"}:
        listings.append(_attempt_channel(
            ec.cninfo_fulltext, max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds, sleep=sleep_fn,
            fetcher=fetcher, code=code, date_from=date_from, date_to=date_to))
        if suffix == "SZ":
            listings.append(_attempt_channel(
                ec.szse_announcements, max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds, sleep=sleep_fn,
                fetcher=fetcher, code=code, date_from=date_from, date_to=date_to))
    elif suffix == "HK":
        prefix = ec.hkex_stock_id(fetcher, code=code)
        report["attempts"].append({"channel": "hkex_prefix", "health": prefix["health"],
                                  "records": 0, "error": None, "url": None, "reused": None})
        if prefix["health"] == ec.HEALTH_OK and prefix["stock_id"] is not None:
            listings.append(ec.hkex_news(fetcher, stock_id=prefix["stock_id"],
                                         date_from=date_from.replace("-", ""),
                                         date_to=date_to.replace("-", "")))
    else:
        lookup = ec.sec_ticker_cik(fetcher, ticker=code)
        report["attempts"].append({"channel": "sec_ticker_lookup", "health": lookup["health"],
                                   "records": 0, "error": None, "url": None, "reused": None})
        if lookup["health"] == ec.HEALTH_OK and lookup["cik"]:
            submissions = ec.sec_submissions(fetcher, cik=lookup["cik"])
            submissions["records"] = _material_forms(submissions["records"])
            if not submissions["records"] and submissions["health"] == ec.HEALTH_OK:
                submissions["health"] = ec.HEALTH_EMPTY
            listings.append(submissions)

    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for listing in listings:
        report["attempts"].append({
            "channel": listing["channel"], "health": listing["health"],
            "records": len(listing.get("records") or []),
            "error": listing.get("error"),
            "url": (listing.get("meta") or {}).get("url"),
            "reused": (listing.get("meta") or {}).get("reused"),
            "attempts_made": listing.get("attempts_made", 1),
        })
        report["records_found"] += len(listing.get("records") or [])
        if listing["health"] != ec.HEALTH_OK:
            continue
        chosen = _choose(listing["records"], window_start, window_end)
        if chosen is None:
            continue
        stamp = _timestamp(str(chosen["published_at"]), "record.published_at")
        if best is None or stamp > best[0]:
            best = (stamp, chosen, listing)

    if best is None:
        broken = [row for row in report["attempts"]
                  if row["channel"] != "sec_ticker_lookup" and row["health"] == ec.HEALTH_BROKEN]
        report["reason"] = "channel_broken" if broken else "no_announcement_in_window"
        report["health"] = ec.HEALTH_BROKEN if broken else ec.HEALTH_EMPTY
        return report

    _, chosen, listing = best
    tier = {"cninfo_fulltext": "exchange", "szse_announcements": "exchange",
            "hkex_news": "exchange", "sec_edgar": "regulator"}[listing["channel"]]
    document_url = chosen.get("document_url")
    retrieved_epoch = float((listing.get("meta") or {}).get("fetched_at") or 0.0)
    artifact: Path | None = None
    if isinstance(document_url, str) and document_url.startswith("http"):
        inline_key = f"{listing['channel']}_doc_{_symbol_key(symbol)}"
        fetched = ec.fetch_document(fetcher, url=document_url, key=inline_key,
                                    referer="http://www.cninfo.com.cn/"
                                    if listing["channel"] == "cninfo_fulltext" else None)
        report["document_retrieval"] = {"url": document_url, "health": fetched["health"],
                                        "http_status": (fetched["meta"] or {}).get("http_status")}
        if fetched["health"] == ec.HEALTH_OK:
            suffix_name = Path(document_url).name or "document.bin"
            artifact = evidence_dir / f"{_symbol_key(symbol)}_{suffix_name}"
            artifact.write_bytes(fetched["meta"]["body"])
            retrieved_epoch = float((fetched["meta"] or {}).get("fetched_at") or retrieved_epoch)
            digest = fetched["content_sha256"]
            locator = document_url
        else:
            report["document_retrieval"]["fallback"] = "listing_payload"
    if artifact is None:
        # The listing payload itself is the verifiable artifact: it carries the
        # platform's own announcement record and publication timestamp.
        artifact = evidence_dir / f"{_symbol_key(symbol)}_{listing['channel']}_listing.json"
        artifact.write_bytes(listing["meta"]["body"])
        digest = ec.sha256_bytes(listing["meta"]["body"])
        locator = str((listing.get("meta") or {}).get("url") or "")
    report.update({"health": ec.HEALTH_OK, "chosen": chosen, "tier": tier,
                   "artifact": str(artifact), "content_sha256": digest,
                   "source_locator": locator,
                   "retrieved_at": ec.iso(retrieved_epoch or fetcher.now())})
    return report


def build_items(reports: list[dict[str, Any]], *, window_start: float, window_end: float,
                scope_entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    unverified: list[str] = []
    for report in reports:
        if report.get("health") != ec.HEALTH_OK:
            unverified.append(f"{report['symbol']}:{report.get('reason', 'unverified')}")
            continue
        chosen = report["chosen"]
        channel = next((row["channel"] for row in report["attempts"]
                        if row["channel"] not in {"sec_ticker_lookup"}), "unknown")
        items.append({
            "evidence_id": f"ev_{channel}_{_symbol_key(report['symbol'])}",
            "source_tier": report["tier"],
            "source_locator": report["source_locator"],
            "published_at": chosen["published_at"],
            "retrieved_at": report["retrieved_at"],
            "content_sha256": report["content_sha256"],
            "artifact": report["artifact"],
            "claim": (f"{channel} 披露记录：{report['symbol']} {chosen['title']}"
                      f"（发布于 {chosen['published_at']}）"),
        })
    for index, entry in enumerate(scope_entries, start=1):
        if entry.get("health") != ec.HEALTH_OK:
            unverified.append(f"scope:{entry['scope']}:{entry.get('health')}")
            continue
        items.append({
            "evidence_id": f"ev_scope_{entry['scope']}_{index}",
            "source_tier": "regulator",
            "source_locator": entry["url"],
            "published_at": entry["published_at"],
            "retrieved_at": entry["retrieved_at"],
            "content_sha256": entry["content_sha256"],
            "artifact": entry["artifact"],
            "claim": f"{entry['scope']} 一手原件：{entry['url']}（发布时间由调用方声明为 {entry['published_at']}）",
        })
    return items, unverified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--scope-source", action="append", default=[],
                        help="<macro|sector|regulatory>=<url>@<published_at>, repeatable")
    parser.add_argument("--cache-dir")
    parser.add_argument("--max-cache-age-seconds", type=float, default=3600.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--user-agent", default=ec.DEFAULT_USER_AGENT)
    args = parser.parse_args(argv)

    try:
        window_start = _timestamp(args.window_start, "window_start")
        window_end = _timestamp(args.window_end, "window_end")
        if window_start >= window_end:
            raise ValueError("window_start must precede window_end")
        scope_specs = [_parse_scope_source(spec) for spec in args.scope_source]
        if len({spec["scope"] for spec in scope_specs}) != len(scope_specs):
            raise ValueError("each scope may be declared at most once")
        symbols = [symbol.strip() for symbol in args.symbols if symbol.strip()]
        if len(symbols) != len(set(symbols)):
            raise ValueError("symbols must be unique")
    except ValueError as exc:
        print(json.dumps({"status": "invalid_input", "detail_status": "collect_evidence_spec_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 2

    task_dir = Path(args.task_dir).expanduser().resolve()
    cache_dir = (Path(args.cache_dir).expanduser().resolve() if args.cache_dir
                 else task_dir / "evidence-cache")
    evidence_dir = task_dir / "evidence"
    out_dir = task_dir / "out"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = ec.ChannelFetcher(session=requests.Session(), cache_dir=cache_dir,
                                max_cache_age_seconds=args.max_cache_age_seconds,
                                timeout=args.timeout, user_agent=args.user_agent)

    reports = [collect_symbol(fetcher, symbol=symbol, window_start=window_start,
                              window_end=window_end, evidence_dir=evidence_dir)
               for symbol in symbols]

    scope_entries: list[dict[str, Any]] = []
    for spec in scope_specs:
        fetched = ec.fetch_document(fetcher, url=spec["url"],
                                    key=f"scope_{spec['scope']}_{abs(hash(spec['url'])) % 10**10}")
        entry = {"scope": spec["scope"], "url": spec["url"],
                 "published_at": spec["published_at"], "health": fetched["health"],
                 "http_status": (fetched["meta"] or {}).get("http_status")}
        if fetched["health"] == ec.HEALTH_OK:
            name = Path(spec["url"].split("?")[0]).name or "scope_source.bin"
            artifact = evidence_dir / f"scope_{spec['scope']}_{name}"
            artifact.write_bytes(fetched["meta"]["body"])
            entry.update({"artifact": str(artifact), "content_sha256": fetched["content_sha256"],
                          "retrieved_at": ec.iso(
                              float((fetched["meta"] or {}).get("fetched_at") or 0.0))})
        scope_entries.append(entry)

    items, unverified = build_items(reports, window_start=window_start, window_end=window_end,
                                    scope_entries=scope_entries)
    declared_scopes = {spec["scope"] for spec in scope_specs}
    missing_scopes = sorted(set(SCOPES) - declared_scopes)
    items_path = evidence_dir / "evidence_items.json"
    items_path.write_text(json.dumps({"evidence_items": items}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    report_path = out_dir / "evidence_channel_report.json"
    verified_symbols = [report["symbol"] for report in reports
                        if report.get("health") == ec.HEALTH_OK]
    complete = not unverified and not missing_scopes
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS_COMPLETE if complete else STATUS_INCOMPLETE,
        "detail_status": ("evidence_collected" if complete
                          else "evidence_incomplete"),
        "decision_scope": DECISION_SCOPE,
        "window_start": args.window_start,
        "window_end": args.window_end,
        "generated_at": ec.iso(fetcher.now()),
        "symbols_requested": symbols,
        "symbols_verified": verified_symbols,
        "unverified": unverified,
        "missing_scopes": missing_scopes,
        "scope_sources": scope_entries,
        "channel_results": reports,
        "known_broken_channels": ec.KNOWN_BROKEN_CHANNELS,
        "evidence_items_file": str(items_path),
        "evidence_count": len(items),
        "errors": ([] if complete else
                   [f"unverified:{','.join(unverified)}"] if unverified else
                   [f"missing_scopes:{','.join(missing_scopes)}"]),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "report_file": str(report_path)}, ensure_ascii=False, indent=2))
    return exit_code_for(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
