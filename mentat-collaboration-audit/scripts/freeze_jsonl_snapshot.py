import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _last_complete_line_end(data):
    if not data:
        return 0
    return data.rfind(b"\n") + 1


def freeze_jsonl(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(output)
    if source == output:
        raise ValueError("source and output must differ")

    with open(source, "rb", buffering=0) as handle:
        captured_size = os.fstat(handle.fileno()).st_size
        data = handle.read(captured_size)
    complete_end = _last_complete_line_end(data)
    frozen = data[:complete_end]

    records = 0
    for line_number, line in enumerate(frozen.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at frozen line {line_number}: {exc}") from exc
        records += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=output.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(frozen)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, output)
        os.unlink(temp_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    return {
        "schema_version": 1,
        "source_name": source.name,
        "captured_source_bytes": captured_size,
        "frozen_bytes": len(frozen),
        "records": records,
        "trailing_partial_record_excluded": complete_end < len(data),
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "snapshot_path": str(output),
        "snapshot_sha256": hashlib.sha256(frozen).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt")
    args = parser.parse_args()

    receipt = freeze_jsonl(args.source, args.output)
    if args.receipt:
        receipt_path = Path(args.receipt).resolve()
        if receipt_path.exists():
            raise FileExistsError(receipt_path)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
