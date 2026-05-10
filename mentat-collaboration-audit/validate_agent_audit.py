import json
import sys
from pathlib import Path

VERSION = '9.0'
METRIC_KEYWORDS = ['会话', '时长', 'token', '提交', '活跃', '失败', 'telemetry', '指标', '摩擦', '效率']
REQUIRED_TOP_LEVEL = [
    'version', 'behavioral_analysis', 'friction_analysis', 'workflow_engineering',
    'suggestions', 'at_a_glance', 'distributions'
]


class ValidationError(Exception):
    pass


def _is_overly_numeric(text):
    if not text:
        return True
    stripped = ''.join(ch for ch in text if not ch.isspace())
    if not stripped:
        return True
    digit_count = sum(ch.isdigit() for ch in stripped)
    return digit_count / max(len(stripped), 1) > 0.35


def validate_agent_payload(payload):
    errors = []

    for key in REQUIRED_TOP_LEVEL:
        if key not in payload:
            errors.append(f'missing top-level field: {key}')

    if payload.get('version') != VERSION:
        errors.append(f"version must be '{VERSION}'")

    behavioral = payload.get('behavioral_analysis', {})
    points = behavioral.get('points', []) if isinstance(behavioral, dict) else []
    if len(points) != 8:
        errors.append('behavioral_analysis.points must contain exactly 8 items')

    coach_summary = behavioral.get('coach_summary', '') if isinstance(behavioral, dict) else ''
    if len(coach_summary.strip()) < 60:
        errors.append('coach_summary is too short to qualify as strategic coaching')
    elif _is_overly_numeric(coach_summary):
        errors.append('coach_summary appears too numeric; expected qualitative coaching')

    friction = payload.get('friction_analysis', {})
    categories = friction.get('categories', []) if isinstance(friction, dict) else []
    if not categories:
        errors.append('friction_analysis.categories must contain at least one anti-pattern category')

    workflow_engineering = payload.get('workflow_engineering', {})
    prompt_assets = workflow_engineering.get('prompt_assets', []) if isinstance(workflow_engineering, dict) else []
    automation_candidates = workflow_engineering.get('automation_candidates', []) if isinstance(workflow_engineering, dict) else []
    if not prompt_assets or not any(asset.get('copy_paste_template', '').strip() for asset in prompt_assets if isinstance(asset, dict)):
        errors.append('workflow_engineering.prompt_assets must contain at least one copyable asset')
    if not automation_candidates:
        errors.append('workflow_engineering.automation_candidates must contain at least one automation proposal')

    merged_text = ' '.join([
        behavioral.get('overall', '') if isinstance(behavioral, dict) else '',
        coach_summary,
        ' '.join(point.get('description', '') for point in points if isinstance(point, dict)),
    ]).lower()
    if not any(keyword.lower() in merged_text for keyword in METRIC_KEYWORDS):
        errors.append('analysis does not appear to align subjective friction with objective metrics or telemetry')

    suggestions = payload.get('suggestions', {})
    usage_patterns = suggestions.get('usage_patterns', []) if isinstance(suggestions, dict) else []
    glance = payload.get('at_a_glance', {})
    quick_wins = glance.get('quick_wins', '') if isinstance(glance, dict) else ''
    if not quick_wins.strip() and not any(item.get('detail', '').strip() for item in usage_patterns if isinstance(item, dict)):
        errors.append('next-cycle action missing from at_a_glance.quick_wins or suggestions.usage_patterns')

    return errors


def validate_file(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    errors = validate_agent_payload(payload)
    if errors:
        raise ValidationError('\n'.join(errors))
    return payload


def main():
    if len(sys.argv) != 2:
        print('Usage: python validate_agent_audit.py <agent_audit_result.json>')
        sys.exit(1)

    target = sys.argv[1]
    try:
        validate_file(target)
    except FileNotFoundError:
        print(f'VALIDATION_FAIL: file not found: {target}')
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f'VALIDATION_FAIL: invalid json: {exc}')
        sys.exit(1)
    except ValidationError as exc:
        print('VALIDATION_FAIL:')
        for line in str(exc).splitlines():
            print(f' - {line}')
        sys.exit(1)

    print('VALIDATION_PASS')


if __name__ == '__main__':
    main()
