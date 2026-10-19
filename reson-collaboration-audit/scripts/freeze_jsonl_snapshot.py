import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


COPY_CHUNK_BYTES = 256 * 1024


def _freeze_captured_prefix(source, target, captured_size):
    search_end = captured_size
    stable_end = 0
    while search_end:
        read_size = min(COPY_CHUNK_BYTES, search_end)
        search_start = search_end - read_size
        source.seek(search_start)
        chunk = source.read(read_size)
        if len(chunk) != read_size:
            raise OSError("source changed while locating the captured newline boundary")
        last_newline = chunk.rfind(b"\n")
        if last_newline >= 0:
            stable_end = search_start + last_newline + 1
            break
        search_end = search_start

    source.seek(0)
    remaining = stable_end
    frozen_bytes = 0
    records = 0
    pending_nonblank = False
    digest = hashlib.sha256()
    while remaining:
        chunk = source.read(min(COPY_CHUNK_BYTES, remaining))
        if not chunk:
            raise OSError("source ended before the captured byte boundary")
        remaining -= len(chunk)
        target.write(chunk)
        digest.update(chunk)
        frozen_bytes += len(chunk)

        segments = chunk.split(b"\n")
        if len(segments) == 1:
            pending_nonblank = pending_nonblank or bool(segments[0].strip())
            continue
        records += int(pending_nonblank or bool(segments[0].strip()))
        records += sum(bool(segment.strip()) for segment in segments[1:-1])
        pending_nonblank = bool(segments[-1].strip())
    return frozen_bytes, records, digest.hexdigest()


def freeze_jsonl(source, output, receipt_path=None):
    source = Path(source).resolve()
    output = Path(output).resolve()
    receipt_path = Path(receipt_path).resolve() if receipt_path is not None else None
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(output)
    if source == output:
        raise ValueError("source and output must differ")
    if receipt_path is not None:
        if receipt_path.exists():
            raise FileExistsError(receipt_path)
        if receipt_path in {source, output}:
            raise ValueError("source, output, and receipt must be distinct")

    output.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path is not None:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    created: list[Path] = []
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        snapshot_temp = Path(temp_name)
        staged.append((snapshot_temp, output))
        with open(source, "rb", buffering=0) as source_handle, os.fdopen(fd, "wb") as target_handle:
            captured_size = os.fstat(source_handle.fileno()).st_size
            complete_end, records, snapshot_sha256 = _freeze_captured_prefix(
                source_handle, target_handle, captured_size
            )
            target_handle.flush()
            os.fsync(target_handle.fileno())

        receipt = {
            "schema_version": 1,
            "source_name": source.name,
            "captured_source_bytes": captured_size,
            "frozen_bytes": complete_end,
            "records": records,
            "trailing_partial_record_excluded": complete_end < captured_size,
            "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "snapshot_path": str(output),
            "snapshot_sha256": snapshot_sha256,
        }
        if receipt_path is not None:
            receipt_fd, receipt_temp_name = tempfile.mkstemp(
                prefix=f".{receipt_path.name}.", suffix=".tmp", dir=receipt_path.parent
            )
            receipt_temp = Path(receipt_temp_name)
            staged.append((receipt_temp, receipt_path))
            with os.fdopen(receipt_fd, "wb") as receipt_handle:
                receipt_handle.write(
                    (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                )
                receipt_handle.flush()
                os.fsync(receipt_handle.fileno())

        for temporary, final in staged:
            os.link(temporary, final)
            created.append(final)
        return receipt
    except Exception:
        for final in reversed(created):
            try:
                final.unlink()
            except OSError:
                pass
        raise
    finally:
        for temporary, _ in staged:
            try:
                temporary.unlink()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt")
    args = parser.parse_args()

    receipt = freeze_jsonl(args.source, args.output, args.receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
