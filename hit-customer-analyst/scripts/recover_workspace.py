#!/usr/bin/env python3
"""Recover an interrupted discovery-call WAL transaction under both locks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from init_workspace import validate_workspace_postflight
from runtime_tx import (
    TxError,
    load_manifest,
    manifest_state,
    output_root_lock,
    recover_transaction,
    verify_manifest_artifacts,
    workspace_lock,
)


def recover(args: argparse.Namespace) -> dict[str, object]:
    supplied_workspace = Path(args.workspace).expanduser()
    workspace = supplied_workspace.resolve()
    if Path(os.path.abspath(supplied_workspace)) != workspace or not workspace.is_dir():
        raise TxError("工作区不存在或为符号链接。")
    with output_root_lock(workspace.parent, timeout=args.lock_timeout):
        with workspace_lock(workspace, timeout=args.lock_timeout):
            result = recover_transaction(
                workspace,
                strategy=args.strategy,
                postflight=validate_workspace_postflight if args.strategy == "roll-forward" else None,
            )
            manifest = load_manifest(workspace)
            assert manifest is not None
            verify_manifest_artifacts(workspace, manifest)
            validate_workspace_postflight(workspace)
            revision, digest = manifest_state(workspace)
            return {
                "workspace": str(workspace),
                "recovery": result,
                "manifest_revision": revision,
                "manifest_sha256": digest,
            }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="安全恢复discovery-call未完成事务。")
    parser.add_argument("workspace")
    parser.add_argument("--strategy", choices=("auto", "rollback", "roll-forward"), default="auto")
    parser.add_argument("--lock-timeout", type=float, default=60.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = recover(args)
    except (TxError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"恢复结果：{result['recovery']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
