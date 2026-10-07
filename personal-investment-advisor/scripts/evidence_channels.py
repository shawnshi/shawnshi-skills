"""Primary-source evidence channels with explicit empty-result vs broken-channel classification.

Why this exists: a disclosure channel that answers HTTP 200 with a structurally
impossible payload (``announcements: null``) or with an error envelope is not
evidence that an issuer published nothing.  Treating the two as the same is the
most dangerous failure mode for a Thesis red team, so every fetch here returns a
health verdict and the caller must fail closed on ``broken``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

SCHEMA_VERSION = "pia_evidence_channels_v1"

HEALTH_OK = "ok"
HEALTH_EMPTY = "empty"
HEALTH_BROKEN = "broken"

CN_TZ = datetime.timezone(datetime.timedelta(hours=8))
HK_TZ = datetime.timezone(datetime.timedelta(hours=8))

DEFAULT_USER_AGENT = "PIA evidence collector (contact: user@example.invalid)"

# Channels that were observed answering HTTP 200 without usable data.  They stay
# listed so a caller never reads "no data" out of a channel that is simply down.
KNOWN_BROKEN_CHANNELS: dict[str, str] = {
    "sse_bulletin_query": (
        "上交所 queryCompanyBulletinNew.do 对 2026-09-01..29 及全年窗口均返回 total=0，"
        "commonSoaQuery.do 返回 ExceptionInterceptor）。通道故障，不等于无公告。"
    ),
    "cninfo_announcement_query": (
        "巨潮 hisAnnouncement/query 对所有测试标的返回 announcements=null / totalAnnouncement=0"
        "（含 2025 对照窗口）。通道故障，不等于无公告。"
    ),
    "szse_attachment_pdf": (
        "深交所公告 PDF 直链（/disc/disk03/finalpage/...）返回 403 WAF 页面；"
        "应以公告列表记录为证据或改用巨潮 static 镜像。"
    ),
}

CNINFO_FULLTEXT_URL = "http://www.cninfo.com.cn/new/fulltextSearch/full"
CNINFO_STATIC_BASE = "http://static.cninfo.com.cn/"
SZSE_ANNLIST_URL = "http://www.szse.cn/api/disc/announcement/annList"
HKEX_PREFIX_URL = "https://www1.hkexnews.hk/search/prefix.do"
HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"


def iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _cn_iso(epoch_seconds: float) -> str:
    return datetime.datetime.fromtimestamp(epoch_seconds, CN_TZ).isoformat()


def _parse_cn_datetime(value: str) -> str | None:
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=CN_TZ).isoformat()
    return None


# --------------------------------------------------------------------- classifiers
def classify_cninfo_fulltext(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    """Classify a cninfo full-text search response.

    The broken shape observed in the wild keeps every field at ``null``/0 with
    ``announcements: null``; a genuine empty window returns ``[]`` with an integer
    total, so the two are distinguishable and must not be merged.
    """
    if not isinstance(payload, dict):
        return HEALTH_BROKEN, []
    rows = payload.get("announcements")
    total = payload.get("totalAnnouncement")
    if rows is None:
        return HEALTH_BROKEN, []
    if not isinstance(rows, list) or not isinstance(total, int):
        return HEALTH_BROKEN, []
    records = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = row.get("announcementTime")
        adjunct = row.get("adjunctUrl")
        if not isinstance(stamp, (int, float)) or not isinstance(adjunct, str) or not adjunct:
            continue
        title = re.sub(r"<[^>]+>", "", str(row.get("announcementTitle") or "")).strip()
        records.append({
            "title": title,
            "published_at": _cn_iso(float(stamp) / 1000.0),
            "document_url": CNINFO_STATIC_BASE + adjunct.lstrip("/"),
            "sec_code": row.get("secCode"),
            "channel": "cninfo_fulltext",
        })
    return (HEALTH_OK if records else HEALTH_EMPTY), records


def classify_szse_announcements(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return HEALTH_BROKEN, []
    count = payload.get("announceCount")
    rows = payload.get("data")
    if not isinstance(count, int) or not isinstance(rows, list):
        return HEALTH_BROKEN, []
    records = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published = _parse_cn_datetime(str(row.get("publishTime") or ""))
        attach = row.get("attachPath")
        if published is None or not isinstance(attach, str) or not attach:
            continue
        records.append({
            "title": str(row.get("title") or "").strip(),
            "published_at": published,
            "document_url": attach if attach.startswith("http") else None,
            "attachment_path": attach,
            "sec_code": (row.get("secCode") or [None])[0],
            "channel": "szse_announcements",
            "document_blocked_reason": "szse_attachment_pdf",
        })
    if records:
        return HEALTH_OK, records
    return (HEALTH_EMPTY if count == 0 else HEALTH_BROKEN), records


def _unwrap_jsonp(text: str) -> Any | None:
    match = re.search(r"^\s*[A-Za-z_$][\w$]*\s*\((.*)\)\s*;?\s*$", text, re.S)
    body = match.group(1) if match else text
    try:
        return json.loads(body)
    except ValueError:
        return None


def classify_hkex_prefix(payload_text: str) -> tuple[str, list[dict[str, Any]]]:
    parsed = _unwrap_jsonp(payload_text)
    if not isinstance(parsed, dict):
        return HEALTH_BROKEN, []
    stocks = parsed.get("stockInfo")
    if stocks is None:
        return HEALTH_BROKEN, []
    if not isinstance(stocks, list):
        return HEALTH_BROKEN, []
    return (HEALTH_OK if stocks else HEALTH_EMPTY), [s for s in stocks if isinstance(s, dict)]


def classify_hkex_news(payload_text: str) -> tuple[str, list[dict[str, Any]]]:
    parsed = _unwrap_jsonp(payload_text)
    if not isinstance(parsed, dict) or "result" not in parsed:
        return HEALTH_BROKEN, []
    raw = parsed.get("result")
    if isinstance(raw, str):
        if not raw.strip():
            return HEALTH_EMPTY, []
        try:
            raw = json.loads(raw)
        except ValueError:
            return HEALTH_BROKEN, []
    if not isinstance(raw, list):
        return HEALTH_BROKEN, []
    records = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        published = _parse_hkex_datetime(str(row.get("DATE_TIME") or ""))
        if published is None:
            continue
        records.append({
            "title": re.sub(r"<[^>]+>", " ", str(row.get("TITLE") or "")).strip(),
            "published_at": published,
            "document_url": row.get("FILE_LINK") or row.get("fileLink"),
            "channel": "hkex_news",
        })
    return (HEALTH_OK if records else HEALTH_EMPTY), records


def _parse_hkex_datetime(value: str) -> str | None:
    text = value.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=HK_TZ).isoformat()
    return None


def classify_sec_submissions(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return HEALTH_BROKEN, []
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return HEALTH_BROKEN, []
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        return HEALTH_BROKEN, []
    columns = ("accessionNumber", "form", "filingDate", "acceptanceDateTime", "primaryDocument")
    if any(not isinstance(recent.get(name), list) for name in columns):
        return HEALTH_BROKEN, []
    cik = str(payload.get("cik") or "").strip()
    records = []
    length = len(recent["form"])
    for index in range(length):
        form = recent["form"][index]
        accepted = str(recent["acceptanceDateTime"][index] or "").strip()
        document = str(recent["primaryDocument"][index] or "").strip()
        accession = str(recent["accessionNumber"][index] or "").strip()
        if not form or not accepted or not document or not accession:
            continue
        published = accepted
        try:
            parsed = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        records.append({
            "title": f"{form} ({recent['filingDate'][index]})",
            "published_at": published,
            "document_url": SEC_ARCHIVE_URL.format(
                cik_int=str(int(cik)) if cik.isdigit() else cik.lstrip("0"),
                accession=accession.replace("-", ""),
                document=document,
            ),
            "form": form,
            "channel": "sec_edgar",
        })
    return (HEALTH_OK if records else HEALTH_EMPTY), records


# ----------------------------------------------------------------------- fetching
class ChannelFetcher:
    """Session-backed fetcher with a bounded on-disk cache and honest reuse labels."""

    def __init__(
        self,
        *,
        session: Any,
        cache_dir: Path,
        max_cache_age_seconds: float = 3600.0,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.session = session
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_age_seconds = float(max_cache_age_seconds)
        self.timeout = float(timeout)
        self.user_agent = user_agent
        self.bypass_cache = False
        self._clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc).timestamp())

    def now(self) -> float:
        """Current clock reading; overridable so cache age stays testable."""
        return self._clock()

    # -- cache ---------------------------------------------------------------
    def _read_cache(self, key: str) -> dict[str, Any] | None:
        meta_path = self.cache_dir / f"{key}.meta.json"
        body_path = self.cache_dir / f"{key}.body"
        if not meta_path.is_file() or not body_path.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        if meta.get("url") is None:
            return None
        age = self._clock() - float(meta.get("fetched_at") or 0.0)
        if age > self.max_cache_age_seconds:
            return None
        meta["body"] = body_path.read_bytes()
        meta["reused"] = True
        meta["cache_age_seconds"] = round(age, 3)
        return meta

    def _write_cache(self, key: str, meta: dict[str, Any]) -> None:
        (self.cache_dir / f"{key}.body").write_bytes(meta["body"])
        stored = {k: v for k, v in meta.items() if k != "body"}
        (self.cache_dir / f"{key}.meta.json").write_text(
            json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- transport -----------------------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        *,
        key: str,
        json_body: Any = None,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        cached = None if self.bypass_cache else self._read_cache(key)
        if cached is not None:
            return cached
        headers = {"User-Agent": self.user_agent}
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)
        meta: dict[str, Any] = {"url": url, "method": method, "fetched_at": self._clock(),
                                "reused": False, "cache_age_seconds": 0.0}
        try:
            if method == "POST":
                headers.setdefault("Content-Type", "application/json")
                response = self.session.post(url, data=json_body, headers=headers,
                                             timeout=self.timeout)
            else:
                response = self.session.get(url, headers=headers, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - transport failure is reported, never hidden
            meta.update({"http_status": None, "body": b"", "transport_error":
                         f"{type(exc).__name__}: {exc}", "content_type": None})
            self._write_cache(key, meta)
            return meta
        body = bytes(response.content or b"")
        meta.update({
            "http_status": int(getattr(response, "status_code", 0) or 0),
            "content_type": str(getattr(response, "headers", {}).get("Content-Type", "") or ""),
            "body": body,
        })
        self._write_cache(key, meta)
        return meta

    def text(self, meta: dict[str, Any]) -> str:
        return meta.get("body", b"").decode("utf-8", "replace")

    def json_payload(self, meta: dict[str, Any]) -> Any:
        try:
            return json.loads(self.text(meta))
        except ValueError:
            return None


# ----------------------------------------------------------------------- adapters
def cninfo_fulltext(fetcher: ChannelFetcher, *, code: str, date_from: str, date_to: str
                    ) -> dict[str, Any]:
    params = (f"searchkey={quote(code)}&sdate={date_from}&edate={date_to}&isfulltext=false"
              "&sortName=nothing&sortType=desc&pageNum=1")
    url = f"{CNINFO_FULLTEXT_URL}?{params}"
    meta = fetcher.request("GET", url, key=f"cninfo_fulltext_{code}_{date_from}_{date_to}",
                           referer="http://www.cninfo.com.cn/")
    if meta.get("http_status") != 200:
        return {"channel": "cninfo_fulltext", "health": HEALTH_BROKEN, "records": [],
                "meta": meta, "error": meta.get("transport_error") or
                f"http_status={meta.get('http_status')}"}
    health, records = classify_cninfo_fulltext(fetcher.json_payload(meta))
    return {"channel": "cninfo_fulltext", "health": health, "records": records, "meta": meta}


def szse_announcements(fetcher: ChannelFetcher, *, code: str, date_from: str, date_to: str
                       ) -> dict[str, Any]:
    body = json.dumps({"seDate": [date_from, date_to], "stock": [code],
                       "channelCode": ["listedNotice_disc"], "pageSize": 30, "pageNum": 1})
    meta = fetcher.request("POST", SZSE_ANNLIST_URL,
                           key=f"szse_annlist_{code}_{date_from}_{date_to}", json_body=body,
                           referer="https://www.szse.cn/disclosure/listed/notice/index.html")
    if meta.get("http_status") != 200:
        return {"channel": "szse_announcements", "health": HEALTH_BROKEN, "records": [],
                "meta": meta, "error": meta.get("transport_error") or
                f"http_status={meta.get('http_status')}"}
    health, records = classify_szse_announcements(fetcher.json_payload(meta))
    return {"channel": "szse_announcements", "health": health, "records": records, "meta": meta}


def hkex_stock_id(fetcher: ChannelFetcher, *, code: str) -> dict[str, Any]:
    url = f"{HKEX_PREFIX_URL}?callback=cb&lang=ZH&type=A&name={quote(code)}&market=SEHK"
    meta = fetcher.request("GET", url, key=f"hkex_prefix_{code}")
    if meta.get("http_status") != 200:
        return {"health": HEALTH_BROKEN, "stock_id": None, "meta": meta}
    health, stocks = classify_hkex_prefix(fetcher.text(meta))
    if health != HEALTH_OK:
        return {"health": health, "stock_id": None, "meta": meta}
    padded = f"{int(code):05d}" if code.isdigit() else code
    for stock in stocks:
        if str(stock.get("code")) == padded:
            return {"health": HEALTH_OK, "stock_id": stock.get("stockId"), "meta": meta}
    return {"health": HEALTH_EMPTY, "stock_id": None, "meta": meta}


def hkex_news(fetcher: ChannelFetcher, *, stock_id: Any, date_from: str, date_to: str
              ) -> dict[str, Any]:
    params = ("sortDir=0&sortByOptions=DateTime&category=0&market=SEHK"
              f"&stockId={stock_id}&documentType=-1&fromDate={date_from}&toDate={date_to}"
              "&title=&searchType=1&t1code=-2&t2Gcode=-2&t2code=-2&rowRange=100&lang=ZH")
    url = f"{HKEX_SEARCH_URL}?{params}"
    meta = fetcher.request("GET", url, key=f"hkex_news_{stock_id}_{date_from}_{date_to}",
                           referer="https://www1.hkexnews.hk/")
    if meta.get("http_status") != 200:
        return {"channel": "hkex_news", "health": HEALTH_BROKEN, "records": [], "meta": meta}
    health, records = classify_hkex_news(fetcher.text(meta))
    return {"channel": "hkex_news", "health": health, "records": records, "meta": meta}


def sec_ticker_cik(fetcher: ChannelFetcher, *, ticker: str) -> dict[str, Any]:
    meta = fetcher.request("GET", SEC_TICKERS_URL, key="sec_company_tickers")
    if meta.get("http_status") != 200:
        return {"health": HEALTH_BROKEN, "cik": None, "meta": meta}
    payload = fetcher.json_payload(meta)
    if not isinstance(payload, dict):
        return {"health": HEALTH_BROKEN, "cik": None, "meta": meta}
    wanted = ticker.upper()
    for row in payload.values():
        if isinstance(row, dict) and str(row.get("ticker", "")).upper() == wanted:
            return {"health": HEALTH_OK, "cik": f"{int(row['cik_str']):010d}", "meta": meta}
    return {"health": HEALTH_EMPTY, "cik": None, "meta": meta}


def sec_submissions(fetcher: ChannelFetcher, *, cik: str) -> dict[str, Any]:
    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    meta = fetcher.request("GET", url, key=f"sec_submissions_{cik}")
    if meta.get("http_status") != 200:
        return {"channel": "sec_edgar", "health": HEALTH_BROKEN, "records": [], "meta": meta}
    health, records = classify_sec_submissions(fetcher.json_payload(meta))
    return {"channel": "sec_edgar", "health": health, "records": records, "meta": meta}


def fetch_document(fetcher: ChannelFetcher, *, url: str, key: str,
                   referer: str | None = None) -> dict[str, Any]:
    meta = fetcher.request("GET", url, key=key, referer=referer)
    status = meta.get("http_status")
    content_type = str(meta.get("content_type") or "")
    body = meta.get("body") or b""
    looks_like_document = bool(body) and (
        body[:5] == b"%PDF-" or "html" in content_type.lower() or "json" in content_type.lower()
        or "pdf" in content_type.lower() or "text" in content_type.lower()
    )
    health = HEALTH_OK if status == 200 and looks_like_document else HEALTH_BROKEN
    if health == HEALTH_OK and "html" in content_type.lower():
        text_head = body[:400].decode("utf-8", "replace").lower()
        if "waf" in text_head or "403 forbidden" in text_head or "request rate threshold" in text_head:
            health = HEALTH_BROKEN
    return {"health": health, "meta": meta,
            "content_sha256": sha256_bytes(body) if body else None,
            "bytes": len(body), "content_type": content_type}
