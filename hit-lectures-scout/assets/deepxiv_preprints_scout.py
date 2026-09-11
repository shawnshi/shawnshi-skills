"""
deepxiv_preprints_scout.py — ArXiv Preprints Recon via deepxiv-sdk
=================================================================
在确认 Python 与 deepxiv-sdk 可用后，可由当前命令环境调用。
输出结构化 Markdown 至 Response_Preprints.md。

Usage:
    python deepxiv_preprints_scout.py [--window DAYS] [--output PATH]
"""

import argparse
import hashlib
import inspect
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

Reader = None
APIError = None


class SchemaError(ValueError):
    """The supported SDK contract was not met; never evidence of empty results."""


def check_envelope(raw, operation):
    """Reject the raw shapes that SDK 0.3.1 otherwise converts to fake empty."""
    if not isinstance(raw, dict) or not raw:
        raise SchemaError("missing response object")
    if operation == "search":
        if raw.get("status") != "success":
            raise SchemaError("search status")
        key, count_key = "result", "total_count"
    elif operation == "trending":
        if "status" in raw and raw["status"] != "success":
            raise SchemaError("trending status")
        key, count_key = "papers", "total"
    elif operation == "brief":
        if "status" in raw and raw["status"] != "success":
            raise SchemaError("brief status")
        if not any(k in raw for k in PAPER_FIELDS):
            raise SchemaError("missing brief metadata")
        return raw
    else:
        raise SchemaError("unsupported operation")
    if not isinstance(raw.get(key), list):
        raise SchemaError("missing paper list")
    count = raw.get(count_key)
    if type(count) is not int or count < len(raw[key]):
        raise SchemaError("invalid count")
    if not raw[key] and count != 0:
        raise SchemaError("positive count without candidates")
    return raw


def _load_deepxiv_sdk():
    """Private request seam is pinned to installed 0.3.1; no alternate HTTP path."""
    global Reader, APIError
    if Reader is not None:
        return
    if version("deepxiv-sdk") != "0.3.1":
        raise SchemaError("unsupported SDK version")
    from deepxiv_sdk import APIError as DeepXivAPIError
    from deepxiv_sdk import Reader as DeepXivReader

    if tuple(inspect.signature(DeepXivReader._make_request).parameters) != (
        "self",
        "url",
        "params",
        "retry_count",
    ):
        raise SchemaError("unsupported SDK request signature")

    class CheckedReader(DeepXivReader):
        def _make_request(self, url, params=None, retry_count=0):
            raw = super()._make_request(url, params, retry_count)
            kind = (params or {}).get("type")
            if kind in ("retrieve", "brief"):
                check_envelope(raw, "search" if kind == "retrieve" else "brief")
            elif url == "https://api.rag.ac.cn/trending_arxiv_papers/api/trending":
                if not isinstance(raw, dict) or (
                    "status" in raw and raw["status"] != "success"
                ):
                    raise SchemaError("trending wrapper")
                check_envelope(raw.get("data"), "trending")
            else:
                raise SchemaError("unsupported SDK request")
            return raw

    Reader = CheckedReader
    APIError = DeepXivAPIError


@contextmanager
def private_sdk_logs():
    """Single CLI call only: upstream logs may contain tokens, URLs or bodies."""
    names = (
        "deepxiv_sdk",
        "deepxiv_sdk.reader",
        "requests",
        "urllib3",
        "urllib3.connection",
        "urllib3.connectionpool",
        "urllib3.util.retry",
    )
    loggers = [logging.getLogger(name) for name in names]
    previous = [logger.disabled for logger in loggers]
    try:
        for logger in loggers:
            logger.disabled = True
        yield
    finally:
        for logger, disabled in zip(loggers, previous, strict=True):
            logger.disabled = disabled


