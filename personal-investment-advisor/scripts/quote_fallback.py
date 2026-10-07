"""Secondary, explicitly labelled quote source for a failed primary transport.

This adapter exists for one narrow case: the primary provider (yfinance) failed at the
transport layer for a symbol, so there is **no** primary quote at all.  A secondary
source may then supply a price, but it is never allowed to look like a primary one:

* every record carries ``quote_provenance`` with ``tier="secondary"``, the primary
  outcome that triggered it, the source name, the source URL, and what the source
  actually evidenced (the echoed instrument key, the returned code/venue and the
  currency string it printed);
* fields the secondary source cannot evidence (``quoteType``, and timeliness) are
  listed as ``unverifiable`` instead of being filled in from the portfolio's own
  expectation;
* a payload the source structurally cannot produce (an error envelope, a mismatched
  echoed code, a missing timestamp) is ``broken``/``empty`` — never a silent price.

The module never decides freshness or readiness: it returns the timestamp the source
printed so the existing, unchanged quote-freshness contract can judge it.  It is
single-vendor by design; ``references/free-data-policy.md`` records that limit.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

VERSION = "pia_quote_fallback_v1"

SOURCE_TENCENT = "Tencent Finance (secondary)"
TENCENT_URL = "https://qt.gtimg.cn/q={key}"

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")

#: Sources that may be used, by portfolio market.  Anything else has no fallback.
MARKET_SOURCES = {"CN": SOURCE_TENCENT, "US": SOURCE_TENCENT}

HEALTH_OK = "ok"
HEALTH_EMPTY = "empty"
HEALTH_BROKEN = "broken"

# CN continuous trading window, used only to label the observed timestamp.
CN_SESSION = (dtime(9, 30), dtime(15, 0))
US_SESSION = (dtime(9, 30), dtime(16, 0))

CN_SUFFIX_EXCHANGE = {".SS": "SSE", ".SZ": "SZSE", ".BJ": "BSE"}
CN_SUFFIX_PREFIX = {".SS": "sh", ".SZ": "sz", ".BJ": "bj"}
# Tencent suffixes US tickers with the venue; only mapped values are reused as
# evidence.  An unmapped suffix stays unverifiable rather than being guessed.
US_VENUE_BY_SUFFIX = {
    ".OQ": "NASDAQ", ".NQ": "NASDAQ", ".N": "NYSE", ".NYS": "NYSE",
    ".A": "AMEX", ".P": "ARCA", ".K": "NASDAQ",
}

_CN_INDICES = {"name": 1, "echoed_symbol": 2, "price": 3, "previous_close": 4,
               "observed": 30, "change": 31, "change_pct": 32, "high": 33, "low": 34}
_US_INDICES = {"venue_code": 2, "price": 3, "previous_close": 4, "observed": 30,
               "change": 31, "change_pct": 32, "high": 33, "low": 34, "currency": 35}
_CN_MIN_FIELDS = 35
_US_MIN_FIELDS = 36


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def fallback_source_for(symbol: str, market: str | None = None) -> str | None:
    """Return the secondary source for a symbol, or ``None`` when unsupported."""
    upper = str(symbol or "").strip().upper()
    if market is not None:
        key = str(market).strip().upper()
        if key not in MARKET_SOURCES:
            return None
        if key == "CN" and not upper.endswith((".SS", ".SZ", ".BJ")):
            return None
        if key == "US" and ("." in upper or not upper):
            return None
        return MARKET_SOURCES[key]
    if upper.endswith((".SS", ".SZ", ".BJ")):
        return SOURCE_TENCENT
    if upper and "." not in upper:
        return SOURCE_TENCENT
    return None


def instrument_key(symbol: str) -> str | None:
    """Return the vendor's instrument key (``sh601899`` / ``usGOOG``)."""
    upper = str(symbol or "").strip().upper()
    for suffix, prefix in CN_SUFFIX_PREFIX.items():
        if upper.endswith(suffix):
            return f"{prefix}{upper[: -len(suffix)]}"
    if upper and "." not in upper:
        return f"us{upper}"
    return None


def source_url(symbol: str) -> str | None:
    key = instrument_key(symbol)
    return TENCENT_URL.format(key=key) if key else None


def source_locator(symbol: str) -> str:
    """Stable locator for a secondary price; never mimics the primary locator."""
    return f"fallback:tencent:{symbol}"


def classify(text: str, status_code: int | None = None, *, key: str | None = None) -> str:
    """Classify a raw secondary response before parsing it."""
    body = str(text or "")
    if status_code is not None and int(status_code) != 200:
        return HEALTH_BROKEN
    lowered = body.strip().lower()
    if not lowered:
        return HEALTH_EMPTY
    if lowered.startswith(("<!doctype", "<html", "{", "[", "<?xml")):
        return HEALTH_BROKEN
    if "v_pv_none_match" in lowered:
        # The vendor's explicit "no such instrument" answer: a faithful empty, not a
        # transport failure, and never a price.
        return HEALTH_EMPTY
    markers = ([f"v_{key.lower()}="] if key else
               ["v_sh", "v_sz", "v_bj", "v_us"])
    return HEALTH_OK if any(marker in lowered for marker in markers) else HEALTH_BROKEN


