#!/usr/bin/env python3
"""Analyze local activity files or explicitly download sensitive raw activity data.

Local parse/query/analyze actions are offline. Download requires three explicit
grants and a non-report output directory because files may contain GPS tracks.
"""

import json
import sys
import os
import tempfile
import hashlib
import io
import stat
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Sequence

from garmin_capabilities import (
    CapabilityError,
    consume_capability,
    issue_capability,
    require_capability,
)


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTHORIZATION = 3
EXIT_AUTH_FAILURE = 4
EXIT_OPERATION_FAILURE = 5
ACTIVITY_OPERATION = "activity_download"
MAX_ACTIVITY_BYTES = 64 * 1024 * 1024
FIT_CRC_TABLE = (
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
)


def _get_client(
    *,
    network_capability: object = None,
    health_data_capability: object = None,
    download_capability: object = None,
    request: dict[str, object] | None = None,
):
    """Load authentication only for an explicitly authorized download."""
    try:
        require_capability(
            network_capability,
            scope="network",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
    except CapabilityError as exc:
        raise PermissionError("network_authorization_required") from exc
    try:
        require_capability(
            health_data_capability,
            scope="health_data",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
    except CapabilityError as exc:
        raise PermissionError("health_data_authorization_required") from exc
    try:
        require_capability(
            download_capability,
            scope="download",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
    except CapabilityError as exc:
        raise PermissionError("download_authorization_required") from exc
    sys.path.insert(0, str(Path(__file__).parent))
    from garmin_auth import get_client
    return get_client(
        network_capability=network_capability,
        operation=ACTIVITY_OPERATION,
        request=request,
    )


def _report_directories() -> list[Path]:
    configured = os.environ.get("GARMIN_REPORT_DIR") or os.environ.get("GARMIN_OUTPUT_DIR")
    default = Path.cwd() / "output" / "personal-health-analysis"
    return [Path(configured).expanduser().resolve()] if configured else [default.resolve()]


def _is_report_directory(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    for report_dir in _report_directories():
        try:
            resolved.relative_to(report_dir)
            return True
        except ValueError:
            continue
    return False

# Check for optional dependencies
try:
    import fitparse
    HAS_FITPARSE = True
except ImportError:
    HAS_FITPARSE = False

try:
    import gpxpy
    import gpxpy.gpx
    HAS_GPXPY = True
except ImportError:
    HAS_GPXPY = False


def _fit_crc(payload: bytes, crc: int = 0) -> int:
    """Calculate the FIT protocol CRC-16 defined by Garmin's FIT SDK."""
    for byte in payload:
        temporary = FIT_CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ temporary ^ FIT_CRC_TABLE[byte & 0xF]
        temporary = FIT_CRC_TABLE[crc & 0xF]
        crc = (
            ((crc >> 4) & 0x0FFF)
            ^ temporary
            ^ FIT_CRC_TABLE[(byte >> 4) & 0xF]
        )
    return crc


def _validate_fit_payload(payload: bytes) -> None:
    """Fail closed unless a single FIT file passes header, size and CRC checks."""
    if not isinstance(payload, bytes) or len(payload) < 14:
        raise ValueError("activity_fit_header_invalid")
    header_size = payload[0]
    if header_size not in (12, 14) or len(payload) < header_size + 2:
        raise ValueError("activity_fit_header_invalid")
    if payload[8:12] != b".FIT":
        raise ValueError("activity_fit_signature_invalid")
    data_size = int.from_bytes(payload[4:8], byteorder="little", signed=False)
    if len(payload) != header_size + data_size + 2:
        raise ValueError("activity_fit_declared_size_mismatch")
    if header_size == 14:
        declared_header_crc = int.from_bytes(payload[12:14], "little")
        if declared_header_crc not in (0, _fit_crc(payload[:12])):
            raise ValueError("activity_fit_header_crc_invalid")
    declared_file_crc = int.from_bytes(payload[-2:], "little")
    if declared_file_crc != _fit_crc(payload[:-2]):
        raise ValueError("activity_fit_file_crc_invalid")


def _extract_single_fit(original_zip: bytes) -> bytes:
    """Extract exactly one bounded FIT member from Garmin's ORIGINAL ZIP."""
    if len(original_zip) > MAX_ACTIVITY_BYTES:
        raise ValueError("activity_archive_too_large")
    with zipfile.ZipFile(io.BytesIO(original_zip)) as archive:
        fit_members = []
        total_size = 0
        for member in archive.infolist():
            mode = member.external_attr >> 16
            normalized = member.filename.replace("\\", "/")
            parts = [part for part in normalized.split("/") if part]
            if normalized.startswith("/") or ".." in parts:
                raise ValueError("activity_archive_unsafe_path")
            if stat.S_ISLNK(mode) or member.flag_bits & 0x1:
                raise ValueError("activity_archive_unsupported_member")
            if member.is_dir():
                continue
            total_size += member.file_size
            if total_size > MAX_ACTIVITY_BYTES:
                raise ValueError("activity_archive_expanded_too_large")
            if normalized.casefold().endswith(".fit"):
                fit_members.append(member)
        if len(fit_members) != 1:
            raise ValueError("activity_archive_requires_single_fit")
        member = fit_members[0]
        with archive.open(member, "r") as source:
            payload = source.read(MAX_ACTIVITY_BYTES + 1)
        if len(payload) != member.file_size or len(payload) > MAX_ACTIVITY_BYTES:
            raise ValueError("activity_fit_size_mismatch")
        _validate_fit_payload(payload)
        return payload


def download_activity_file(
    client,
    activity_id,
    file_format="fit",
    output_dir=None,
    *,
    network_capability: object = None,
    health_data_capability: object = None,
    download_capability: object = None,
    request: dict[str, object] | None = None,
):
    """Download an activity file only with explicit network and download grants."""
    try:
        require_capability(
            network_capability,
            scope="network",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
    except CapabilityError:
        return {"error": "network_authorization_required", "activity_id": activity_id}
    try:
        require_capability(
            health_data_capability,
            scope="health_data",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
    except CapabilityError:
        return {"error": "health_data_authorization_required", "activity_id": activity_id}
    try:
        require_capability(
            download_capability,
            scope="download",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
    except CapabilityError:
        return {"error": "download_authorization_required", "activity_id": activity_id}
    if output_dir is None:
        return {"error": "explicit_output_dir_required", "activity_id": activity_id}
    if file_format.casefold() not in {"fit", "gpx", "tcx"}:
        return {"error": "unsupported_format", "activity_id": activity_id}
    output_dir = Path(output_dir).expanduser().resolve()
    if _is_report_directory(output_dir):
        return {"error": "report_directory_forbidden", "activity_id": activity_id}
    temporary_path = None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_path = output_dir / f"activity_{activity_id}_{timestamp}.{file_format.lower()}"
        
        consume_capability(
            health_data_capability,
            scope="health_data",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
        consume_capability(
            download_capability,
            scope="download",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
        if file_format.lower() == "fit":
            original_zip = client.download_activity(
                activity_id,
                dl_fmt=client.ActivityDownloadFormat.ORIGINAL,
            )
            data = _extract_single_fit(original_zip)
        elif file_format.lower() == "gpx":
            data = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.GPX)
        elif file_format.lower() == "tcx":
            data = client.download_activity(activity_id, dl_fmt=client.ActivityDownloadFormat.TCX)
        else:
            return {"error": "unsupported_format", "activity_id": activity_id}
        if not isinstance(data, bytes) or len(data) > MAX_ACTIVITY_BYTES:
            raise ValueError("activity_payload_invalid_or_too_large")
        
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output_dir, prefix=".activity-", suffix=".part", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, output_path)
        temporary_path.unlink()
        temporary_path = None
        
        return {
            "file": str(output_path),
            "activity_id": activity_id,
            "format": file_format,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    
    except Exception as e:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        return {"error": "download_failed", "error_type": type(e).__name__, "activity_id": activity_id}


def parse_fit_file(file_path):
    """Parse FIT file and extract all data points."""
    if not HAS_FITPARSE:
        return {"error": "fitparse library not installed. Run: pip install fitparse"}
    
    try:
        fitfile = fitparse.FitFile(file_path)
        
        # Extract different record types
        records = []
        laps = []
        sessions = []
        
        for record in fitfile.get_messages('record'):
            data_point = {}
            for field in record:
                if field.value is not None:
                    data_point[field.name] = field.value
            if data_point:
                records.append(data_point)
        
        for record in fitfile.get_messages('lap'):
            lap_data = {}
            for field in record:
                if field.value is not None:
                    lap_data[field.name] = field.value
            if lap_data:
                laps.append(lap_data)
        
        for record in fitfile.get_messages('session'):
            session_data = {}
            for field in record:
                if field.value is not None:
                    session_data[field.name] = field.value
            if session_data:
                sessions.append(session_data)
        
        return {
            "records": records,
            "laps": laps,
            "sessions": sessions,
            "total_records": len(records)
        }
    
    except Exception as e:
        return {"error": str(e)}


def parse_gpx_file(file_path):
    """Parse GPX file and extract track points."""
    if not HAS_GPXPY:
        return {"error": "gpxpy library not installed. Run: pip install gpxpy"}
    
    try:
        with open(file_path, 'r') as f:
            gpx = gpxpy.parse(f)
        
        points = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    points.append({
                        "latitude": point.latitude,
                        "longitude": point.longitude,
                        "elevation": point.elevation,
                        "time": point.time.isoformat() if point.time else None,
                        "speed": point.speed,
                        "hr": point.extensions.get("hr") if point.extensions else None
                    })
        
        return {
            "points": points,
            "total_points": len(points),
            "bounds": {
                "min_lat": gpx.get_bounds().min_latitude,
                "max_lat": gpx.get_bounds().max_latitude,
                "min_lon": gpx.get_bounds().min_longitude,
                "max_lon": gpx.get_bounds().max_longitude
            } if gpx.get_bounds() else None
        }
    
    except Exception as e:
        return {"error": str(e)}


def query_data_at_distance(data, distance_meters):
    """Find data point closest to a specific distance."""
    if "records" in data:
        records = data["records"]
    elif "points" in data:
        records = data["points"]
    else:
        return {"error": "No data records found"}
    
    # Find closest by distance
    closest = None
    min_diff = float('inf')
    
    for record in records:
        if "distance" in record:
            diff = abs(record["distance"] - distance_meters)
            if diff < min_diff:
                min_diff = diff
                closest = record
    
    return closest


def query_data_at_time(data, target_time):
    """Find data point at a specific time."""
    if "records" in data:
        records = data["records"]
    elif "points" in data:
        records = data["points"]
    else:
        return {"error": "No data records found"}
    
    # Parse target time
    if isinstance(target_time, str):
        try:
            target_dt = datetime.fromisoformat(target_time.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return {"error": f"Invalid time format: {target_time}"}
    else:
        target_dt = target_time
    
    target_ts = target_dt.timestamp()
    
    closest = None
    min_diff = float('inf')
    
    for record in records:
        if "timestamp" in record:
            if isinstance(record["timestamp"], datetime):
                rec_ts = record["timestamp"].timestamp()
            else:
                continue
            
            diff = abs(rec_ts - target_ts)
            if diff < min_diff:
                min_diff = diff
                closest = record
    
    return closest


def analyze_activity(data):
    """Analyze activity data and provide insights."""
    if "error" in data:
        return data
    
    records = data.get("records", [])
    if not records:
        return {"error": "No data records to analyze"}
    
    # Calculate statistics
    hr_values = [r.get("heart_rate") for r in records if r.get("heart_rate")]
    elevation_values = [r.get("altitude") or r.get("elevation") for r in records if r.get("altitude") or r.get("elevation")]
    speed_values = [r.get("speed") for r in records if r.get("speed")]
    cadence_values = [r.get("cadence") for r in records if r.get("cadence")]
    power_values = [r.get("power") for r in records if r.get("power")]
    
    analysis = {
        "total_points": len(records),
        "duration_seconds": None,
        "distance_meters": None,
        "heart_rate": {
            "avg": sum(hr_values) / len(hr_values) if hr_values else None,
            "max": max(hr_values) if hr_values else None,
            "min": min(hr_values) if hr_values else None
        },
        "elevation": {
            "max": max(elevation_values) if elevation_values else None,
            "min": min(elevation_values) if elevation_values else None,
            "gain": None  # Would need to calculate from sequential points
        },
        "speed": {
            "avg": sum(speed_values) / len(speed_values) if speed_values else None,
            "max": max(speed_values) if speed_values else None
        },
        "cadence": {
            "avg": sum(cadence_values) / len(cadence_values) if cadence_values else None
        } if cadence_values else None,
        "power": {
            "avg": sum(power_values) / len(power_values) if power_values else None,
            "max": max(power_values) if power_values else None
        } if power_values else None
    }
    
    # Get duration and distance from first/last records
    if records:
        if "timestamp" in records[0] and "timestamp" in records[-1]:
            if isinstance(records[0]["timestamp"], datetime):
                duration = (records[-1]["timestamp"] - records[0]["timestamp"]).total_seconds()
                analysis["duration_seconds"] = duration
        
        if "distance" in records[-1]:
            analysis["distance_meters"] = records[-1]["distance"]
    
    return analysis


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze Garmin activity files")
    parser.add_argument("action", nargs="?", choices=["download", "parse", "query", "analyze"],
                       help="Action to perform")
    parser.add_argument("--activity-id", type=int, help="Activity ID")
    parser.add_argument("--format", choices=["fit", "gpx", "tcx"], default="fit",
                       help="File format for download")
    parser.add_argument("--file", help="Path to local FIT/GPX file")
    parser.add_argument("--distance", type=float, help="Query data at distance (meters)")
    parser.add_argument("--time", help="Query data at time (ISO format)")
    parser.add_argument("--output-dir", help="Explicit directory for downloaded raw files")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly authorize a download to contact Garmin",
    )
    parser.add_argument(
        "--allow-health-data",
        action="store_true",
        help="Explicitly authorize reading the selected raw activity",
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Explicitly authorize saving the selected raw activity file",
    )
    return parser


def _emit(result):
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def main(argv: Sequence[str] | None = None):
    args = build_parser().parse_args(argv)
    if args.action is None:
        _emit({"ok": False, "status": "usage_error", "error": "action_required"})
        return EXIT_USAGE
    
    if args.action == "download":
        if not args.activity_id:
            _emit({"ok": False, "status": "usage_error", "error": "activity_id_required"})
            return EXIT_USAGE
        if not args.allow_network:
            _emit({"ok": False, "status": "network_authorization_required"})
            return EXIT_AUTHORIZATION
        if not args.allow_health_data:
            _emit({"ok": False, "status": "health_data_authorization_required"})
            return EXIT_AUTHORIZATION
        if not args.allow_download:
            _emit({"ok": False, "status": "download_authorization_required"})
            return EXIT_AUTHORIZATION
        if not args.output_dir:
            _emit({"ok": False, "status": "usage_error", "error": "explicit_output_dir_required"})
            return EXIT_USAGE
        output_dir = Path(args.output_dir).expanduser().resolve()
        if _is_report_directory(output_dir):
            _emit({"ok": False, "status": "usage_error", "error": "report_directory_forbidden"})
            return EXIT_USAGE

        request = {
            "activity_id": args.activity_id,
            "format": args.format,
            "output_dir": str(output_dir),
        }
        network_capability = issue_capability(
            scope="network",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
        health_data_capability = issue_capability(
            scope="health_data",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
        download_capability = issue_capability(
            scope="download",
            operation=ACTIVITY_OPERATION,
            request=request,
        )
        client = _get_client(
            network_capability=network_capability,
            health_data_capability=health_data_capability,
            download_capability=download_capability,
            request=request,
        )
        if not client:
            _emit({"ok": False, "status": "session_unavailable"})
            return EXIT_AUTH_FAILURE
        
        result = download_activity_file(
            client,
            args.activity_id,
            args.format,
            output_dir,
            network_capability=network_capability,
            health_data_capability=health_data_capability,
            download_capability=download_capability,
            request=request,
        )
        _emit(result)
        return EXIT_OPERATION_FAILURE if "error" in result else EXIT_OK
    
    elif args.action == "parse":
        if not args.file:
            _emit({"error": "file path required for parse"})
            return EXIT_USAGE
        
        if args.file.endswith('.fit'):
            result = parse_fit_file(args.file)
        elif args.file.endswith('.gpx'):
            result = parse_gpx_file(args.file)
        else:
            result = {"error": "Unsupported file type. Use .fit or .gpx"}
        
        _emit(result)
        return EXIT_OPERATION_FAILURE if "error" in result else EXIT_OK
    
    elif args.action == "query":
        if not args.file:
            _emit({"error": "file path required for query"})
            return EXIT_USAGE
        
        # First parse the file
        if args.file.endswith('.fit'):
            data = parse_fit_file(args.file)
        elif args.file.endswith('.gpx'):
            data = parse_gpx_file(args.file)
        else:
            _emit({"error": "Unsupported file type"})
            return EXIT_USAGE
        
        if "error" in data:
            _emit(data)
            return EXIT_OPERATION_FAILURE
        
        # Query
        if args.distance is not None:
            result = query_data_at_distance(data, args.distance)
        elif args.time:
            result = query_data_at_time(data, args.time)
        else:
            result = {"error": "Specify --distance or --time for query"}
        
        _emit(result)
        return EXIT_OPERATION_FAILURE if isinstance(result, dict) and "error" in result else EXIT_OK
    
    elif args.action == "analyze":
        if not args.file:
            _emit({"error": "file path required for analyze"})
            return EXIT_USAGE
        
        # Parse and analyze
        if args.file.endswith('.fit'):
            data = parse_fit_file(args.file)
        elif args.file.endswith('.gpx'):
            data = parse_gpx_file(args.file)
        else:
            _emit({"error": "Unsupported file type"})
            return EXIT_USAGE
        
        result = analyze_activity(data)
        _emit(result)
        return EXIT_OPERATION_FAILURE if "error" in result else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