def error_detail(exc):
    """Keep native exception chain and stack locations, never messages/locals/source."""
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        frames, tb = [], exc.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            frames.append(
                {
                    "file": os.path.basename(code.co_filename),
                    "function": code.co_name,
                    "line": tb.tb_lineno,
                }
            )
            tb = tb.tb_next
        codes = {}
        for key in ("code", "status_code", "errno", "winerror"):
            value = getattr(exc, key, None)
            if type(value) is int and -65535 <= value <= 65535:
                codes[key] = value
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            codes["status_code"] = status
        # 0.3.1 encodes HTTP codes in exception classes/messages, not attributes.
        if type(exc).__module__ == "deepxiv_sdk.reader":
            known = {
                "AuthenticationError": 401,
                "BadRequestError": 400,
                "NotFoundError": 404,
                "RateLimitError": 429,
            }
            if type(exc).__name__ in known:
                codes.setdefault("status_code", known[type(exc).__name__])
            elif type(exc).__name__ == "ServerError":
                match = re.fullmatch(r"Server error (5\d\d)", str(exc))
                if match:
                    codes.setdefault("status_code", int(match[1]))
        chain.append(
            {
                "type": type(exc).__module__ + "." + type(exc).__name__,
                "codes": codes,
                "traceback": frames,
            }
        )
        exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
    return chain


def record_failure(receipt, phase, exc):
    receipt[phase]["failed"] += 1
    receipt["errors"].append(
        {
            "phase": phase,
            "call": receipt[phase]["attempted"],
            "category": "schema_error"
            if isinstance(exc, SchemaError)
            else "call_error",
            "chain": error_detail(exc),
        }
    )


def new_receipt(include_trending, queries=None):
    return {
        "status": "error",
        "source": "deepxiv-sdk/0.3.1",
        "candidate_only": True,
        "queries": list(SEARCH_QUERIES if queries is None else queries),
        "counts": dict.fromkeys(
            (
                "retrieved",
                "dedup",
                "eligible",
                "unverified",
                "enriched",
                "rendered",
                "out_of_range",
                "supplemental",
            ),
            0,
        ),
        "search": {
            "planned": len(SEARCH_QUERIES if queries is None else queries),
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
        },
        "trending": {
            "planned": int(include_trending),
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
        },
        "brief": {"planned": 0, "attempted": 0, "succeeded": 0, "failed": 0},
        "query_coverage": [],
        "pool_count": 0,
        "rendered_count": 0,
        "errors": [],
    }


# ============================================================
# 检索配置 — 可通过 task_preprints.md 同步维护
# ============================================================
SEARCH_QUERIES = [
    "clinical AI large language model",
    "medical foundation model multimodal",
    "healthcare reasoning agent workflow",
    "biomedical knowledge graph LLM",
    "digital health federated learning",
    "radiology AI diagnostic imaging",
    "EHR clinical NLP transformer",
]

CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "q-bio.QM"]

MAX_PER_QUERY = 15  # 每个 query 拉取上限
TOP_N_ENRICH = 30  # brief() 提纯数量上限
DEFAULT_WINDOW = 7  # 默认检索窗口 (天)
DEFAULT_OUTPUT = os.path.join(
    os.getcwd(),
    "Response_Preprints.md",
)


def build_reader(request_timeout=45):
    """构建 Reader 实例，优先从环境变量加载 token。"""
    _load_deepxiv_sdk()
    token = os.environ.get("DEEPXIV_TOKEN")
    if not token:
        print(
            "⚠️  DEEPXIV_TOKEN 未配置。将尝试免认证模式（功能受限）。", file=sys.stderr
        )
    # SDK retries are additional attempts: 2 retries => at most 3 HTTP attempts.
    assert Reader is not None
    return Reader(token=token, timeout=request_timeout, max_retries=2)


PAPER_FIELDS = (
    "arxiv_id",
    "title",
    "publish_at",
    "tldr",
    "abstract",
    "github_url",
    "src_url",
    "categories",
    "keywords",
    "citations",
    "citation",
    "score",
    "authors",
    "version",
    "version_date",
)
MAX_QUERIES = 20
MAX_QUERY_LENGTH = 300
MAX_TEXT = 4000
MAX_LIST = 50
IDENTITY_FIELDS = (
    "arxiv_id",
    "publish_at",
    "version",
    "version_date",
    "authors",
    "title",
)


