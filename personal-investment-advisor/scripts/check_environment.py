"""Read-only environment receipt. Installed metadata is not a cross-platform lock."""
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path


def environment_receipt():
    requirements = Path(__file__).with_name('requirements.txt')
    raw = requirements.read_bytes()
    packages = []
    for requirement in raw.decode('utf-8').splitlines():
        if not requirement.strip() or requirement.startswith('#'):
            continue
        name = requirement.split('>=', 1)[0]
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = 'not_installed'
        packages.append({'requirement': requirement, 'installed_version': version})
    return {'python': sys.version, 'implementation': platform.python_implementation(),
            'os': platform.platform(), 'machine': platform.machine(),
            'requirements_sha256': hashlib.sha256(raw).hexdigest(), 'packages': packages,
            'compatibility_scope': 'metadata only; executable compatibility is established by the recorded offline unittest run',
            'lock_status': 'not_a_lock; no cross-platform resolution or installation performed'}


if __name__ == '__main__':
    print(json.dumps(environment_receipt(), ensure_ascii=False, indent=2))
