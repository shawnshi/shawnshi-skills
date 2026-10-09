#!/usr/bin/env sh
# Cross-platform entry point for the local skills-library gate.
#
# The workers are Python plus PowerShell. PowerShell Core (`pwsh`) runs on
# Windows, macOS and Linux, so this wrapper fails closed with an explicit
# message when it is absent rather than reporting a partial pass. It exists so
# the gate has one command that a third party can reproduce from a checkout.
#
# Usage:
#   scripts/gate.sh                     # whole library, no tests or writes
#   scripts/gate.sh skill-a skill-b     # scoped deterministic checks
#   scripts/gate.sh --tests             # explicit library tests (temporary writes)
#   scripts/gate.sh --refresh-manifests skill-a # authorized scoped refresh
# Flags precede skill names. Tests always cover the library test suite.
#
# Exit codes: 0 deterministic checks pass, 1 failure, 2 usage, 127 missing dependency.

set -eu
export PYTHONDONTWRITEBYTECODE=1

refresh=0
tests=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --refresh-manifests) refresh=1; shift ;;
        --tests) tests=1; shift ;;
        --help) echo 'Usage: gate.sh [--tests] [--refresh-manifests] [skill-name ...]'; exit 0 ;;
        --*) echo "gate: unknown option: $1" >&2; exit 2 ;;
        *) break ;;
    esac
done

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

if ! command -v python >/dev/null 2>&1; then
    echo "gate: python 3 with PyYAML is required." >&2
    exit 127
fi

if ! python -B -X utf8 -c 'import sys; assert sys.version_info >= (3, 10); import yaml'; then
    echo "gate: Python 3.10+ with PyYAML is required; no dependency was installed." >&2
    exit 127
fi
if [ "$tests" -eq 1 ] && ! python -B -X utf8 -c 'import pytest'; then
    echo "gate: --tests requires pytest; deterministic checks do not." >&2
    exit 127
fi

if ! command -v pwsh >/dev/null 2>&1; then
    echo "gate: pwsh (PowerShell 7+) is required; Windows PowerShell is not cross-platform." >&2
    echo "gate: install PowerShell Core, or run the individual commands listed in mentat-skill-creator/SKILL.md." >&2
    exit 127
fi

# -ExecutionPolicy only exists on Windows hosts; passing it elsewhere fails.
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW* | MSYS* | CYGWIN*) pwsh_flags="-NoProfile -ExecutionPolicy Bypass" ;;
    *) pwsh_flags="-NoProfile" ;;
esac

run_scope() {
    for skill in "$@"; do
        echo "== $skill =="
        python -B -X utf8 scripts/validate_openai_yaml.py --root . --json --include-skill "$skill"
        if [ "$refresh" -eq 1 ]; then
            # shellcheck disable=SC2086
            pwsh $pwsh_flags -File scripts/generate_resource_manifests.ps1 -Root . -IncludeSkills "$skill"
        fi
        # shellcheck disable=SC2086
        pwsh $pwsh_flags -File scripts/generate_resource_manifests.ps1 -Root . -Check -IncludeSkills "$skill"
        # shellcheck disable=SC2086
        pwsh $pwsh_flags -File scripts/repair_skills.ps1 -Mode Gate -Root . -IncludeSkills "$skill"
    done
}

run_repository() {
    echo "== openai.yaml metadata =="
    python -B -X utf8 scripts/validate_openai_yaml.py --root . --json
    if [ "$refresh" -eq 1 ]; then
        # shellcheck disable=SC2086
        pwsh $pwsh_flags -File scripts/generate_resource_manifests.ps1 -Root .
    fi
    echo "== resource manifests =="
    # shellcheck disable=SC2086
    pwsh $pwsh_flags -File scripts/generate_resource_manifests.ps1 -Root . -Check
    echo "== repository gate =="
    # shellcheck disable=SC2086
    pwsh $pwsh_flags -File scripts/repair_skills.ps1 -Mode Gate -Root .
}

if [ "$tests" -eq 1 ]; then
    echo "== authorized library tests (temporary writes) =="
    python -B -X utf8 -m pytest scripts -q -p no:cacheprovider
fi

if [ "$#" -gt 0 ]; then
    run_scope "$@"
else
    run_repository
fi

echo "gate: deterministic checks passed; semantic review and host behaviour are separate."
