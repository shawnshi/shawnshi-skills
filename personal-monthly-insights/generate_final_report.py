import argparse
import sys
from analyze_insights_v4 import main as v9_main
from core.engine import get_agent_audit_path


def main():
    parser = argparse.ArgumentParser(description='Compatibility shim for the V9 report renderer')
    parser.add_argument('--period', default='30d', choices=['1d', '7d', '30d', '90d', 'year'])
    parser.add_argument('--extract-only', action='store_true')
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--agent-file', default='')
    args = parser.parse_args()

    if not args.extract_only and not args.render:
        args.render = True

    forwarded = [sys.argv[0], '--period', args.period]
    if args.extract_only:
        forwarded.append('--extract-only')
    if args.render:
        forwarded.extend(['--render', '--agent-file', args.agent_file or str(get_agent_audit_path())])

    print('⚠️ generate_final_report.py is deprecated. Forwarding to analyze_insights_v4.py (V9).')
    old_argv = sys.argv[:]
    try:
        sys.argv = forwarded
        v9_main()
    finally:
        sys.argv = old_argv


if __name__ == '__main__':
    main()
