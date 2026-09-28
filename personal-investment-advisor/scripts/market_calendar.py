#!/usr/bin/env python3
"""Machine-verified market holiday calendar for quote-freshness decisions (P0-7).

Why this exists: quote freshness uses a fixed 72-hour CLOSED ceiling, so a long
holiday makes a perfectly healthy daily run fail closed.  Widening that ceiling
needs real closure dates, and an incomplete holiday table is more dangerous than no
table at all — it would silently widen or narrow the window.

Design: each market has its own parser (a shared regex over two very different
documents produced a silently incomplete table in the first attempt), each parser
asserts its own completeness, and the shipped table records the source locator,
retrieval time and content SHA-256 for every source.

Boundaries: no network access here (the caller captures the pages); no table is
written unless every assertion passes; a missing or unverified table yields no
extension rather than a guessed one.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pia_market_holidays_v1"
OFFICIAL_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "references" / "official_sources"
MARKETS = ("CN", "US", "SSE", "SZSE")
CN_HOLIDAYS = ("元旦", "春节", "清明节", "劳动节", "端午节", "中秋节", "国庆节")
US_LABELS = (
    "New Year", "Martin Luther King", "Washington", "Good Friday", "Memorial",
    "Juneteenth", "Independence", "Labor Day", "Thanksgiving", "Christmas",
)
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


class CalendarError(RuntimeError):
    pass


HEADER_RE = re.compile(
    r"[一二三四五六七八九十]+、\s*(元旦|春节|清明节|劳动节|端午节|中秋节|国庆节)\s*[：:]\s*")


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = text.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#x27;", "'")
    text = text.replace("&mdash;", "—").replace("&#8212;", "—").replace("&rsquo;", "'")
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- CN


def parse_cn_notice(html: str) -> dict[str, Any]:
    """Parse 国务院办公厅 holiday notice text into per-holiday date ranges.

    Completeness assertions: the notice year must be found, all seven holiday
    sections must be present, and every section that declares 共N天 must expand to
    exactly N days.
    """

    text = strip_tags(html)
    year_match = re.search(r"(\d{4})年元旦", text)
    if year_match is None:
        raise CalendarError("CN notice: could not locate the notice year (YYYY年元旦)")
    year = int(year_match.group(1))
    # Split on the numbered holiday headers themselves.  A generic "[一二三四五六七八九十]+、"
    # split is wrong: dates inside a section contain Chinese numerals too (for example
    # "（农历腊月二十八、周日）"), which silently truncated the Spring Festival section in the
    # first attempt.  Anchoring on the known holiday names removes that failure mode.
    parts = HEADER_RE.split(text)
    if len(parts) < 3:
        raise CalendarError("CN notice: no numbered holiday sections found")
    found = {parts[index]: parts[index + 1]
             for index in range(1, len(parts) - 1, 2)}
    missing = [name for name in CN_HOLIDAYS if name not in found]
    if missing:
        raise CalendarError(
            "CN notice: incomplete holiday sections, missing " + ", ".join(missing))
    holidays: dict[str, dict[str, Any]] = {}
    total_days = 0
    for name in CN_HOLIDAYS:
        body = found[name]
        days = _cn_section_days(body, year, name)
        declared = re.search(r"共\s*(\d{1,2})\s*天", body)
        if declared is None:
            raise CalendarError(
                f"CN notice: {name} does not declare 共N天, so the parsed range cannot be "
                "checked for completeness")
        if len(days) != int(declared.group(1)):
            raise CalendarError(
                f"CN notice: {name} declares 共{declared.group(1)}天 but {len(days)} days "
                "were parsed")
        holidays[name] = {"days": [day.isoformat() for day in days],
                          "declared_days": int(declared.group(1))}
        total_days += len(days)
    if total_days < 20:
        raise CalendarError(f"CN notice: only {total_days} holiday days parsed; expected >= 20")
    return {"year": year, "holidays": holidays, "total_days": total_days}


def _cn_section_days(body: str, year: int, name: str) -> list[datetime.date]:
    range_match = re.search(
        r"(\d{1,2})月(\d{1,2})日[^至]{0,60}?至\s*(?:(\d{1,2})月)?(\d{1,2})日", body)
    if range_match is not None:
        start_month, start_day, end_month, end_day = range_match.groups()
        start = datetime.date(year, int(start_month), int(start_day))
        end_month_value = int(end_month) if end_month else int(start_month)
        end = datetime.date(year, end_month_value, int(end_day))
        if end < start:  # a range that crosses into the next calendar year
            end = datetime.date(year + 1, end_month_value, int(end_day))
        return [start + datetime.timedelta(days=offset)
                for offset in range((end - start).days + 1)]
    single = re.search(r"(\d{1,2})月(\d{1,2})日", body)
    if single is not None:
        day = datetime.date(year, int(single.group(1)), int(single.group(2)))
        return [day]
    raise CalendarError(f"CN notice: could not parse dates for {name}")


# --------------------------------------------------------------------------- US


def parse_nyse_table(html: str) -> dict[str, Any]:
    """Parse the NYSE holidays table (one column per year).

    Completeness assertions: every known row label must be present, and each year
    column must yield at least nine closures (a dash means the market is open that
    day, which is legitimate for some years).
    """

    rows: list[list[str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [strip_tags(cell) for cell in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S | re.I)]
        if cells:
            rows.append(cells)
    years: list[int] = []
    for cells in rows:
        for cell in cells:
            if re.fullmatch(r"20\d{2}", cell.strip()):
                years.append(int(cell.strip()))
    years = sorted(set(years))
    if not years:
        raise CalendarError("NYSE table: no year columns found")
    closures: dict[int, list[str]] = {year: [] for year in years}
    seen_labels: set[str] = set()
    for cells in rows:
        label = next((cell for cell in cells
                      if any(token.lower() in cell.lower() for token in US_LABELS)), None)
        if label is None:
            continue
        seen_labels.add(label)
        dates = cells[cells.index(label) + 1:]
        for index, year in enumerate(years):
            if index >= len(dates):
                break
            day = _us_date(dates[index], year)
            if day is not None:
                closures[year].append(day.isoformat())
    missing = [token for token in US_LABELS
               if not any(token.lower() in label.lower() for label in seen_labels)]
    if missing:
        raise CalendarError("NYSE table: incomplete rows, missing " + ", ".join(missing))
    for year in years:
        if len(closures[year]) < 9:
            raise CalendarError(
                f"NYSE table: only {len(closures[year])} closures parsed for {year}")
    return {"years": years,
            "closures": {str(year): sorted(closures[year]) for year in years}}


def _us_date(cell: str, year: int) -> datetime.date | None:
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2})", cell)
    if match is None:
        return None
    month = MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    try:
        return datetime.date(year, month, int(match.group(2)))
    except ValueError:
        return None


# ------------------------------------------------------------------------ table


def build_table(cn_html: str, us_html: str, *, cn_locator: str, us_locator: str,
                retrieved_at: str) -> dict[str, Any]:
    cn = parse_cn_notice(cn_html)
    us = parse_nyse_table(us_html)
    us_years = {str(year): values for year, values in us["closures"].items()}
    table = {
        "schema_version": SCHEMA_VERSION,
        "note": ("CN is a government leave calendar, not exchange-verified closures. "
                 "US comes from NYSE. Only a separately parsed and cross-checked SSE notice "
                 "may authorize SSE-specific freshness extension."),
        "sources": [
            {"market": "CN", "locator": cn_locator, "retrieved_at": retrieved_at,
             "content_sha256": hashlib.sha256(cn_html.encode("utf-8")).hexdigest(),
             "parsed_holiday_groups": len(cn["holidays"]),
             "parsed_days": cn["total_days"]},
            {"market": "US", "locator": us_locator, "retrieved_at": retrieved_at,
             "content_sha256": hashlib.sha256(us_html.encode("utf-8")).hexdigest(),
             "parsed_years": us["years"]},
        ],
        "markets": {
            "CN": {str(cn["year"]): sorted(day
                                           for entry in cn["holidays"].values()
                                           for day in entry["days"])},
            "US": us_years,
        },
    }
    return table


EXCHANGE_NOTICES = {
    "SSE": ("https://www.sse.com.cn/disclosure/announcement/",
            r'<div class="allZoom"[^>]*>(.*?)</div>', "上证公告", "上海证券交易所"),
    "SZSE": ("https://www.szse.cn/disclosure/notice/",
             r'<div[^>]*id="desContent"[^>]*>(.*?)</div>', "深证会", "深圳证券交易所"),
}


def augment_cn_exchange_table(table: dict[str, Any], raw: bytes, *, exchange: str,
                              locator: str, retrieved_at: str) -> dict[str, Any]:
    """Parse an official exchange notice before any CN freshness widening."""
    if exchange not in EXCHANGE_NOTICES:
        raise CalendarError("unsupported CN exchange notice")
    prefix, body_pattern, issue, issuer = EXCHANGE_NOTICES[exchange]
    if not isinstance(locator, str) or not locator.startswith(prefix):
        raise CalendarError(f"{exchange} source must be an official exchange announcement URL")
    if not isinstance(retrieved_at, str):
        raise CalendarError(f"{exchange} retrieval time missing")
    if not raw or len(raw) > 1024 * 1024:
        raise CalendarError(f"{exchange} source must be nonempty and at most 1 MiB")
    try:
        captured = datetime.datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        if captured.tzinfo is None or captured > datetime.datetime.now(datetime.timezone.utc):
            raise ValueError("future or naive time")
        page = raw.decode("utf-8")
    except (ValueError, UnicodeError):
        raise CalendarError(f"{exchange} source requires UTF-8 and past timezone-aware retrieval") from None
    notice_match = re.search(body_pattern, page, re.S)
    if notice_match is None:
        raise CalendarError(f"{exchange} official announcement body not found")
    paragraphs = [re.sub(r"\s+", "", strip_tags(html.unescape(item))) for item in
                  re.findall(r"<p\b[^>]*>(.*?)</p>", notice_match.group(1), re.S | re.I)]
    body = " ".join(paragraphs)
    year_match = re.search(r"现将(20\d{2})年部分节假日休市安排", body)
    if issue not in body or issuer not in body or year_match is None:
        raise CalendarError(f"{exchange} issuer, document number or notice year missing")
    year = int(year_match.group(1))
    groups: dict[str, list[str]] = {}
    for name in CN_HOLIDAYS:
        candidates = [p for p in paragraphs if re.match(rf"^（[一二三四五六七]）{name}：", p)]
        if len(candidates) != 1:
            raise CalendarError(f"{exchange} {name} must appear in exactly one holiday paragraph")
        match = re.search(r"(\d{1,2})月(\d{1,2})日.*?至(\d{1,2})月(\d{1,2})日.*?休市，(\d{1,2})月(\d{1,2})日.*?开市", candidates[0])
        if match is None:
            raise CalendarError(f"{exchange} {name} closure and reopening must be explicit")
        sm, sd, em, ed, rm, rd = map(int, match.groups())
        try:
            start, end, reopen = (datetime.date(year, m, d) for m, d in
                                  ((sm, sd), (em, ed), (rm, rd)))
        except ValueError as exc:
            raise CalendarError(f"{exchange} {name} has invalid date: {exc}") from exc
        if end < start or (end - start).days > 20 or not end < reopen <= end + datetime.timedelta(days=3):
            raise CalendarError(f"{exchange} {name} closure/reopening order invalid")
        if any((end + datetime.timedelta(days=i)).weekday() < 5
               for i in range(1, (reopen - end).days)):
            raise CalendarError(f"{exchange} {name} has an unexplained weekday before reopening")
        groups[name] = [(start + datetime.timedelta(days=i)).isoformat()
                        for i in range((end - start).days + 1)]
    dates = sorted(day for values in groups.values() for day in values)
    if len(dates) != len(set(dates)) or len(dates) < 20:
        raise CalendarError(f"{exchange} holidays overlap or are incomplete")
    government = ((table.get("markets") or {}).get("CN") or {}).get(str(year))
    if not isinstance(government, list) or dates != sorted(government):
        raise CalendarError(f"{exchange} notice and existing CN public holiday baseline disagree")
    result = copy.deepcopy(table)
    result.setdefault("markets", {})[exchange] = {str(year): dates}
    result.setdefault("sources", []).append({
        "market": exchange, "kind": "official_exchange_closure_notice",
        "locator": locator, "retrieved_at": retrieved_at,
        "content_sha256": hashlib.sha256(raw).hexdigest(), "parsed_holiday_groups": 7,
        "parsed_days": len(dates),
    })
    return result


def augment_sse_table(table: dict[str, Any], raw: bytes, *, locator: str,
                      retrieved_at: str) -> dict[str, Any]:
    return augment_cn_exchange_table(table, raw, exchange="SSE", locator=locator,
                                     retrieved_at=retrieved_at)


def load_table(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CalendarError(f"holiday table unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise CalendarError(f"holiday table schema_version must be {SCHEMA_VERSION}")
    sources = payload.get("sources")
    markets = payload.get("markets")
    if not isinstance(sources, list) or not isinstance(markets, dict):
        raise CalendarError("holiday table sources and markets must be structured")
    for source in sources:
        if not isinstance(source, dict) or source.get("kind") != "official_exchange_closure_notice":
            continue
        exchange = source.get("market")
        years = markets.get(exchange) if isinstance(exchange, str) else None
        if not isinstance(exchange, str) or exchange not in EXCHANGE_NOTICES:
            raise CalendarError("unsupported official exchange source")
        if not isinstance(years, dict) or len(years) != 1:
            raise CalendarError("official exchange table must have one supported year")
        year = next(iter(years))
        if not re.fullmatch(r"20\d{2}", str(year)):
            raise CalendarError("official exchange table year invalid")
        raw_path = OFFICIAL_SOURCE_ROOT / f"{exchange.lower()}_{year}_holidays.html"
        if raw_path.is_symlink() or not raw_path.is_file() or raw_path.stat().st_size > 1024 * 1024:
            raise CalendarError("official exchange capture missing or unsafe")
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source.get("content_sha256"):
            raise CalendarError("official exchange capture digest mismatch")
        parsed = augment_cn_exchange_table(payload, raw, exchange=exchange,
                                            locator=source.get("locator"),
                                            retrieved_at=source.get("retrieved_at"))
        if parsed["markets"][exchange] != years:
            raise CalendarError("official exchange dates differ from captured notice")
    return payload


def holiday_dates(table: dict[str, Any], market: str, year: int) -> set[datetime.date]:
    market = market.strip().upper()
    if market not in MARKETS:
        raise CalendarError(f"unknown market {market!r}; expected one of {', '.join(MARKETS)}")
    values = ((table.get("markets") or {}).get(market) or {}).get(str(year))
    if values is None:
        raise CalendarError(f"holiday table has no coverage for {market} {year}")
    return {datetime.date.fromisoformat(day) for day in values}


def is_closed(table: dict[str, Any], market: str, day: datetime.date) -> bool:
    if day.weekday() >= 5:
        return True
    return day in holiday_dates(table, market, day.year)


def closed_days_between(table: dict[str, Any], market: str, start: datetime.date,
                        end: datetime.date) -> tuple[int, list[str]]:
    """Count market-closed days in (start, end]; unknown years are refused."""

    if end < start:
        return 0, []
    closed: list[str] = []
    day = start + datetime.timedelta(days=1)
    while day <= end:
        if is_closed(table, market, day):
            closed.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return len(closed), closed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or query the market holiday table.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Parse captured notices into a table.")
    build.add_argument("--cn-html", required=True)
    build.add_argument("--us-html", required=True)
    build.add_argument("--cn-locator", required=True)
    build.add_argument("--us-locator", required=True)
    build.add_argument("--retrieved-at", required=True)
    build.add_argument("--out", required=True)
    exchange = subparsers.add_parser("augment-sse", help="Add source-checked SSE closures to an existing table.")
    exchange.add_argument("--table", required=True)
    exchange.add_argument("--sse-html", required=True)
    exchange.add_argument("--sse-locator", required=True)
    exchange.add_argument("--retrieved-at", required=True)
    exchange.add_argument("--out", required=True)
    cn_exchange = subparsers.add_parser("augment-cn-exchange", help="Add SSE or SZSE official closures.")
    cn_exchange.add_argument("--table", required=True)
    cn_exchange.add_argument("--exchange", required=True, choices=("SSE", "SZSE"))
    cn_exchange.add_argument("--exchange-html", required=True)
    cn_exchange.add_argument("--exchange-locator", required=True)
    cn_exchange.add_argument("--retrieved-at", required=True)
    cn_exchange.add_argument("--out", required=True)
    query = subparsers.add_parser("closed", help="Count market-closed days in a window.")
    query.add_argument("--table", required=True)
    query.add_argument("--market", required=True)
    query.add_argument("--start", required=True)
    query.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            table = build_table(
                Path(args.cn_html).expanduser().resolve().read_text(encoding="utf-8"),
                Path(args.us_html).expanduser().resolve().read_text(encoding="utf-8"),
                cn_locator=args.cn_locator, us_locator=args.us_locator,
                retrieved_at=args.retrieved_at)
            target = Path(args.out).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            rendered = json.dumps(table, ensure_ascii=False, indent=2).encode("utf-8")
            target.write_bytes(rendered)
            print(json.dumps({"status": "complete", "detail_status": "holiday_table_built",
                              "decision_scope": "research_only", "table": str(target),
                              "table_sha256": hashlib.sha256(rendered).hexdigest(),
                              "markets": {market: {year: len(days) for year, days in years.items()}
                                          for market, years in table["markets"].items()},
                              "sources": table["sources"]},
                             ensure_ascii=False, indent=2))
            return 0
        if args.command in ("augment-sse", "augment-cn-exchange"):
            source = Path(args.table).expanduser().resolve()
            target = Path(args.out).expanduser().resolve()
            if target == source or target.exists():
                raise CalendarError("exchange table output must be a new, distinct file")
            exchange_name = "SSE" if args.command == "augment-sse" else args.exchange
            html_path = args.sse_html if args.command == "augment-sse" else args.exchange_html
            locator = args.sse_locator if args.command == "augment-sse" else args.exchange_locator
            with Path(html_path).expanduser().resolve().open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            table = augment_cn_exchange_table(load_table(source), raw, exchange=exchange_name,
                                              locator=locator, retrieved_at=args.retrieved_at)
            rendered = json.dumps(table, ensure_ascii=False, indent=2).encode("utf-8")
            with target.open("xb") as stream:
                stream.write(rendered)
            source_field = "sse_source" if args.command == "augment-sse" else "exchange_source"
            print(json.dumps({"status": "complete", "table": str(target),
                              "table_sha256": hashlib.sha256(rendered).hexdigest(),
                              source_field: table["sources"][-1]}, ensure_ascii=False))
            return 0
        table = load_table(Path(args.table).expanduser().resolve())
        count, days = closed_days_between(
            table, args.market, datetime.date.fromisoformat(args.start),
            datetime.date.fromisoformat(args.end))
        print(json.dumps({"status": "complete", "detail_status": "closed_days_counted",
                          "decision_scope": "research_only", "market": args.market.upper(),
                          "start": args.start, "end": args.end,
                          "closed_day_count": count, "closed_days": days},
                         ensure_ascii=False, indent=2))
        return 0
    except (CalendarError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "detail_status": "holiday_calendar_input_invalid",
                          "decision_scope": "research_only", "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