def arxiv_base(aid):
    """Syntax only, never proof that an ID/version exists at arXiv."""
    match = re.fullmatch(
        r"(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5})(?:v[1-9]\d{0,3})?", aid, re.ASCII
    )
    if match:
        base = match[1]
        stamp = int(base[:4])
        if stamp >= 704 and len(base.split(".")[1]) == (5 if stamp >= 1501 else 4):
            return base
    match = re.fullmatch(
        r"([a-z][a-z-]{1,30}(?:\.[A-Z]{2})?/\d{2}(?:0[1-9]|1[0-2])\d{3})(?:v[1-9]\d{0,3})?",
        aid,
        re.ASCII,
    )
    if match:
        stamp = int(match[1].split("/")[1][:4])
        if 9108 <= stamp <= 9912 or 1 <= stamp <= 703:
            return match[1]
    return None


def markdown_text(value):
    # Numeric entities keep remote punctuation inert (including links/HTML/fences).
    text = " ".join(str(value)[:MAX_TEXT].split())
    return "".join(
        c if c.isalnum() or c == " " else f"&#{ord(c)};"
        for c in text
        if c.isprintable()
    )


def safe_url(value):
    if (
        not isinstance(value, str)
        or len(value) > 2000
        or any(c.isspace() or ord(c) < 32 for c in value)
    ):
        return None
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.password
            or "\\" in value
        ):
            return None
        _ = parts.port
        # Only authority brackets have IPv6 structure; encode other components
        # independently. Markdown entity protection belongs to the output layer.
        safe = ":/@!$&*+,;=%-._~"
        return urlunsplit((
            parts.scheme,
            quote(parts.netloc, safe=safe + "[]"),
            quote(parts.path, safe=safe),
            quote(parts.query, safe=safe + "?"),
            quote(parts.fragment, safe=safe + "?#"),
        ))
    except ValueError:
        return None


