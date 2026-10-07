#!/usr/bin/env python3
"""管理人官方基金净值观测点台账（可累积的一手净值序列）。

为什么需要它：ETF/基金的**历史净值序列**在各管理人站点由前端接口加载，无法稳定直取；
但管理人详情页的服务端渲染 HTML 稳定暴露「单位净值(YYYY-MM-DD) 值」这一个观测点。
因此把每个交易日的观测点**按日累积**成台账，条件核验即可引用「最近 N 个观测点」，
而不是依赖无法取得的整段序列。

- 只读联网（需显式 `--allow-network`）；`--from-file` 可离线解析已保存页面。
- 幂等：同一 (code, nav_date) 只保留一条；重复运行不产生重复记录。
- 失败关闭：404 外壳、无法渲染、解析不到净值都返回稳定原因码，不写台账。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "pia_fund_nav_point_v1"
MANAGERS = {
    "fullgoal": "https://www.fullgoal.com.cn/fundDetail/{code}/index.html",
}
NOT_FOUND_MARKERS = ("error_box_404", "您访问的页面不见了")
NAV_PATTERN = re.compile(
    r"单位净值\s*[（(]\s*(\d{4}-\d{2}-\d{2})\s*[)）]\s*(?:</p>)?\s*(?:<[^>]+>\s*)*([0-9]+(?:\.[0-9]+)?)"
)
CUMULATIVE_PATTERN = re.compile(
    r"累计净值\s*(?:</p>)?\s*(?:<[^>]+>\s*)*([0-9]+(?:\.[0-9]+)?)"
)


class NavLedgerError(RuntimeError):
    """带稳定原因码的失败关闭异常。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_nav_points(html: str) -> dict:
    """从服务端渲染 HTML 中提取观测点；失败抛 NavLedgerError。"""
    if any(marker in html for marker in NOT_FOUND_MARKERS):
        raise NavLedgerError("page_not_found")
    match = NAV_PATTERN.search(html)
    if not match:
        raise NavLedgerError("nav_not_rendered")
    cumulative = CUMULATIVE_PATTERN.search(html)
    return {
        "nav_date": match.group(1),
        "unit_nav": float(match.group(2)),
        "cumulative_nav": float(cumulative.group(1)) if cumulative else None,
    }


def fetch_page(url: str, *, timeout: int = 40) -> str:
    completed = subprocess.run(
        ["curl", "-sS", "-L", "--compressed", "--max-time", str(timeout),
         "-A", "Mozilla/5.0", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout + 20,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise NavLedgerError("page_read_error")
    return completed.stdout


def build_point(code: str, manager: str, html: str, *, source_locator: str,
                retrieved_at: str | None = None) -> dict:
    parsed = parse_nav_points(html)
    return {
        "schema_version": SCHEMA_VERSION,
        "code": code,
        "manager": manager,
        "nav_date": parsed["nav_date"],
        "unit_nav": parsed["unit_nav"],
        "cumulative_nav": parsed["cumulative_nav"],
        "source_locator": source_locator,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "content_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
    }


def read_ledger(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def append_point(path: Path, point: dict) -> bool:
    """幂等追加；返回是否新增。"""
    records = read_ledger(path)
    if any(r.get("code") == point["code"] and r.get("nav_date") == point["nav_date"] for r in records):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(point, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    return True


def series(path: Path, code: str) -> list[dict]:
    rows = [r for r in read_ledger(path) if r.get("code") == code]
    return sorted(rows, key=lambda r: r["nav_date"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=True)
    parser.add_argument("--manager", default="fullgoal", choices=sorted(MANAGERS))
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--from-file", type=Path, help="离线解析已保存的详情页 HTML")
    parser.add_argument("--show-series", action="store_true")
    args = parser.parse_args(argv)

    if args.show_series and not args.from_file:
        rows = series(args.ledger, args.code)
        print(json.dumps({"code": args.code, "point_count": len(rows), "points": rows}, ensure_ascii=False, indent=2))
        return 0 if rows else 2

    if args.from_file:
        html = args.from_file.read_text(encoding="utf-8", errors="replace")
        locator = f"file://{args.from_file.name}"
    elif args.allow_network:
        locator = MANAGERS[args.manager].format(code=args.code)
        try:
            html = fetch_page(locator)
        except NavLedgerError as exc:
            print(json.dumps({"status": "error", "reason": exc.code, "source_locator": locator}, ensure_ascii=False))
            return 3
    else:
        print(json.dumps({"status": "error", "reason": "network_authorization_required"}, ensure_ascii=False))
        return 3

    try:
        point = build_point(args.code, args.manager, html, source_locator=locator)
    except NavLedgerError as exc:
        print(json.dumps({"status": "error", "reason": exc.code, "source_locator": locator}, ensure_ascii=False))
        return 3

    added = append_point(args.ledger, point)
    rows = series(args.ledger, args.code)
    print(json.dumps({
        "status": "complete",
        "added": added,
        "point": point,
        "ledger_points": len(rows),
        "latest": rows[-1] if rows else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
