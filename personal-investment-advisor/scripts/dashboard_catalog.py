import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dashboard_gate import SCHEMA, validate_dashboard


INDEX_FILENAME = "dashboard_index.json"
LOCK_FILENAME = ".dashboard_index.lock"
GENERATIONS_DIRNAME = "generations"
INDEX_SCHEMA_VERSION = 3
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class DashboardCatalogError(ValueError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[0-9a-f]{64}", value)
    )


def _markdown_contains_payload(markdown: str, payload: dict) -> bool:
    canonical_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return f"```json\n{canonical_json}\n```" in markdown


def canonical_symbol(value: object) -> str:
    if not isinstance(value, str):
        raise DashboardCatalogError("stock symbol must be a string")
    symbol = value.strip().upper()
    if not symbol:
        raise DashboardCatalogError("stock symbol is required")
    return symbol


def safe_archive_component(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise DashboardCatalogError(f"{label} must be a string")
    component = value.strip()
    if (
        not component
        or component in {".", ".."}
        or component.endswith(".")
        or len(component) > 128
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", component)
        or component.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
    ):
        raise DashboardCatalogError(
            f"{label} contains characters that are unsafe for an archive path"
        )
    return component


def _is_linklike(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction and is_junction():
        return True
    if os.name == "nt":
        try:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            return False
        return bool(attributes & 0x400)
    return False


def _managed_file_path(root: Path, filename: str) -> Path:
    path = root / filename
    if _is_linklike(path):
        raise DashboardCatalogError(
            f"managed catalog file must not be a link: {filename}"
        )
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise DashboardCatalogError(
            f"managed catalog file escapes the archive root: {filename}"
        ) from exc
    return path


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


@contextmanager
def _catalog_lock(root: Path, timeout_seconds: float = 5.0):
    root.mkdir(parents=True, exist_ok=True)
    lock_path = _managed_file_path(root, LOCK_FILENAME)
    handle = lock_path.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            while not acquired:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise DashboardCatalogError(
                            "dashboard index is locked by another writer"
                        ) from exc
                    time.sleep(0.05)
        else:
            import fcntl

            while not acquired:
                try:
                    fcntl.flock(
                        handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                    acquired = True
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise DashboardCatalogError(
                            "dashboard index is locked by another writer"
                        ) from exc
                    time.sleep(0.05)
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _new_index() -> dict:
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "dashboard_contract_version": str(SCHEMA["version"]),
        "updated_at": None,
        "dashboards": {},
    }


def _load_index(index_path: Path) -> dict:
    if not index_path.exists():
        return _new_index()
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DashboardCatalogError("dashboard index is unreadable") from exc
    if not isinstance(index, dict):
        raise DashboardCatalogError("dashboard index root must be an object")
    if (
        type(index.get("schema_version")) is not int
        or index.get("schema_version") != INDEX_SCHEMA_VERSION
    ):
        raise DashboardCatalogError("dashboard index schema version is unsupported")
    if (
        not isinstance(index.get("dashboard_contract_version"), str)
        or index.get("dashboard_contract_version") != str(SCHEMA["version"])
    ):
        raise DashboardCatalogError("dashboard contract version is unsupported")
    if not isinstance(index.get("dashboards"), dict):
        raise DashboardCatalogError("dashboard index dashboards must be an object")
    if not isinstance(index.get("updated_at"), str):
        raise DashboardCatalogError(
            "dashboard index updated_at must be a timestamp string"
        )
    _parse_archived_at(index["updated_at"])
    return index


def _parse_archived_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise DashboardCatalogError(
            "dashboard index archived_at must be a string"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DashboardCatalogError(
            "dashboard index archived_at must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise DashboardCatalogError(
            "dashboard index archived_at must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _entry_sort_key(symbol: str, entry: dict) -> tuple[datetime, str]:
    if entry.get("dashboard_contract_version") != str(SCHEMA["version"]):
        raise DashboardCatalogError(
            f"dashboard index entry contract mismatch for {symbol}"
        )
    try:
        entry_symbol = canonical_symbol(entry.get("stock_code"))
    except DashboardCatalogError as exc:
        raise DashboardCatalogError(
            f"dashboard index entry for {symbol} has no valid stock_code"
        ) from exc
    if entry_symbol != symbol:
        raise DashboardCatalogError(
            f"dashboard index entry identity mismatch for {symbol}"
        )
    if not _valid_sha256(entry.get("json_sha256")) or not _valid_sha256(
        entry.get("markdown_sha256")
    ):
        raise DashboardCatalogError(
            f"dashboard index entry integrity metadata is invalid for {symbol}"
        )
    generation_id = safe_archive_component(
        entry.get("generation_id"),
        "generation_id",
    )
    return _parse_archived_at(entry.get("archived_at")), generation_id


def _expected_generation_paths(
    root: Path,
    symbol: str,
    generation_id: str,
) -> tuple[Path, Path]:
    safe_symbol = safe_archive_component(symbol, "stock_code")
    safe_generation = safe_archive_component(generation_id, "generation_id")
    generation_dir = (
        root
        / safe_symbol
        / GENERATIONS_DIRNAME
        / safe_generation
    )
    return generation_dir / "dashboard.json", generation_dir / "dashboard.md"


def _validate_generation_layout(
    root: Path,
    symbol: str,
    generation_id: str,
    json_path: Path,
    markdown_path: Path,
) -> None:
    expected_json, expected_markdown = _expected_generation_paths(
        root,
        symbol,
        generation_id,
    )
    if (
        json_path != expected_json.resolve()
        or markdown_path != expected_markdown.resolve()
    ):
        raise DashboardCatalogError(
            "dashboard index paths do not match the immutable generation layout"
        )

    symbol_dir = root / safe_archive_component(symbol, "stock_code")
    generations_dir = symbol_dir / GENERATIONS_DIRNAME
    generation_dir = generations_dir / safe_archive_component(
        generation_id,
        "generation_id",
    )
    for managed_dir in (symbol_dir, generations_dir, generation_dir):
        if managed_dir.exists() and _is_linklike(managed_dir):
            raise DashboardCatalogError(
                "dashboard generation path must not traverse a link"
            )


def _path_within_root(root: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str):
        raise DashboardCatalogError("dashboard index path must be a string")
    value = relative_path.strip()
    if not value:
        raise DashboardCatalogError("dashboard index path is required")
    candidate_value = Path(value)
    if candidate_value.is_absolute():
        raise DashboardCatalogError("dashboard index paths must be relative")
    try:
        indexed_path = root / candidate_value
        if _is_linklike(indexed_path):
            raise DashboardCatalogError(
                "dashboard index artifact path must not be a link"
            )
        candidate = indexed_path.resolve()
        candidate.relative_to(root)
    except DashboardCatalogError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise DashboardCatalogError(
            "dashboard index path is invalid or escapes the archive root"
        ) from exc
    return candidate


def register_dashboard(
    root: str | Path,
    dashboard: dict,
    json_path: str | Path,
    markdown_path: str | Path,
    archived_at: datetime,
    generation_id: str,
) -> dict:
    root_path = Path(root).expanduser().resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    symbol = canonical_symbol(dashboard.get("stock_code"))
    safe_archive_component(symbol, "stock_code")
    generation_id = safe_archive_component(generation_id, "generation_id")
    json_file = Path(json_path).resolve()
    markdown_file = Path(markdown_path).resolve()
    try:
        json_relative = json_file.relative_to(root_path).as_posix()
        markdown_relative = markdown_file.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise DashboardCatalogError(
            "dashboard artifacts must stay inside the archive root"
        ) from exc

    _validate_generation_layout(
        root_path,
        symbol,
        generation_id,
        json_file,
        markdown_file,
    )
    if _is_linklike(Path(json_path)) or _is_linklike(Path(markdown_path)):
        raise DashboardCatalogError(
            "dashboard artifacts must not be links"
        )
    if not json_file.is_file() or not markdown_file.is_file():
        raise DashboardCatalogError(
            "dashboard generation must contain both JSON and Markdown artifacts"
        )
    try:
        json_bytes = json_file.read_bytes()
        markdown_bytes = markdown_file.read_bytes()
        payload = json.loads(json_bytes.decode("utf-8"))
        markdown = markdown_bytes.decode("utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DashboardCatalogError(
            "dashboard generation artifacts are unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise DashboardCatalogError(
            "dashboard generation JSON root must be an object"
        )
    if payload != dashboard:
        raise DashboardCatalogError(
            "dashboard generation JSON does not match the registration payload"
        )
    validation_errors = validate_dashboard(payload)
    if validation_errors:
        raise DashboardCatalogError(
            "dashboard generation JSON failed the Dashboard gate: "
            + "; ".join(validation_errors)
        )
    if not markdown.strip() or not _markdown_contains_payload(
        markdown,
        payload,
    ):
        raise DashboardCatalogError(
            "dashboard generation Markdown does not contain the canonical JSON payload"
        )
    if archived_at.tzinfo is None:
        raise DashboardCatalogError("archived_at must include a timezone")
    timestamp = archived_at.astimezone(timezone.utc).isoformat()
    incoming_entry = {
        "stock_code": str(dashboard["stock_code"]).strip(),
        "dashboard_contract_version": str(SCHEMA["version"]),
        "generation_id": generation_id,
        "json_path": json_relative,
        "markdown_path": markdown_relative,
        "json_sha256": _sha256(json_bytes),
        "markdown_sha256": _sha256(markdown_bytes),
        "archived_at": timestamp,
    }
    incoming_key = (_parse_archived_at(timestamp), generation_id)
    index_path = _managed_file_path(root_path, INDEX_FILENAME)
    with _catalog_lock(root_path):
        index = _load_index(index_path)
        current_entry = index["dashboards"].get(symbol)
        if current_entry is not None and not isinstance(current_entry, dict):
            raise DashboardCatalogError(
                f"dashboard index entry for {symbol} must be an object"
            )
        if current_entry is not None:
            current_key = _entry_sort_key(symbol, current_entry)
            if incoming_key <= current_key:
                return {
                    "index_path": index_path,
                    "index_updated": False,
                    "active_entry": dict(current_entry),
                }

        index["dashboards"][symbol] = incoming_entry
        updated_at = incoming_key[0]
        if index.get("updated_at") is not None:
            updated_at = max(
                updated_at,
                _parse_archived_at(index["updated_at"]),
            )
        index["updated_at"] = updated_at.isoformat()
        _atomic_write_text(
            index_path,
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        )
    return {
        "index_path": index_path,
        "index_updated": True,
        "active_entry": dict(incoming_entry),
    }


def resolve_dashboards(root: str | Path, symbols: list[str]) -> dict:
    root_path = Path(root).expanduser().resolve()
    requested = [canonical_symbol(symbol) for symbol in symbols]
    duplicate_symbols = sorted(
        symbol for symbol in set(requested) if requested.count(symbol) > 1
    )
    unique_symbols = list(dict.fromkeys(requested))
    report = {
        "catalog_status": "ok",
        "dashboard_contract_version": str(SCHEMA["version"]),
        "requested_count": len(requested),
        "unique_requested_count": len(unique_symbols),
        "valid_count": 0,
        "complete": False,
        "duplicate_symbols": duplicate_symbols,
        "entries": [],
        "errors": [],
    }

    try:
        index_path = _managed_file_path(root_path, INDEX_FILENAME)
    except DashboardCatalogError as exc:
        report["catalog_status"] = "index_invalid"
        report["errors"].append(str(exc))
        report["entries"] = [
            {
                "symbol": symbol,
                "status": "insufficient_data",
                "reason": "dashboard_index_invalid",
            }
            for symbol in unique_symbols
        ]
        return report
    if not index_path.exists():
        report["catalog_status"] = "index_missing"
        report["entries"] = [
            {
                "symbol": symbol,
                "status": "insufficient_data",
                "reason": "dashboard_index_missing",
            }
            for symbol in unique_symbols
        ]
        return report

    try:
        index = _load_index(index_path)
    except DashboardCatalogError as exc:
        report["catalog_status"] = "index_invalid"
        report["errors"].append(str(exc))
        report["entries"] = [
            {
                "symbol": symbol,
                "status": "insufficient_data",
                "reason": "dashboard_index_invalid",
            }
            for symbol in unique_symbols
        ]
        return report

    for symbol in unique_symbols:
        entry = index["dashboards"].get(symbol)
        if not isinstance(entry, dict):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_not_indexed",
                }
            )
            continue
        try:
            indexed_symbol = canonical_symbol(entry.get("stock_code"))
        except DashboardCatalogError:
            indexed_symbol = ""
        if indexed_symbol != symbol:
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "index_stock_code_mismatch",
                }
            )
            continue
        if entry.get("dashboard_contract_version") != str(SCHEMA["version"]):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_contract_version_mismatch",
                }
            )
            continue
        expected_json_sha256 = entry.get("json_sha256")
        expected_markdown_sha256 = entry.get("markdown_sha256")
        if not _valid_sha256(expected_json_sha256) or not _valid_sha256(
            expected_markdown_sha256
        ):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_integrity_metadata_invalid",
                }
            )
            continue

        try:
            generation_id = safe_archive_component(
                entry.get("generation_id"),
                "generation_id",
            )
        except DashboardCatalogError as exc:
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "generation_id_invalid",
                    "errors": [str(exc)],
                }
            )
            continue

        try:
            json_path = _path_within_root(root_path, entry.get("json_path"))
            markdown_path = _path_within_root(
                root_path,
                entry.get("markdown_path"),
            )
            _validate_generation_layout(
                root_path,
                symbol,
                generation_id,
                json_path,
                markdown_path,
            )
        except DashboardCatalogError as exc:
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_path_invalid",
                    "errors": [str(exc)],
                }
            )
            continue
        if not json_path.is_file() or not markdown_path.is_file():
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_generation_incomplete",
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                    "json_available": json_path.is_file(),
                    "markdown_available": markdown_path.is_file(),
                }
            )
            continue

        try:
            json_bytes = json_path.read_bytes()
            payload = json.loads(json_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_unreadable",
                    "json_path": str(json_path),
                }
            )
            continue
        if not isinstance(payload, dict):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_root_invalid",
                    "json_path": str(json_path),
                }
            )
            continue
        try:
            payload_symbol = canonical_symbol(payload.get("stock_code"))
        except DashboardCatalogError:
            payload_symbol = ""
        if payload_symbol != symbol:
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "stock_code_mismatch",
                    "json_path": str(json_path),
                }
            )
            continue

        validation_errors = validate_dashboard(payload)
        if validation_errors:
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_invalid",
                    "json_path": str(json_path),
                    "validation_errors": validation_errors,
                }
            )
            continue
        try:
            markdown_bytes = markdown_path.read_bytes()
            markdown = markdown_bytes.decode("utf-8")
        except (OSError, UnicodeError):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_markdown_unreadable",
                    "markdown_path": str(markdown_path),
                }
            )
            continue
        if (
            _sha256(json_bytes) != expected_json_sha256
            or _sha256(markdown_bytes) != expected_markdown_sha256
        ):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_integrity_mismatch",
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                }
            )
            continue
        if not markdown.strip() or not _markdown_contains_payload(
            markdown,
            payload,
        ):
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "dashboard_markdown_invalid",
                    "markdown_path": str(markdown_path),
                }
            )
            continue

        try:
            archived_at = entry.get("archived_at")
            _parse_archived_at(archived_at)
        except DashboardCatalogError:
            report["entries"].append(
                {
                    "symbol": symbol,
                    "status": "insufficient_data",
                    "reason": "archive_timestamp_missing",
                    "json_path": str(json_path),
                }
            )
            continue

        report["valid_count"] += 1
        report["entries"].append(
            {
                "symbol": symbol,
                "status": "valid",
                "reason": None,
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
                "markdown_available": True,
                "archived_at": archived_at,
                "generation_id": generation_id,
                "monitoring_boundaries_defined": isinstance(
                    payload.get("monitoring_boundaries"),
                    dict,
                ),
            }
        )

    report["complete"] = (
        not duplicate_symbols
        and report["valid_count"] == len(unique_symbols)
        and len(unique_symbols) == len(requested)
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve the latest gate-valid Dashboard JSON for each requested symbol."
        )
    )
    parser.add_argument(
        "--root",
        help="Dashboard archive root; alternatively set PIA_DASHBOARD_DIR.",
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args()

    configured_root = args.root or os.environ.get("PIA_DASHBOARD_DIR")
    if not configured_root:
        parser.error(
            "dashboard archive root is required; pass --root or set PIA_DASHBOARD_DIR"
        )

    try:
        report = resolve_dashboards(configured_root, args.symbols)
    except DashboardCatalogError as exc:
        report = {
            "catalog_status": "invalid_request",
            "dashboard_contract_version": str(SCHEMA["version"]),
            "requested_count": len(args.symbols),
            "unique_requested_count": 0,
            "valid_count": 0,
            "complete": False,
            "duplicate_symbols": [],
            "entries": [],
            "errors": [str(exc)],
        }

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    message = json.dumps(report, ensure_ascii=False, indent=2)
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
