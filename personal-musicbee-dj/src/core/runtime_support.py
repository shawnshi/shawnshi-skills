"""Validate the reviewed standalone runtime without installing/downloading anything."""
from functools import lru_cache
from importlib import metadata
import json
import os
from pathlib import Path
import sys
from src.core.local_paths import local_path

ROOT = Path(__file__).resolve().parents[2]


def default_runtime_root():
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise RuntimeError('LOCALAPPDATA is required for the durable runtime')
    spec = json.loads((ROOT / 'runtime-manifest.json').read_text(encoding='utf-8'))
    return local_path(Path(base) / 'MusicBeeDJ' / spec['runtime_directory'])


@lru_cache(maxsize=1)
def verify_runtime():
    spec = json.loads((ROOT / 'runtime-manifest.json').read_text(encoding='utf-8'))
    if spec.get('schema_version') != 1 or sys.platform != spec['platform'] or list(sys.version_info[:3]) != spec['python']:
        raise RuntimeError('Runtime platform/Python differs from the reviewed manifest')
    prefix = local_path(Path(sys.prefix))
    config = prefix / 'pyvenv.cfg'
    if sys.prefix == sys.base_prefix or not config.is_file():
        raise RuntimeError('Use the reviewed isolated virtual environment')
    settings = {key.strip(): value.strip() for key, value in
                (line.split('=', 1) for line in config.read_text(encoding='utf-8').splitlines() if '=' in line)}
    if settings.get('include-system-site-packages', '').strip().lower() != 'false':
        raise RuntimeError('Inherited global site-packages denied')
    for name, version in spec['packages'].items():
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError as exc:
            raise RuntimeError('Required runtime package unavailable: ' + name) from exc
        if dist.version != version or not Path(dist.locate_file('')).resolve().is_relative_to(prefix.resolve()):
            raise RuntimeError('Runtime version/origin mismatch: ' + name)
    return {'python': sys.version.split()[0], 'isolated_site_packages': True,
            'verified_production_packages': len(spec['packages'])}
