from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


def classify_source_type(candidate: dict[str, Any]) -> str:
    """Honor explicit classifications; infer only canonical arXiv paper URLs."""
    claimed = candidate.get("source_type")
    if claimed in ("primary", "secondary"):
        return str(claimed)
    try:
        url = urlsplit(str(candidate.get("url") or ""))
        if (
            url.scheme in {"http", "https"}
            and url.netloc.lower() == "arxiv.org"
            and re.fullmatch(
                r"/(?:abs|pdf)/(?:[0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})(?:v[0-9]+)?(?:\.pdf)?",
                url.path,
            )
        ):
            return "primary"
    except ValueError:
        pass
    return "secondary"
