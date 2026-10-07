#!/usr/bin/env python3
"""Emit a ready-to-run independent review brief for one run directory (P2-3).

Why this exists: review lanes previously failed for environmental reasons (in one
recorded case three lanes stopped with ``MISSING_WEB_TOOLS`` and produced no usable
evidence), and a lane started without its required artifacts would silently audit a
partial picture.  This packer declares what a lane needs, hashes what is actually
present, and refuses to hand over a brief when a required input is missing.

Boundaries: the brief is a request, not a permission and not a review result.  It
never writes outside ``--out``, never runs the review itself, and never softens a
lane's read-only constraint.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
LANES_PATH = SKILL_DIR / "references" / "review_lanes.json"
DECISION_SCOPE = "advisory"
SCHEMA_VERSION = "pia_review_brief_v1"


class LaneError(RuntimeError):
    pass


def load_lanes(path: Path | None = None) -> dict[str, Any]:
    target = path or LANES_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LaneError(f"lane specification unreadable: {target}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("lanes"), dict):
        raise LaneError("lane specification must contain a 'lanes' object")
    for name, lane in payload["lanes"].items():
        if not isinstance(lane, dict):
            raise LaneError(f"lane {name!r} must be an object")
        if not isinstance(lane.get("purpose"), str) or not lane["purpose"].strip():
            raise LaneError(f"lane {name!r}.purpose must be a non-empty string")
        for field in ("required_tools", "required_inputs", "forbidden",
                      "questions", "output_contract"):
            value = lane.get(field)
            if not isinstance(value, list) or not value:
                raise LaneError(f"lane {name!r}.{field} must be a non-empty list")
    return payload


def scan_inputs(run_dir: Path, required: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    present: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in required:
        path = run_dir / relative
        if path.is_file():
            present.append({"path": relative, "bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        else:
            missing.append(relative)
    return present, missing


def render_brief(lane_name: str, lane: dict[str, Any], run_dir: Path,
                 present: list[dict[str, Any]], missing: list[str]) -> str:
    lines: list[str] = []
    lines.append(f"# 独立复核简报：{lane_name}")
    lines.append("")
    lines.append("> 你是未参与该次生成的独立复核者。本简报是任务书，不是权限；实际可用工具以运行时为准。")
    lines.append("")
    lines.append("## 复核对象")
    lines.append("")
    lines.append(f"- 运行目录：{run_dir}")
    lines.append(f"- 生成时点（本地）：{datetime.datetime.now().isoformat(timespec='seconds')}")
    lines.append("- 一致性约束：仅判定制品所显示的内容；不得修改任何制品。")
    lines.append("")
    lines.append("## 职责")
    lines.append("")
    lines.append(lane["purpose"])
    lines.append("")
    lines.append("## 声明所需工具（缺失即报告，不要用别的方式绕行）")
    lines.append("")
    for tool in lane["required_tools"]:
        lines.append(f"- {tool}")
    lines.append("")
    lines.append("## 输入清单（SHA-256 由本打包器计算）")
    lines.append("")
    lines.append("| 制品 | 字节 | SHA-256 |")
    lines.append("|---|---|---|")
    for row in present:
        lines.append(f"| {row['path']} | {row['bytes']} | {row['sha256']} |")
    if missing:
        lines.append("")
        for relative in missing:
            lines.append(f"- 缺口：缺少 {relative}（本泳道不应在缺此项的情况下得出结论）")
    lines.append("")
    lines.append("## 禁止事项")
    lines.append("")
    for item in lane["forbidden"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 必须回答的问题")
    lines.append("")
    for index, question in enumerate(lane["questions"], 1):
        lines.append(f"{index}. {question}")
    lines.append("")
    lines.append("## 输出契约")
    lines.append("")
    for item in lane["output_contract"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 汇报要求")
    lines.append("")
    lines.append("- 先列阻断性发现，再列非阻断备注，最后列无法验证项（UNVERIFIED）与原因。")
    lines.append("- 每条结论须给出制品、字段或命令作为证据；不得只给印象式判断。")
    lines.append("- 不提供买卖建议；发现的问题交回主控处理。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit an independent review brief for a run.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out")
    parser.add_argument("--lanes-file")
    args = parser.parse_args(argv)
    try:
        lanes = load_lanes(Path(args.lanes_file).expanduser().resolve()
                           if args.lanes_file else None)
        lane = lanes["lanes"].get(args.lane)
        if lane is None:
            raise LaneError(f"unknown lane {args.lane!r}; available: "
                            + ", ".join(sorted(lanes["lanes"])))
        run_dir = Path(args.run_dir).expanduser().resolve()
        if not run_dir.is_dir():
            raise LaneError(f"run directory not found: {run_dir}")
        present, missing = scan_inputs(run_dir, lane["required_inputs"])
        brief = render_brief(args.lane, lane, run_dir, present, missing)
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "complete" if not missing else "insufficient_data",
            "detail_status": "brief_ready" if not missing else "required_inputs_missing",
            "decision_scope": DECISION_SCOPE,
            "lane": args.lane,
            "run_dir": str(run_dir),
            "required_tools": lane["required_tools"],
            "present_inputs": present,
            "missing_inputs": missing,
            "question_count": len(lane["questions"]),
            "brief_sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest(),
            "note": ("the brief is a task request, not a permission; the lane must still "
                     "declare anything it cannot verify"),
        }
        if args.out:
            target = Path(args.out).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            if not missing:
                target.write_bytes(brief.encode("utf-8"))
                report["brief_file"] = str(target)
            else:
                report["brief_file"] = None
                report["note"] += "; brief not written because required inputs are missing"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not missing else 2
    except LaneError as exc:
        print(json.dumps({"status": "failed", "detail_status": "review_pack_input_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
