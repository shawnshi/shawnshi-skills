"""Single-writer atomic file commit. A failed replace never truncates the old file."""
import hashlib
import json
import os
import tempfile
from pathlib import Path


def atomic_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_text(path: Path, content: str) -> None:
    atomic_bytes(path, content.encode('utf-8'))


def snapshot_previous(task_dir: Path, summary_digest: str) -> Path:
    """Commit a manifest last; only then may the caller change current outputs."""
    directory = task_dir / 'recovery' / summary_digest
    manifest = directory / 'manifest.json'
    if manifest.is_file():
        existing = json.loads(manifest.read_text(encoding='utf-8'))
        if existing.get('summary_sha256') != summary_digest:
            raise ValueError('recovery summary identity mismatch')
        for entry in existing['files']:
            target = directory / entry['path']
            if target.resolve().is_relative_to(directory.resolve()) is False:
                raise ValueError('recovery path escaped snapshot')
            if hashlib.sha256(target.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('recovery snapshot integrity mismatch')
        return manifest
    files = []
    for relative in ('out/daily_run_summary.json', 'out/quotes.json', 'out/weights.json',
                     'out/daily_sync.json', 'out/refresh_receipt.json',
                     'inputs/positions_fx_snapshot.json', 'out/unpurchased_analysis.json',
                     'out/unpurchased_quotes.json', 'out/watchlist_results.json'):
        source = task_dir / relative
        if not source.is_file():
            continue
        raw = source.read_bytes()
        target = directory / relative
        atomic_bytes(target, raw)
        files.append({'path': relative, 'snapshot': str(target),
                      'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    manifest = directory / 'manifest.json'
    atomic_text(manifest, json.dumps({'summary_sha256': summary_digest, 'files': files}, indent=2))
    return manifest
