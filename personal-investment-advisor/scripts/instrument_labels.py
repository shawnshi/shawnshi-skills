"""Attach human-readable instrument names to symbol-bearing rows.

Why this exists: a bare code such as ``601899.SS`` forces every reader to look the
name up elsewhere, and the authoritative display name already travels with the
user's own positions file. Rows therefore carry ``symbol_name`` (plain name) and
``display_label`` (``"601899.SS 紫金矿业"``) so code and name are never separated.

The name is display metadata only: it never participates in identity matching,
which stays bound to ``symbol``/``market``/``asset_type``.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

NAME_FIELD = "symbol_name"
LABEL_FIELD = "display_label"


def symbol_name_map(source: Any) -> dict[str, str]:
    """Build ``{SYMBOL: name}`` from a positions payload, a list of rows or a map."""
    if isinstance(source, Mapping):
        rows: Iterable[Any] = (
            source["positions"] if isinstance(source.get("positions"), list) else source.values()
        )
    elif isinstance(source, list):
        rows = source
    else:
        return {}
    names: dict[str, str] = {}
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").strip()
        name = item.get("name")
        if symbol and isinstance(name, str) and name.strip():
            names[symbol.upper()] = name.strip()
    return names


def name_for(symbol: Any, names: Mapping[str, str]) -> str | None:
    return names.get(str(symbol or "").strip().upper())


def label(symbol: Any, names: Mapping[str, str]) -> str:
    """``"601899.SS 紫金矿业"``; falls back to the bare code when no name is known."""
    text = str(symbol or "").strip()
    name = name_for(text, names)
    return f"{text} {name}" if name else text


def annotate_row(row: Any, names: Mapping[str, str]) -> Any:
    """Add ``symbol_name``/``display_label`` to one row, in place, only when known."""
    if not isinstance(row, dict):
        return row
    symbol = row.get("symbol")
    name = name_for(symbol, names)
    if name:
        row.setdefault(NAME_FIELD, name)
        row.setdefault(LABEL_FIELD, f"{str(symbol).strip()} {name}")
    return row


def annotate_rows(rows: Any, names: Mapping[str, str]) -> Any:
    for row in rows or []:
        annotate_row(row, names)
    return rows
