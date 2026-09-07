#!/usr/bin/env python3
"""Check a UTF-8 briefing draft's shape, never approve, export, or modify it."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# Keep default CLI invocations read-only too, without requiring caller -B/env flags.
sys.dont_write_bytecode = True
import validate_outputs as validator  # noqa: E402

MAX_INPUT_BYTES = 1024 * 1024


def check(text: str) -> dict[str, object]:
    document = validator.Document(Path("<draft>"), text, {}, text)
    body = validator.briefing_body(document)
    lines = validator.briefing_lines(body)
    claim_ids = sorted(set(validator.CLAIM_RE.findall(body)))
    if not claim_ids:
        raise ValueError("速览须引用已有 CLM-I/L/N-编号；不能以 C01/S01 简写替代。")
    return {
        "scope": "draft_shape_only",
        "characters": len(body),
        "wrapped_lines": len(lines),
        "claim_ids": claim_ids,
        "sources_verified": False,
        "ready_for_use": False,
        "note": "仅检查标记、容量及主张编号存在；未核验台账、事实、权限、审批或物理页数。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", nargs="?", default="-", help="UTF-8候选文件；-表示stdin"
    )
    args = parser.parse_args()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        if args.input == "-":
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            path = Path(args.input)
            if path.is_symlink():
                raise ValueError("不读取符号链接候选文件。")
            with path.open("rb") as stream:
                raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("候选输入超过1MiB；请仅提交本轮候选正文。")
        result = check(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