def _market_state(moment: datetime, market: str) -> str:
    if market == "CN":
        local = moment.astimezone(SHANGHAI)
        session = CN_SESSION
    else:
        local = moment.astimezone(NEW_YORK)
        session = US_SESSION
    if local.weekday() >= 5:
        return "CLOSED"
    return "REGULAR" if session[0] <= local.time() <= session[1] else "CLOSED"


def parse_payload(text: str, symbol: str, market: str) -> dict[str, Any]:
    """Parse one vendor quote line.  Raises ``ValueError`` on anything unusable."""
    key = instrument_key(symbol)
    if key is None:
        raise ValueError("unsupported_symbol")
    marker = f'v_{key}="'
    lowered = str(text or "")
    index = lowered.lower().find(marker.lower())
    if index < 0:
        raise ValueError("echoed_instrument_key_missing")
    tail = lowered[index + len(marker):]
    end = tail.find('"')
    if end < 0:
        raise ValueError("unterminated_payload")
    fields = tail[:end].split("~")

    if market == "CN":
        if len(fields) < _CN_MIN_FIELDS:
            raise ValueError(f"field_count_too_small:{len(fields)}")
        echoed = fields[_CN_INDICES["echoed_symbol"]].strip()
        expected_code = key[2:].upper()
        if echoed.upper() != expected_code:
            raise ValueError("echoed_code_mismatch")
        price = _finite(fields[_CN_INDICES["price"]])
        prev_close = _finite(fields[_CN_INDICES["previous_close"]])
        if price is None or price <= 0:
            raise ValueError("invalid_price")
        stamp = fields[_CN_INDICES["observed"]].strip()
        try:
            observed = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise ValueError(f"unparseable_timestamp:{stamp}") from exc
        observed = observed.replace(tzinfo=SHANGHAI)
        suffix = next(s for s in CN_SUFFIX_PREFIX if symbol.upper().endswith(s))
        return {
            "source": SOURCE_TENCENT,
            "echoed_symbol": echoed,
            "instrument_name": (fields[_CN_INDICES["name"]].strip() or None),
            "price": price,
            "previous_close": prev_close,
            "currency": "CNY",
            "observed_at": observed.isoformat(),
            "observed_epoch": observed.timestamp(),
            "market_state": _market_state(observed, "CN"),
            "exchange_evidence": "request_key_echo",
            "exchange": CN_SUFFIX_EXCHANGE[suffix],
            "identity_verification": "echoed_instrument_key_and_code",
            "unverifiable": ["quoteType", "timeliness"],
        }

    if len(fields) < _US_MIN_FIELDS:
        raise ValueError(f"field_count_too_small:{len(fields)}")
    venue_code = fields[_US_INDICES["venue_code"]].strip().upper()
    ticker, _, venue_suffix = venue_code.partition(".")
    if not ticker or ticker != symbol.strip().upper():
        raise ValueError("echoed_code_mismatch")
    price = _finite(fields[_US_INDICES["price"]])
    if price is None or price <= 0:
        raise ValueError("invalid_price")
    currency = fields[_US_INDICES["currency"]].strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError(f"invalid_currency:{currency}")
    stamp = fields[_US_INDICES["observed"]].strip()
    try:
        observed = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"unparseable_timestamp:{stamp}") from exc
    observed = observed.replace(tzinfo=NEW_YORK)
    venue = US_VENUE_BY_SUFFIX.get(f".{venue_suffix}" if venue_suffix else "")
    unverifiable = ["quoteType", "timeliness"]
    if venue is None:
        unverifiable.append("exchange")
    return {
        "source": SOURCE_TENCENT,
        "echoed_symbol": venue_code,
        "instrument_name": None,
        "price": price,
        "previous_close": _finite(fields[_US_INDICES["previous_close"]]),
        "currency": currency,
        "observed_at": observed.isoformat(),
        "observed_epoch": observed.timestamp(),
        "market_state": _market_state(observed, "US"),
        "exchange_evidence": "venue_suffix_echo" if venue else None,
        "exchange": venue,
        "identity_verification": "echoed_venue_code_and_currency",
        "unverifiable": unverifiable,
    }


