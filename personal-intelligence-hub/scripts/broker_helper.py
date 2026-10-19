"""Parent broker automation helper.

Provides deterministic CLI actions for the parent agent to reserve, capture,
assemble, and record broker native fetches and web searches without manual
assembly of raw JSON structures.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\nStderr: {p.stderr}\nStdout: {p.stdout}")
    return json.loads(p.stdout)


def reserve_fetch(scripts_dir: Path, request_path: Path, gap_id: str, url: str) -> dict:
    cmd = [
        sys.executable, "-B", "-X", "utf8",
        str(scripts_dir / "supplement_agent.py"),
        "broker-reserve-fetch",
        "--parent",
        "--request", str(request_path),
        "--gap-id", gap_id,
        "--url", url,
    ]
    res = run_cmd(cmd)
    res_id = res["fetch_reservations"][-1]["id"]
    return {"reservation_id": res_id, "data": res}


def record_fetch(
    scripts_dir: Path,
    request_path: Path,
    gap_id: str,
    reservation_id: str,
    url: str,
    started_at: str,
    completed_at: str,
    tool_output_file: Path,
    out_receipt_file: Path,
) -> dict:
    run_dir = request_path.resolve().parent
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    ledger = manifest["article_broker_evidence"][gap_id]

    events = ledger["events"]
    res_event = None
    for e in reversed(events):
        if e.get("id") == reservation_id and e.get("kind") == "fetch_reserved":
            res_event = e
            break
    if not res_event:
        raise ValueError(f"Reservation {reservation_id} not found in ledger")

    header = {
        "request_sha256": ledger["request_sha256"],
        "gap_id": gap_id,
        "reservation_id": reservation_id,
        "invocation_id": res_event["invocation_id"],
        "tool": "fetch_content",
        "arguments": res_event["arguments"],
        "started_at": started_at,
        "completed_at": completed_at,
        "outcome": "success",
        "error": None,
        "truncated": False,
        "parent_attestation": "actual_public_tool_receipt",
    }
    header_path = run_dir / f"header_{reservation_id}.json"
    header_path.write_text(json.dumps(header, ensure_ascii=False, indent=2), encoding="utf-8")

    assemble_cmd = [
        sys.executable, "-B", "-X", "utf8",
        str(scripts_dir / "receipt_assemble.py"),
        "--kind", "fetch",
        "--header", str(header_path),
        "--tool-output", str(tool_output_file),
        "--out", str(out_receipt_file),
    ]
    p_asm = subprocess.run(assemble_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if p_asm.returncode != 0:
        raise RuntimeError(f"receipt_assemble failed:\nStderr: {p_asm.stderr}\nStdout: {p_asm.stdout}")

    record_cmd = [
        sys.executable, "-B", "-X", "utf8",
        str(scripts_dir / "supplement_agent.py"),
        "broker-record-fetch",
        "--parent",
        "--request", str(request_path),
        "--gap-id", gap_id,
        "--receipt", str(out_receipt_file),
    ]
    return run_cmd(record_cmd)


def reserve_query(scripts_dir: Path, request_path: Path, gap_id: str, query: str, num_results: int = 5) -> dict:
    cmd = [
        sys.executable, "-B", "-X", "utf8",
        str(scripts_dir / "supplement_agent.py"),
        "broker-reserve-query",
        "--parent",
        "--request", str(request_path),
        "--gap-id", gap_id,
        "--query", query,
        "--num-results", str(num_results),
    ]
    res = run_cmd(cmd)
    res_id = res["query_reservations"][-1]["id"]
    return {"reservation_id": res_id, "data": res}


def record_query(
    scripts_dir: Path,
    request_path: Path,
    gap_id: str,
    reservation_id: str,
    query: str,
    response_id: str,
    results_list: list[dict],
    out_receipt_file: Path,
) -> dict:
    run_dir = request_path.resolve().parent
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    ledger = manifest["article_broker_evidence"][gap_id]

    cleaned_results = []
    for r in results_list:
        cleaned_results.append({
            "url": r["url"],
            "title": r.get("title") or r["url"],
        })

    outcome = "matched" if cleaned_results else "empty"

    receipt = {
        "request_sha256": ledger["request_sha256"],
        "gap_id": gap_id,
        "reservation_id": reservation_id,
        "tool": "web_search",
        "query": query,
        "responseId": response_id,
        "outcome": outcome,
        "error": None,
        "results": cleaned_results,
        "proof_subset": {
            "query": query,
            "count": len(cleaned_results),
            "responseId": response_id,
        },
        "parent_attestation": "actual_public_tool_receipt",
    }

    out_receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    record_cmd = [
        sys.executable, "-B", "-X", "utf8",
        str(scripts_dir / "supplement_agent.py"),
        "broker-record-query",
        "--parent",
        "--request", str(request_path),
        "--gap-id", gap_id,
        "--receipt", str(out_receipt_file),
    ]
    return run_cmd(record_cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parent broker automation helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rf = subparsers.add_parser("reserve-fetch")
    rf.add_argument("--request", type=Path, required=True)
    rf.add_argument("--gap-id", required=True)
    rf.add_argument("--url", required=True)

    rcf = subparsers.add_parser("record-fetch")
    rcf.add_argument("--request", type=Path, required=True)
    rcf.add_argument("--gap-id", required=True)
    rcf.add_argument("--reservation-id", required=True)
    rcf.add_argument("--url", required=True)
    rcf.add_argument("--started-at", required=True)
    rcf.add_argument("--completed-at", required=True)
    rcf.add_argument("--tool-output", type=Path, required=True)
    rcf.add_argument("--out-receipt", type=Path, required=True)

    rq = subparsers.add_parser("reserve-query")
    rq.add_argument("--request", type=Path, required=True)
    rq.add_argument("--gap-id", required=True)
    rq.add_argument("--query", required=True)
    rq.add_argument("--num-results", type=int, default=5)

    rcq = subparsers.add_parser("record-query")
    rcq.add_argument("--request", type=Path, required=True)
    rcq.add_argument("--gap-id", required=True)
    rcq.add_argument("--reservation-id", required=True)
    rcq.add_argument("--query", required=True)
    rcq.add_argument("--response-id", required=True)
    rcq.add_argument("--results-json", type=Path, required=True)
    rcq.add_argument("--out-receipt", type=Path, required=True)

    args = parser.parse_args()
    scripts_dir = Path(__file__).resolve().parent

    if args.command == "reserve-fetch":
        res = reserve_fetch(scripts_dir, args.request, args.gap_id, args.url)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.command == "record-fetch":
        res = record_fetch(
            scripts_dir,
            args.request,
            args.gap_id,
            args.reservation_id,
            args.url,
            args.started_at,
            args.completed_at,
            args.tool_output,
            args.out_receipt,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.command == "reserve-query":
        res = reserve_query(scripts_dir, args.request, args.gap_id, args.query, args.num_results)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    if args.command == "record-query":
        results = json.loads(args.results_json.read_text(encoding="utf-8"))
        res = record_query(
            scripts_dir,
            args.request,
            args.gap_id,
            args.reservation_id,
            args.query,
            args.response_id,
            results,
            args.out_receipt,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