def receipt_json(receipt):
    return (
        json.dumps(receipt, ensure_ascii=True)
        .replace("`", "\\u0060")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def normalize_paper(raw, require_id=True):
    """Validate consumed fields once at entry; null means unknown, never zero."""
    if not isinstance(raw, dict):
        raise SchemaError("paper must be an object")
    paper = {}
    for key in PAPER_FIELDS:
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key in ("citations", "citation", "score"):
            if type(value) not in (int, float) or (
                type(value) is float and not math.isfinite(value)
            ):
                raise SchemaError("invalid numeric metadata")
            if key != "score" and (value < 0 or int(value) != value):
                raise SchemaError("invalid citation count")
        elif key in ("categories", "keywords", "authors"):
            if (
                isinstance(value, list)
                and len(value) <= MAX_LIST
                and all(isinstance(v, str) and len(v) <= MAX_TEXT for v in value)
            ):
                value = ", ".join(value)
            elif not isinstance(value, str):
                raise SchemaError("invalid string list")
        elif not isinstance(value, str):
            raise SchemaError("invalid text metadata")
        if isinstance(value, str) and len(value) > MAX_TEXT:
            raise SchemaError("text exceeds local limit")
        paper[key] = value
    if require_id and not paper.get("arxiv_id", "").strip():
        raise SchemaError("missing arxiv_id")
    if "citations" not in paper and "citation" in paper:
        paper["citations"] = paper["citation"]
    paper.pop("citation", None)
    return paper


def candidate_rows(raw, operation, limit):
    check_envelope(raw, operation)
    rows = raw["result" if operation == "search" else "papers"]
    if len(rows) > limit:
        raise SchemaError("response exceeds requested candidate limit")
    # Validate the whole batch before adding any of it to the pool.
    return [normalize_paper(row) for row in rows]


class CallBudget:
    """Admission budget, not cancellation of an in-flight requests/SDK call."""

    def __init__(self, seconds, max_calls):
        self.deadline = time.monotonic() + seconds
        self.max_calls = max_calls
        self.calls = 0

    def admit(self, receipt, phase):
        if receipt["errors"]:
            return False
        if time.monotonic() >= self.deadline or self.calls >= self.max_calls:
            receipt["errors"].append(
                {"phase": phase, "category": "budget_exhausted", "chain": []}
            )
            return False
        self.calls += 1
        return True


def add_candidates(pool, rows, source, receipt, supplemental=False):
    receipt["counts"]["retrieved"] += len(rows)
    for paper in rows:
        aid = paper["arxiv_id"]
        key = ("trending", aid) if supplemental else aid
        existing = pool.get(key)
        conflicts = [
            field for field in IDENTITY_FIELDS
            if existing is not None and field in paper and field in existing
            and paper[field] != existing[field]
        ]
        base_id = arxiv_base(aid)
        id_version = aid[len(base_id):] if base_id else ""
        if id_version and "version" in paper and paper["version"] != id_version:
            if "version" not in conflicts:
                conflicts.append("version")
        retained = existing if existing is not None else paper
        for field in conflicts:
            retained.setdefault("_conflicts", []).append(field)
            receipt["errors"].append(
                {
                    "phase": "metadata",
                    "category": "identity_conflict",
                    "field": field,
                    "chain": [],
                }
            )
        if existing is not None:
            if source not in existing["_sources"]:
                existing["_sources"].append(source)
            # Check ALL identity conflicts before accepting any incoming metadata.
            if not conflicts:
                for field, value in paper.items():
                    existing.setdefault(field, value)
            continue
        paper["_sources"] = [source]
        paper["_supplemental"] = supplemental
        paper["_base_id"] = base_id
        pool[key] = paper


def classify_candidates(pool, date_from, date_to, receipt):
    counts = receipt["counts"]
    for key in ("eligible", "unverified", "out_of_range", "supplemental"):
        counts[key] = 0
    for paper in pool.values():
        try:
            published = date.fromisoformat(paper.get("publish_at", ""))
        except ValueError:
            published = None
        if not paper["_base_id"] or published is None:
            scope = "unverified"
        elif (
            not date.fromisoformat(date_from)
            <= published
            <= date.fromisoformat(date_to)
        ):
            scope = "out_of_range"
        else:
            scope = "supplemental" if paper["_supplemental"] else "eligible"
        paper["_scope"] = scope
        counts[scope] += 1
    counts["dedup"] = len(pool)  # Per source stream; trending is never a topic match.


def search_phase(
    reader, date_from: str, date_to: str, receipt: dict, budget=None
) -> dict:
    """Stop on the first surfaced failure; never hammer the same failed service."""
    pool = {}
    for q in receipt["queries"]:
        if receipt["errors"] or (budget and not budget.admit(receipt, "search")):
            break
        receipt["search"]["attempted"] += 1
        try:
            raw = reader.search(
                query=q,
                size=MAX_PER_QUERY,
                source="arxiv",
                categories=CATEGORIES,
                date_from=date_from,
                date_to=date_to,
            )
            rows = candidate_rows(raw, "search", MAX_PER_QUERY)
            add_candidates(pool, rows, q, receipt)
            receipt["search"]["succeeded"] += 1
            total_count = raw.get("total_count") if isinstance(raw, dict) else None
            receipt.setdefault("query_coverage", []).append(
                {
                    "query": q,
                    "limit": MAX_PER_QUERY,
                    "returned": len(rows),
                    "total_count": total_count,
                    "truncated": bool(
                        isinstance(total_count, int) and total_count > len(rows)
                    ),
                    "note": "总数字段由服务提供，未经独立核验；不保证全部相关或穷尽",
                }
            )
        except Exception as exc:
            # Terminal failure receipt, not a fallback or an empty-result conversion.
            record_failure(receipt, "search", exc)
            break
    return pool


def trending_phase(reader, pool: dict, receipt: dict, budget=None) -> dict:
    if receipt["errors"] or (budget and not budget.admit(receipt, "trending")):
        return pool
    receipt["trending"]["attempted"] += 1
    try:
        rows = candidate_rows(reader.trending(days=7, limit=30), "trending", 30)
        add_candidates(pool, rows, "__trending__", receipt, supplemental=True)
        receipt["trending"]["succeeded"] += 1
    except Exception as exc:
        record_failure(receipt, "trending", exc)
    return pool


def enrich_phase(
    reader, pool: dict, receipt: dict, max_enrich=TOP_N_ENRICH, budget=None
) -> list:
    """Enhance in discovery order; the limit never deletes unenhanced candidates."""
    selected = [
        p
        for p in pool.values()
        if p.get("_base_id") and p.get("_scope") != "out_of_range"
    ][:max_enrich]
    receipt["brief"]["planned"] = len(selected)
    for paper in selected:
        if receipt["errors"] or (budget and not budget.admit(receipt, "brief")):
            break
        receipt["brief"]["attempted"] += 1
        try:
            raw = reader.brief(paper["arxiv_id"])
            check_envelope(raw, "brief")
            brief = normalize_paper(raw, require_id=False)
            if not brief:
                raise SchemaError("missing brief metadata")
            conflicts = [
                k
                for k in IDENTITY_FIELDS
                if k in brief and k in paper and brief[k] != paper[k]
            ]
            id_version = re.search(r"v[1-9][0-9]*$", paper["arxiv_id"])
            if id_version and "version" in brief and brief["version"] != id_version[0]:
                conflicts.append("version")
            if conflicts:
                paper["_conflicts"] = conflicts
                raise SchemaError("brief identity or publication conflict")
            paper.update(brief)
            paper["_enriched"] = True
            receipt["brief"]["succeeded"] += 1
            receipt["counts"]["enriched"] += 1
        except Exception as exc:
            record_failure(receipt, "brief", exc)
            break
    return list(pool.values())


def render_markdown(papers: list, date_from: str, date_to: str, receipt: dict) -> str:
    """Phase 4: 渲染结构化 Markdown 报告。"""
    lines = [
        f"# ArXiv Preprints Recon ({date_from} ~ {date_to})",
        "",
        f"> Cutoff: {receipt.get('cutoff', 'N/A')} | Timezone: Asia/Shanghai | Inclusive calendar dates",
        f"> Source: deepxiv-sdk candidate metadata | Queries: {len(receipt['queries'])} | Categories: {', '.join(CATEGORIES)}",
        f"> Candidate pool: {receipt['pool_count']} | Rendered: {len(papers)}",
        "> CANDIDATE DRAFT ONLY — NOT a formal DHLS report or archive receipt.",
        "> Retrieval status below is NOT publication success. Only the terminal publication=verified receipt plus matching SHA-256 proves candidate output verification.",
        "> Status describes configured capped calls, not exhaustive research coverage.",
        "",
        "## Retrieval receipt",
        "```json",
        receipt_json(receipt),
        "```",
        "> Evidence status: all entries are preprint candidates; verify the source page, version, full text, and any later peer-reviewed publication before drawing conclusions.",
        "",
    ]

    sections = (
        ("eligible", "Date-eligible topic candidates (not verified studies)"),
        ("supplemental", "Trending supplement — NOT topic matches"),
        ("unverified", "Unverified identity/date — NOT current-period findings"),
        ("out_of_range", "Outside date range — NOT current-period findings"),
    )
    for scope, heading in sections:
        lines.extend([f"## {heading}", ""])
        for i, p in enumerate(papers, 1):
            if p.get("_scope", "unverified") != scope:
                continue
            aid = p.get("arxiv_id", "N/A")
            lines.append(f"### {i}. {markdown_text(p.get('title', 'N/A'))}")
            identity = (
                f"[{markdown_text(aid)}](https://arxiv.org/abs/{aid})"
                if arxiv_base(aid)
                else markdown_text(aid) + " (invalid syntax; isolated)"
            )
            lines.append(f"- **arXiv ID**: {identity}")
            lines.append(
                f"- **Base ID (syntax association only)**: {markdown_text(p.get('_base_id') or 'N/A')}"
            )
            for field, label in (
                ("citations", "Citations"),
                ("categories", "Categories"),
                ("publish_at", "Published"),
                ("authors", "Authors"),
                ("version", "SDK version"),
                ("version_date", "SDK version date"),
                ("tldr", "TLDR"),
                ("abstract", "Abstract"),
                ("keywords", "Keywords"),
            ):
                lines.append(f"- **{label}**: {markdown_text(p.get(field, 'N/A'))}")
            lines.append(
                "- **Review status**: Preprint candidate / verify source and later publication"
            )
            for field, label in (("github_url", "GitHub"), ("src_url", "Source URL")):
                if field in p:
                    url = safe_url(p[field])
                    lines.append(
                        f"- **{label}**: [source]({url.replace('&', '&amp;')})"
                        if url
                        else f"- **{label}**: rejected unsafe URL"
                    )
            label = (
                "Trending source (not topic match)"
                if p.get("_supplemental")
                else "Matched queries"
            )
            for source in p.get("_sources", []):
                lines.append(f"- **{label}**: {markdown_text(source)}")
            lines.append(f"- **Brief enhanced**: {bool(p.get('_enriched'))}")
            if p.get("_conflicts"):
                lines.append(
                    f"- **Identity conflict; original retained**: {markdown_text(', '.join(p['_conflicts']))}"
                )
            lines.append("")

    return "\n".join(lines)


def positive_window(value):
    days = int(value)
    if not 1 <= days <= 366:
        raise argparse.ArgumentTypeError("window must be 1..366 calendar days")
    return days


def current_time():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def resolve_scope(args, parser: argparse.ArgumentParser):
    now = current_time()  # One wall-clock snapshot for the whole task.
    try:
        cutoff = datetime.fromisoformat(args.cutoff) if args.cutoff else now
        if cutoff.utcoffset() is None or cutoff > now:
            raise ValueError("cutoff must have an offset and not be in the future")
        cutoff = cutoff.astimezone(ZoneInfo("Asia/Shanghai"))
        if bool(args.date_from) != bool(args.date_to):
            raise ValueError("date-from and date-to must be paired")
        if args.date_from and args.window is not None:
            raise ValueError("explicit dates cannot be combined with window")
        end = date.fromisoformat(args.date_to) if args.date_to else cutoff.date()
        start = (
            date.fromisoformat(args.date_from)
            if args.date_from
            else end - timedelta(days=(args.window or DEFAULT_WINDOW) - 1)
        )
        if start > end or end > cutoff.date() or (end - start).days >= 366:
            raise ValueError(
                "dates must be ordered, not future, and span at most 366 calendar days"
            )
        queries = args.query if args.query is not None else SEARCH_QUERIES
        if len(queries) > MAX_QUERIES or any(
            not q.strip() or len(q) > MAX_QUERY_LENGTH or any(ord(c) < 32 for c in q)
            for q in queries
        ):
            raise ValueError(
                "query requires 1..300 non-control characters; at most 20 queries"
            )
        if not 0 <= args.max_enrich <= TOP_N_ENRICH:
            raise ValueError("max-enrich must be 0..30")
        if not 1 <= args.budget_seconds <= 3600 or not 1 <= args.request_timeout <= 120:
            raise ValueError("budget-seconds must be 1..3600; request-timeout 1..120")
    except (ValueError, OverflowError) as exc:
        parser.error(str(exc))
    trending = (
        args.include_trending and end == now.date() and start == end - timedelta(days=6)
    )
    return (
        start.isoformat(),
        end.isoformat(),
        cutoff.isoformat(),
        list(queries),
        trending,
    )


def preflight_output(value):
    """Candidate-only local Windows destination. No parent creation/overwrite."""
    if os.name != "nt" or sys.version_info < (3, 13):
        raise OSError("candidate files require Windows and Python >=3.13")
    if not value or value.startswith(("\\\\", "//")):
        raise ValueError("local candidate path required")
    raw_path = Path(value)
    if raw_path.drive and not raw_path.root:
        raise ValueError("drive-relative output is ambiguous")
    # Windows abspath can strip trailing dots: reject the original spelling first.
    for part in raw_path.parts[1:] if raw_path.anchor else raw_path.parts:
        if (
            part.endswith((" ", "."))
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or re.fullmatch(
                r"(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", part, re.I
            )
        ):
            raise ValueError("invalid Windows path component")
    path = Path(os.path.abspath(value))
    if (
        path.suffix.lower() != ".md"
        or path.name.lower().startswith("dhls-")
        or any(p.lower() == "digitalhealthlecturesscout" for p in path.parts)
    ):
        raise ValueError("formal DHLS/archive targets are forbidden for candidates")
    if os.path.lexists(path):
        raise FileExistsError("candidate target exists")
    if not path.parent.is_dir():
        raise FileNotFoundError("candidate parent is missing")
    if any(
        p.is_symlink() or p.is_junction() for p in (path.parent, *path.parent.parents)
    ):
        raise ValueError("reparse parents are not supported")
    return path


def check_private_acl(path, directory=False):
    """Validate native 3.13 mkdir(0700) policy, not chmod or formal archive policy."""
    import win32security

    sd = win32security.GetFileSecurity(
        str(path),
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION,
    )
    acl = sd.GetSecurityDescriptorDacl()
    if acl is None or acl.GetAceCount() == 0:
        raise PermissionError("private candidate ACL unavailable")
    owner = win32security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
    allowed = {owner, "S-1-3-4", "S-1-5-18", "S-1-5-32-544"}
    for i in range(acl.GetAceCount()):
        ace = acl.GetAce(i)
        if (
            ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE
            or win32security.ConvertSidToStringSid(ace[2]) not in allowed
        ):
            raise PermissionError("unexpected candidate ACL trustee")
    if (
        directory
        and not sd.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
    ):
        raise PermissionError("candidate directory ACL is not protected")


def prepare_output(path, publication):
    stage = Path(tempfile.mkdtemp(prefix=".deepxiv-draft-", dir=path.parent))
    publication["draft_directory"] = str(stage)
    check_private_acl(stage, directory=True)
    return stage


def write_complete(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    check_private_acl(path)
    if path.read_bytes() != data:
        raise OSError("staged readback mismatch")


def publish_candidate(path, stage, data, publication):
    """Windows rename is no-replace; never delete/roll back a competing target."""
    publication["state"] = "error"
    publication["failure_scope"] = "staging"
    draft = stage / "candidate.draft.md"
    publication["draft"] = str(draft)
    write_complete(draft, data)
    pending = stage / "publish.tmp"
    write_complete(pending, data)
    # Recheck scope/parent immediately before native same-volume publication.
    preflight_output(str(path))
    publication["failure_scope"] = "rename"
    os.rename(pending, path)  # Windows only, intentionally not os.replace.
    publication["failure_scope"] = (
        "post_rename_readback; target may exist; no automatic rollback"
    )
    check_private_acl(path)
    if path.read_bytes() != data:
        raise OSError("published readback mismatch")
    publication.update(
        state="verified", sha256=hashlib.sha256(data).hexdigest(), failure_scope=None
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Bounded ArXiv candidate drafts; Windows/Python >=3.13 file output, never formal DHLS archive"
    )
    parser.add_argument(
        "--window",
        type=positive_window,
        default=None,
        help="1..366 calendar days including cutoff day (default: 7)",
    )
    parser.add_argument("--date-from", help="paired inclusive ISO date")
    parser.add_argument("--date-to", help="paired inclusive ISO date")
    parser.add_argument(
        "--cutoff",
        help="offset ISO timestamp, not future; default: one Asia/Shanghai snapshot",
    )
    parser.add_argument(
        "--query",
        action="append",
        help="repeat to replace default queries (max 20, 300 chars each)",
    )
    parser.add_argument(
        "--include-trending",
        action="store_true",
        help="independent supplement; only for current exact seven-day window",
    )
    parser.add_argument(
        "--max-enrich",
        type=int,
        default=TOP_N_ENRICH,
        help="0..30 briefs in discovery order; retain every bounded candidate",
    )
    parser.add_argument(
        "--budget-seconds",
        type=float,
        default=300,
        help="1..3600 total call-admission budget; not in-flight cancellation",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=45,
        help="1..120 SDK requests timeout, NOT a hard wall-clock deadline",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help="new local .md candidate path; parent must exist",
    )
    args = parser.parse_args(argv)
    receipt = new_receipt(args.include_trending, args.query)
    publication = {"state": "not_attempted", "sha256": None}
    phase = "setup"
    try:
        # Capability failures use the setup receipt; argparse SystemExit stays 2.
        date_from, date_to, cutoff, queries, trending = resolve_scope(args, parser)
        receipt = new_receipt(trending, queries)
        receipt.update(
            date_from=date_from,
            date_to=date_to,
            cutoff=cutoff,
            timezone="Asia/Shanghai",
            trending_requested=args.include_trending,
            trending_skip_reason="window is not current exact seven days"
            if args.include_trending and not trending
            else None,
            max_enrich=args.max_enrich,
            budget_seconds=args.budget_seconds,
            request_timeout=args.request_timeout,
            max_logical_calls=len(queries) + int(trending) + args.max_enrich,
        )
        phase = "preflight"
        budget = CallBudget(args.budget_seconds, receipt["max_logical_calls"])
        output = preflight_output(args.output)
        publication["target"] = str(output)
        stage = prepare_output(output, publication)
        phase = "setup"
        with private_sdk_logs():
            reader = build_reader(args.request_timeout)
            pool = search_phase(reader, date_from, date_to, receipt, budget)
            if trending and not receipt["errors"]:
                trending_phase(reader, pool, receipt, budget)
            classify_candidates(pool, date_from, date_to, receipt)
            papers = enrich_phase(reader, pool, receipt, args.max_enrich, budget)
            classify_candidates(pool, date_from, date_to, receipt)
        if not receipt["errors"] and time.monotonic() >= budget.deadline:
            receipt["errors"].append(
                {"phase": "completion", "category": "budget_exhausted", "chain": []}
            )
        receipt["logical_calls"] = budget.calls
        receipt["pool_count"] = len(pool)
        receipt["rendered_count"] = len(papers)
        receipt["counts"]["rendered"] = len(papers)
        receipt["status"] = (
            ("partial" if pool else "error")
            if receipt["errors"]
            else ("success" if pool else "empty")
        )
        if receipt["status"] != "error":
            phase = "output"
            report = render_markdown(papers, date_from, date_to, receipt)
            publish_candidate(output, stage, report.encode("utf-8"), publication)
    except Exception as exc:
        failure = {
            "phase": phase,
            "category": "schema_error"
            if isinstance(exc, SchemaError)
            else "call_error",
            "chain": error_detail(exc),
        }
        if phase in ("output", "preflight"):
            publication.update(state="error", error=failure)
        else:
            receipt["status"] = "error"
            receipt["errors"].append(failure)
    terminal = {"retrieval": receipt, "publication": publication}
    print(receipt_json(terminal), file=sys.stderr)
    if publication["state"] != "verified":
        return 1
    return {"success": 0, "empty": 0, "partial": 3, "error": 1}[receipt["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