def build_record(symbol: str, parsed: dict[str, Any], *, url: str,
                 retrieved_at: str, primary_outcome: str) -> dict[str, Any]:
    """Shape a parsed secondary quote into the run's record contract."""
    return {
        "tier": "secondary",
        "symbol": symbol,
        "source": parsed["source"],
        "source_url": url,
        "source_locator": source_locator(symbol),
        "price": parsed["price"],
        "previous_close": parsed.get("previous_close"),
        "currency": parsed["currency"],
        "observed_at": parsed["observed_at"],
        "observed_epoch": parsed["observed_epoch"],
        "retrieved_at": retrieved_at,
        "market_state": parsed["market_state"],
        "identity_verification": parsed.get("identity_verification"),
        "exchange": parsed.get("exchange"),
        "exchange_evidence": parsed.get("exchange_evidence"),
        "unverifiable": list(parsed.get("unverifiable") or []),
        "echoed_symbol": parsed.get("echoed_symbol"),
        "instrument_name": parsed.get("instrument_name"),
        "primary_outcome": primary_outcome,
    }


class FallbackFetcher:
    """Fetch secondary quotes with an injectable transport and a bounded cache.

    ``http_get(url, headers)`` must return ``(status_code, text)``.  The cache is a
    small on-disk map keyed by source URL so a repeated run inside the TTL does not
    re-hit the endpoint; ``bypass_cache`` forces a fresh read.
    """

    def __init__(self, *, http_get: Callable[..., Any] | None = None,
                 cache_dir: Path | str | None = None, ttl_seconds: float = 120.0,
                 now: Callable[[], float] | None = None,
                 timeout_seconds: float = 20.0):
        self._http_get = http_get or _requests_get
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._ttl = float(ttl_seconds)
        self._now = now or time.time
        self._timeout = float(timeout_seconds)
        self.bypass_cache = False

    def _cache_path(self, url: str) -> Path | None:
        if self._cache_dir is None:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self._cache_dir / f"fallback_{digest}.json"

    def _read_cache(self, url: str) -> tuple[str | None, int | None, float | None]:
        path = self._cache_path(url)
        if path is None or self.bypass_cache or not path.is_file():
            return None, None, None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            age = self._now() - float(payload["stored_epoch"])
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            return None, None, None
        if age > self._ttl:
            return None, None, None
        return payload.get("text"), payload.get("status_code"), age

    def _write_cache(self, url: str, text: str, status_code: int | None) -> None:
        path = self._cache_path(url)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"url": url, "status_code": status_code,
                                        "text": text, "stored_epoch": self._now()},
                                       ensure_ascii=False), encoding="utf-8")
        except OSError:
            return

    def _fetch_text(self, url: str, headers: dict[str, str]) -> tuple[int | None, str, str]:
        text, status_code, _age = self._read_cache(url)
        if text is not None:
            return status_code, text, "cache"
        try:
            status_code, text = self._http_get(url, headers)
        except Exception as exc:  # a transport failure is data, not an exception
            return None, f"{type(exc).__name__}: {exc}", "error"
        text = text if isinstance(text, str) else str(text)
        self._write_cache(url, text, status_code)
        return status_code, text, "network"

    def fetch(self, symbol: str, *, market: str | None = None,
              primary_outcome: str | None = None) -> dict[str, Any]:
        """Return ``{health, record, error, url, fetched_via}`` for one symbol."""
        key = instrument_key(symbol)
        resolved_market = (str(market).strip().upper() if market
                           else ("CN" if symbol.upper().endswith((".SS", ".SZ", ".BJ")) else "US"))
        if fallback_source_for(symbol, resolved_market) is None or key is None:
            return {"health": HEALTH_EMPTY, "record": None,
                    "error": "no_secondary_source_for_symbol", "url": None,
                    "fetched_via": None, "market": resolved_market}
        url = source_url(symbol)
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
        status_code, text, via = self._fetch_text(url, headers)
        health = classify(text, status_code, key=key)
        if health != HEALTH_OK:
            return {"health": health, "record": None,
                    "error": f"secondary_response_{health}", "url": url,
                    "fetched_via": via, "market": resolved_market}
        try:
            parsed = parse_payload(text, symbol, resolved_market)
        except ValueError as exc:
            return {"health": HEALTH_BROKEN, "record": None,
                    "error": f"secondary_parse_failed:{exc}", "url": url,
                    "fetched_via": via, "market": resolved_market}
        record = build_record(symbol, parsed, url=url, retrieved_at=_iso(self._now()),
                              primary_outcome=str(primary_outcome or "error"))
        return {"health": HEALTH_OK, "record": record, "error": None, "url": url,
                "fetched_via": via, "market": resolved_market}

    def fetch_many(self, symbols: Iterable[str], *,
                   primary_outcomes: dict[str, str] | None = None,
                   markets: dict[str, str | None] | None = None) -> dict[str, dict[str, Any]]:
        outcomes = primary_outcomes or {}
        market_map = markets or {}
        return {symbol: self.fetch(symbol, market=market_map.get(symbol),
                                   primary_outcome=outcomes.get(symbol))
                for symbol in symbols}


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def _requests_get(url: str, headers: dict[str, str]) -> tuple[int, str]:
    import requests  # local import keeps the module importable without the dependency

    response = requests.get(url, headers=headers, timeout=20.0)
    response.encoding = "gbk"
    return response.status_code, response.text
