#!/usr/bin/env sh
# Cross-platform entry point for the local skills-library gate.
#
# The workers are Python plus PowerShell. PowerShell Core (`pwsh`) runs on
# Windows, macOS and Linux, so this wrapper fails closed with an explicit
# message when it is absent rather than reporting a partial pass. It exists so
# the gate has one command that a third party can reproduce from a checkout.
#
# Usage:
#   scripts/gate.sh                     # whole library, read-only checks
#   scripts/gate.sh skill-a skill-b     # scoped to selected skills
#   scripts/gate.sh --refresh-manifests # rewrite manifests, then check
#
# Exit codes: 0 pass, 1 gate failure, 127 missing runtime dependency.

set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

refresh=0
if [ "${1:-}" = "--refresh-manifests" ]; then
    refresh=1
    shift
fi

if ! command -v python >/dev/null 2>&1; then
    echo "gate: python 3 with PyYAML is required." >&2
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
        python -B -X utf8 scripts/validate_openai_yaml.py --root . --json --include-skill "$skill" >/dev/null
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
    python -B -X utf8 scripts/validate_openai_yaml.py --root . --json >/dev/null
    echo "== unit tests =="
    python -B -X utf8 -m pytest scripts -q
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

if [ "$#" -gt 0 ]; then
    run_scope "$@"
else
    run_repository
fi

echo "gate: passed"
