#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VENV_PATH="$SCRIPT_DIR/.venv"
OFFLINE=0
WHEELHOUSE=''
HASH_REQUIREMENTS_DIR=''
HASH_REQUIREMENTS=''
STAGING_VENV=''

cleanup_install_temporary_files() {
    if [[ -n "$HASH_REQUIREMENTS" && -f "$HASH_REQUIREMENTS" ]]; then
        rm -f -- "$HASH_REQUIREMENTS"
    fi
    if [[ -n "$HASH_REQUIREMENTS_DIR" && -d "$HASH_REQUIREMENTS_DIR" ]]; then
        rmdir -- "$HASH_REQUIREMENTS_DIR"
    fi
    if [[ -n "$STAGING_VENV" && -d "$STAGING_VENV" ]]; then
        case "$(basename -- "$STAGING_VENV")" in
            .pia-venv-staging-*) rm -rf -- "$STAGING_VENV" ;;
            *) echo 'Refusing to remove an unexpected staging path.' >&2 ;;
        esac
    fi
}
trap cleanup_install_temporary_files EXIT

while (($#)); do
    case "$1" in
        --venv)
            [[ $# -ge 2 ]] || { echo '--venv requires a path' >&2; exit 2; }
            VENV_PATH="$2"
            shift 2
            ;;
        --offline)
            OFFLINE=1
            shift
            ;;
        --wheelhouse)
            [[ $# -ge 2 ]] || { echo '--wheelhouse requires a path' >&2; exit 2; }
            WHEELHOUSE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if [[ "$OFFLINE" -ne 1 ]]; then
    echo 'Online installation is disabled. Use --offline --wheelhouse <verified-directory>.' >&2
    exit 2
fi
[[ -n "$WHEELHOUSE" && -d "$WHEELHOUSE" ]] || {
    echo 'Offline installation requires --wheelhouse <existing-directory>.' >&2
    exit 2
}

PYTHON=''
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -I -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
            >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
if [[ -z "$PYTHON" ]]; then
    echo 'Python 3 is required and was not found on PATH.' >&2
    exit 1
fi

REQUIREMENTS="$SCRIPT_DIR/requirements.lock.txt"
[[ -f "$REQUIREMENTS" ]] || {
    echo 'requirements.lock.txt is missing.' >&2
    exit 1
}
INTEGRITY_SCRIPT="$SCRIPT_DIR/scripts/wheelhouse_integrity.py"
[[ -f "$INTEGRITY_SCRIPT" ]] || {
    echo 'scripts/wheelhouse_integrity.py is missing.' >&2
    exit 1
}
ENVIRONMENT_GATE="$SCRIPT_DIR/scripts/installed_environment_gate.py"
[[ -f "$ENVIRONMENT_GATE" ]] || {
    echo 'scripts/installed_environment_gate.py is missing.' >&2
    exit 1
}
PUBLISH_SCRIPT="$SCRIPT_DIR/scripts/publish_directory_no_replace.py"
[[ -f "$PUBLISH_SCRIPT" ]] || {
    echo 'scripts/publish_directory_no_replace.py is missing.' >&2
    exit 1
}
WHEELHOUSE_MANIFEST="$WHEELHOUSE/wheelhouse-manifest.json"
if ! "$PYTHON" -I -B "$INTEGRITY_SCRIPT" verify \
    --wheelhouse "$WHEELHOUSE" \
    --manifest "$WHEELHOUSE_MANIFEST" \
    --requirements-lock "$REQUIREMENTS"; then
    echo 'Wheelhouse integrity verification failed; the target virtual environment was not changed.' >&2
    exit 3
fi
HASH_REQUIREMENTS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pia-wheelhouse.XXXXXXXX")"
HASH_REQUIREMENTS="$HASH_REQUIREMENTS_DIR/requirements.hashed.txt"
if ! "$PYTHON" -I -B "$INTEGRITY_SCRIPT" generate-hash-requirements \
    --wheelhouse "$WHEELHOUSE" \
    --manifest "$WHEELHOUSE_MANIFEST" \
    --requirements-lock "$REQUIREMENTS" \
    --output "$HASH_REQUIREMENTS"; then
    echo 'Hashed requirements generation failed; the target virtual environment was not changed.' >&2
    exit 3
fi

if [[ -e "$VENV_PATH" || -L "$VENV_PATH" ]]; then
    echo 'The target virtual-environment path already exists; choose a new empty path.' >&2
    exit 2
fi
VENV_PARENT="$(dirname -- "$VENV_PATH")"
[[ -d "$VENV_PARENT" ]] || {
    echo 'The target virtual-environment parent directory must already exist.' >&2
    exit 2
}
STAGING_VENV="$(mktemp -d "$VENV_PARENT/.pia-venv-staging-XXXXXXXX")"

"$PYTHON" -I -m venv "$STAGING_VENV"
if [[ -x "$STAGING_VENV/bin/python" ]]; then
    VENV_PYTHON="$STAGING_VENV/bin/python"
elif [[ -x "$STAGING_VENV/Scripts/python.exe" ]]; then
    VENV_PYTHON="$STAGING_VENV/Scripts/python.exe"
else
    echo 'The virtual-environment Python executable was not created.' >&2
    exit 1
fi
PIP_ARGS=(
    -I -m pip --isolated install
    --requirement "$HASH_REQUIREMENTS"
    --require-hashes
    --only-binary=:all:
    --no-index
    --disable-pip-version-check
    --find-links "$WHEELHOUSE"
)
"$VENV_PYTHON" "${PIP_ARGS[@]}"
"$VENV_PYTHON" -I -m pip --isolated check
"$VENV_PYTHON" -I -B "$ENVIRONMENT_GATE" --requirements-lock "$REQUIREMENTS"
if ! "$PYTHON" -I -B "$INTEGRITY_SCRIPT" verify \
    --wheelhouse "$WHEELHOUSE" \
    --manifest "$WHEELHOUSE_MANIFEST" \
    --requirements-lock "$REQUIREMENTS"; then
    echo 'Wheelhouse changed during installation; do not use the target virtual environment.' >&2
    exit 3
fi
"$PYTHON" -I -B "$PUBLISH_SCRIPT" --staging "$STAGING_VENV" --target "$VENV_PATH"
STAGING_VENV=''
if [[ -x "$VENV_PATH/bin/python" ]]; then
    VENV_PYTHON="$VENV_PATH/bin/python"
else
    VENV_PYTHON="$VENV_PATH/Scripts/python.exe"
fi

echo 'Dependencies installed in the isolated virtual environment.'
echo "Local check: $VENV_PYTHON $SCRIPT_DIR/scripts/garmin_data.py summary --days 7 --source local"
echo 'Authentication and synchronization remain separate, explicitly authorized operations.'
echo 'GarminDB synchronization requires a separately reviewed runner environment.'
