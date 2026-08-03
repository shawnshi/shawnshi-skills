import argparse
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from advice_journal import append_entry
from dashboard_catalog import (
    GENERATIONS_DIRNAME,
    DashboardCatalogError,
    canonical_symbol,
    register_dashboard,
    safe_archive_component,
)
from dashboard_gate import validate_dashboard


class DashboardArchiveError(ValueError):
    pass


def safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def render_markdown(data, raw_json):
    stock_name = data.get("stock_name", "Unknown")
    stock_code = data.get("stock_code", "Unknown")
    market_type = data.get("market_type", "")
    confidence = data.get("confidence_level", "")
    tags = data.get("tags", [])

    db = data.get("dashboard", {})
    cc = db.get("core_conclusion", {})
    qa = db.get("qualitative_analysis", {})
    dp = db.get("data_perspective", {})
    intel = db.get("intelligence", {})
    research_plan = db.get("research_plan", {})
    portfolio = data.get("portfolio_context", {})
    portfolio_summary = data.get("portfolio_summary", {})
    portfolio_risk = data.get("portfolio_risk", {})
    portfolio_fit = data.get("portfolio_fit", {})
    holding_assessment = data.get("holding_assessment", {})
    confidence_details = data.get("confidence_details", {})
    freshness_flags = data.get("freshness_flags", {})
    earnings_snapshot = data.get("earnings_snapshot", {})
    catalyst_map = data.get("catalyst_map", {})
    evidence_items = data.get("evidence_items", [])
    monitoring_alerts = data.get("monitoring_alerts", [])

    md = "---\n"
    md += f"title: {stock_name} ({stock_code}) 深度研究报告\n"
    md += f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
    md += "status: archived\n"
    md += "author: personal-investment-advisor\n"
    if tags:
        md += f"tags: [{', '.join(tags)}]\n"
    md += "---\n\n"

    md += f"# 研究仪表盘: {stock_name} ({stock_code} - {market_type})\n\n"
    md += (
        "> 本报告仅用于研究，不包含证券交易方向、仓位、进出场或价格指令。"
        f"置信度：**{confidence}**\n\n"
    )

    md += "## 🟢 核心判词 (Executive Summary)\n"
    md += f"**{cc.get('one_sentence', '无')}**\n\n"
    md += f"- **信号状态**: {cc.get('signal_type', '无')}\n"
    md += f"- **时间窗口**: {cc.get('time_sensitivity', '无')}\n"
    md += f"- **研究模式**: {data.get('research_mode', '无')}\n"
    md += f"- **研究边界**: {cc.get('research_boundary', '无')}\n\n"

    md += "## 🧮 置信度与新鲜度\n"
    md += f"- **综合置信分**: {confidence_details.get('score', '--')}/100\n"
    md += f"- **数据质量**: {confidence_details.get('data_quality', '--')}\n"
    md += f"- **技术一致性**: {confidence_details.get('technical_alignment', '--')}\n"
    md += f"- **估值支撑**: {confidence_details.get('valuation_support', '--')}\n"
    md += f"- **研究可用性**: {confidence_details.get('actionability', '--')}\n"
    md += f"- **价格数据新鲜**: {freshness_flags.get('price_data_fresh', '--')}\n"
    md += f"- **基本面数据新鲜**: {freshness_flags.get('info_data_fresh', '--')}\n"
    md += f"- **新闻数据新鲜**: {freshness_flags.get('news_data_fresh', '--')}\n"
    md += f"- **持仓数据新鲜**: {freshness_flags.get('portfolio_data_fresh', '--')}\n"
    stale_inputs = freshness_flags.get("stale_inputs", [])
    if stale_inputs:
        md += "- **过期输入**:\n"
        for item in stale_inputs:
            md += f"  - {item}\n"
    md += "\n"

    if portfolio.get("has_position"):
        pnl_pct = portfolio.get("unrealized_pnl_pct")
        pnl_pct_display = f"{pnl_pct * 100:.2f}%" if isinstance(pnl_pct, (int, float)) else "--"
        md += "## 🧾 持仓研究上下文\n"
        md += f"- **持仓数量**: {portfolio.get('quantity', '--')}\n"
        md += f"- **持仓成本**: {portfolio.get('avg_cost', '--')}\n"
        md += f"- **当前价格**: {portfolio.get('current_price', '--')}\n"
        md += f"- **持仓市值**: {portfolio.get('market_value', '--')}\n"
        md += f"- **浮盈/浮亏**: {portfolio.get('unrealized_pnl', '--')} ({pnl_pct_display})\n"
        md += f"- **仓位状态**: {portfolio.get('weight_status', '--')}\n"
        md += f"- **持仓背景**: {holding_assessment.get('holding_context', '无')}\n"
        md += f"- **成本背景**: {holding_assessment.get('cost_basis_context', '无')}\n"
        md += f"- **风险证据**: {holding_assessment.get('risk_evidence', '无')}\n"
        conditions = holding_assessment.get("monitoring_conditions", [])
        if conditions:
            md += "- **后续观察条件**:\n"
            for item in conditions:
                md += f"  - {item}\n"
        md += "\n"

    if portfolio_summary or portfolio_risk or portfolio_fit:
        md += "## 🧩 组合适配度 (Portfolio Fit)\n"
        if portfolio_summary:
            md += f"- **持仓总数**: {portfolio_summary.get('total_positions', '--')}\n"
            md += f"- **已跟踪权重**: {portfolio_summary.get('tracked_weight', '--')}\n"
            md += f"- **集中度分数**: {portfolio_summary.get('concentration_score', '--')} ({portfolio_summary.get('concentration_bucket', '--')})\n"
            md += f"- **市场暴露**: {portfolio_summary.get('market_exposure', {})}\n"
        if portfolio_risk:
            md += f"- **集中度风险**: {portfolio_risk.get('concentration_risk', '--')}\n"
            md += f"- **市场暴露风险**: {portfolio_risk.get('market_exposure_risk', '--')}\n"
            md += f"- **风格漂移风险**: {portfolio_risk.get('style_drift_risk', '--')}\n"
            md += f"- **流动性风险**: {portfolio_risk.get('liquidity_risk', '--')}\n"
            for gap in portfolio_risk.get("risk_data_gaps", []):
                md += f"  - 数据缺口: {gap}\n"
        if portfolio_fit:
            md += f"- **约束状态**: {portfolio_fit.get('constraint_status', '--')}\n"
            md += f"- **约束观察**: {portfolio_fit.get('constraint_observation', '--')}\n"
            md += f"- **说明**: {portfolio_fit.get('rationale', '--')}\n"
        md += "\n"

    ts = dp.get("trend_status", {})
    pp = dp.get("price_position", {})
    va = dp.get("volume_analysis", {})
    cs = dp.get("chip_structure", {})
    md += "## 📊 关键财务与技术锚点 (Data Perspective)\n\n"
    md += "| 指标维度 | 数值 | 状态与描述 |\n|:---|:---|:---|\n"
    md += f"| **当前价格** | {pp.get('current_price', '--')} | 价格位置: {pp.get('bias_status', '--')} |\n"
    md += f"| **均线排列** | {ts.get('ma_alignment', '--')} | 乖离率状态: {pp.get('bias_status', '--')} |\n"
    md += f"| **RSI (14)** | {ts.get('rsi_14', '--')} | {ts.get('rsi_status', '--')} |\n"
    md += f"| **MACD** | {ts.get('macd_signal', '--')} | 趋势得分: {ts.get('trend_score', '--')}/100 |\n"
    md += f"| **量能分析** | {va.get('volume_status', '--')} | 换手率: {va.get('turnover_rate', '--')} (量比: {va.get('volume_ratio', '--')}) |\n"
    md += f"| **筹码结构** | {cs.get('chip_health', '--')} | 获利比例: {cs.get('profit_ratio', '--')} |\n\n"

    md += "## 🔍 深度逻辑穿透 (Qualitative Analysis)\n\n"
    md += f"**趋势推演**: {qa.get('trend_analysis', '')}\n\n"
    md += f"**基本面/逻辑**: {qa.get('fundamental_analysis', '')}\n\n"
    md += f"**形态与技术**: {qa.get('pattern_analysis', '')}\n\n"
    md += f"**行业地位**: {qa.get('sector_position', '')}\n\n"
    md += f"**核心题材**: {qa.get('hot_topics', '')}\n\n"

    if earnings_snapshot or catalyst_map:
        md += "## 📅 Thesis & Catalyst Map\n\n"
        if earnings_snapshot:
            md += f"- **下次财报**: {earnings_snapshot.get('next_earnings_date', '--')}\n"
            md += f"- **营收增长**: {earnings_snapshot.get('revenue_growth', '--')}\n"
            md += f"- **Trailing PE**: {earnings_snapshot.get('trailing_pe', '--')}\n"
            md += f"- **Forward PE**: {earnings_snapshot.get('forward_pe', '--')}\n"
            if earnings_snapshot.get("peg_ratio"):
                md += f"- **PEG Ratio**: {earnings_snapshot.get('peg_ratio')}\n"
            if earnings_snapshot.get("price_to_book"):
                md += f"- **Price/Book**: {earnings_snapshot.get('price_to_book')}\n"
            if earnings_snapshot.get("dividend_yield"):
                md += f"- **Div Yield**: {earnings_snapshot.get('dividend_yield')}\n"
            if earnings_snapshot.get("beta"):
                md += f"- **Beta**: {earnings_snapshot.get('beta')}\n"
            if earnings_snapshot.get("sector"):
                md += f"- **Sector/Industry**: {earnings_snapshot.get('sector')} / {earnings_snapshot.get('industry', '--')}\n"
        if catalyst_map:
            if catalyst_map.get("upcoming"):
                md += "- **即将到来的催化**:\n"
                for item in catalyst_map["upcoming"]:
                    md += f"  - {item}\n"
            if catalyst_map.get("active"):
                md += "- **活跃催化**:\n"
                for item in catalyst_map["active"]:
                    md += f"  - {item}\n"
            if catalyst_map.get("broken"):
                md += "- **thesis 破坏信号**:\n"
                for item in catalyst_map["broken"]:
                    md += f"  - {item}\n"
            if catalyst_map.get("data_gaps"):
                md += "- **数据缺口**:\n"
                for item in catalyst_map["data_gaps"]:
                    md += f"  - {item}\n"
        md += "\n"

    md += "## 🔬 后续研究计划\n\n"
    md += "**证据核验**\n"
    for item in research_plan.get("evidence_checks", []):
        md += f"- {item}\n"
    md += "\n**证伪检查**\n"
    for item in research_plan.get("falsification_checks", []):
        md += f"- {item}\n"
    md += "\n**观察指标**\n"
    for item in research_plan.get("monitoring_indicators", []):
        md += f"- {item}\n"

    md += "\n## 🔴 情报与风险 (Intelligence)\n\n"
    md += f"**市场情绪**: {intel.get('sentiment_summary', '')}\n\n"
    
    thesis_tracking = intel.get("thesis_tracking", {})
    if thesis_tracking:
        md += "**图谱协同追踪 (Thesis Tracking)**:\n"
        md += f"- 历史预判: {thesis_tracking.get('previous_thesis', '无记录')}\n"
        md += f"- 当前状态: {thesis_tracking.get('status', 'N/A')}\n"
        md += f"- 逻辑推演: {thesis_tracking.get('reasoning', '')}\n\n"
        
    if intel.get("positive_catalysts"):
        md += "**催化剂**:\n"
        for item in intel["positive_catalysts"]:
            md += f"- {item}\n"
    if intel.get("risk_alerts"):
        md += "**风险警示**:\n"
        for item in intel["risk_alerts"]:
            md += f"  - ⚠️ {item}\n"

    if "management_claim_tracking" in data:
        tracking = data["management_claim_tracking"]
        md += "\n## 管理层承诺兑现核对\n\n"
        summary = tracking.get("summary", {})
        md += f"- 已兑现: {summary.get('met', 0)}\n"
        md += f"- 未兑现: {summary.get('missed', 0)}\n"
        md += f"- 证据不足: {summary.get('insufficient_evidence', 0)}\n"
        md += f"- 评估边界: {tracking.get('assessment_boundary', '')}\n"
        for claim in tracking.get("claims", []):
            md += f"  - {claim.get('claim_id', '')}: {claim.get('status', '')} — {claim.get('statement', '')}\n"

    blind_spot = data.get("blind_spot_warning", "")
    if blind_spot:
        md += f"\n**🎯 对抗性红队审计 (Adversarial Stress Test)**:\n> ⚠️ {blind_spot}\n"

    if evidence_items:
        md += "\n## Evidence Mesh\n\n"
        for idx, item in enumerate(evidence_items, start=1):
            md += f"**证据 {idx}**\n"
            md += f"- Fact: {item.get('fact', '')}\n"
            md += f"- Connection: {item.get('connection', '')}\n"
            md += f"- Deduction: {item.get('deduction', '')}\n"
            md += f"- Source Type: {item.get('source_type', '')}\n"
            md += f"- Source Tier: {item.get('source_tier', '')}\n"
            md += f"- Source Locator: {item.get('source_locator', '')}\n"
            md += f"- Published/Retrieved/As Of: {item.get('published_at', '')} / {item.get('retrieved_at', '')} / {item.get('as_of_date', '')}\n"
            md += f"- Freshness: {item.get('freshness', '')}\n"
            md += f"- Confidence: {item.get('confidence', '')}\n"

    md += "\n## ⚖️ 研究反证检查\n\n"
    md += "- **证伪条件**: 哪一项新证据会推翻当前核心假设？\n"
    md += "- **定价检验**: 当前市场共识是否已反映主要正反因素？\n"
    md += "- **数据缺口**: 哪个缺失变量最可能改变研究结论？\n"

    if monitoring_alerts:
        md += "\n## Monitoring Alerts\n"
        for item in monitoring_alerts:
            md += f"- {item}\n"

    if data.get("data_gaps"):
        md += "\n## ⚠️ 数据缺口\n"
        for gap in data["data_gaps"]:
            md += f"- {gap}\n"

    md += "\n## 🧠 Mentat 综合分析摘要\n\n"
    md += f"> {data.get('analysis_summary', '')}\n\n"
    md += "\n---\n<details><summary>点击查看原始 JSON 资产</summary>\n\n"
    md += f"```json\n{raw_json}\n```\n</details>\n"
    return md


def _safe_path_component(value: object) -> str:
    try:
        return safe_archive_component(value, "stock_code")
    except DashboardCatalogError as exc:
        raise DashboardArchiveError(str(exc)) from exc


def _is_linklike(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction and is_junction():
        return True
    if os.name == "nt":
        try:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            return False
        return bool(attributes & 0x400)
    return False


def _ensure_managed_directory(root: Path, path: Path, label: str) -> Path:
    if path.exists():
        if _is_linklike(path):
            raise DashboardArchiveError(
                f"{label} must not be a symbolic link or junction"
            )
        if not path.is_dir():
            raise DashboardArchiveError(f"{label} must be a directory")
    else:
        try:
            path.mkdir()
        except FileExistsError:
            pass

    if _is_linklike(path):
        raise DashboardArchiveError(
            f"{label} must not be a symbolic link or junction"
        )
    if not path.is_dir():
        raise DashboardArchiveError(f"{label} must be a directory")
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DashboardArchiveError(
            f"{label} escapes the archive root"
        ) from exc
    return resolved


def _write_text_fsync(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def archive_dashboard(
    dashboard: dict,
    output_dir: str | Path,
    stock_alias: str,
    now: datetime | None = None,
    generation_id: str | None = None,
) -> dict:
    errors = validate_dashboard(dashboard, require_scenarios=True)
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise DashboardArchiveError(
            f"dashboard gate blocked archive:\n{details}"
        )

    stock_code = canonical_symbol(dashboard.get("stock_code"))
    try:
        requested_alias = canonical_symbol(stock_alias)
    except DashboardCatalogError as exc:
        raise DashboardArchiveError(
            "--stock must be a non-empty stock code"
        ) from exc
    if requested_alias != stock_code:
        raise DashboardArchiveError(
            "--stock must match dashboard.stock_code"
        )

    archived_at = now or datetime.now(timezone.utc)
    if archived_at.tzinfo is None:
        archived_at = archived_at.replace(tzinfo=timezone.utc)
    archived_at = archived_at.astimezone(timezone.utc)

    safe_stock_code = _safe_path_component(stock_code)
    timestamp = archived_at.strftime("%Y%m%dT%H%M%S%fZ")
    requested_generation_id = (
        generation_id
        if generation_id is not None
        else f"{timestamp}-{uuid.uuid4().hex}"
    )
    try:
        safe_generation_id = safe_archive_component(
            requested_generation_id,
            "generation_id",
        )
    except DashboardCatalogError as exc:
        raise DashboardArchiveError(str(exc)) from exc

    try:
        formatted_json = json.dumps(
            dashboard,
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        markdown = render_markdown(dashboard, formatted_json.rstrip())
    except (TypeError, ValueError) as exc:
        raise DashboardArchiveError(
            f"dashboard serialization failed before archive: {exc}"
        ) from exc

    pending_dir = None
    generation_dir = None
    generation_published = False
    try:
        root_dir = Path(output_dir).expanduser().resolve()
        root_dir.mkdir(parents=True, exist_ok=True)
        symbol_dir = _ensure_managed_directory(
            root_dir,
            root_dir / safe_stock_code,
            "symbol archive directory",
        )
        generations_dir = _ensure_managed_directory(
            root_dir,
            symbol_dir / GENERATIONS_DIRNAME,
            "generation archive directory",
        )
        generation_dir = generations_dir / safe_generation_id
        if generation_dir.exists() or _is_linklike(generation_dir):
            raise DashboardArchiveError(
                "immutable dashboard generation already exists: "
                f"{safe_generation_id}"
            )
        pending_dir = generations_dir / f".pending-{uuid.uuid4().hex}"
        pending_dir.mkdir()
        json_path = generation_dir / "dashboard.json"
        markdown_path = generation_dir / "dashboard.md"

        _write_text_fsync(pending_dir / "dashboard.json", formatted_json)
        _write_text_fsync(pending_dir / "dashboard.md", markdown)
        _fsync_directory(pending_dir)
        os.rename(pending_dir, generation_dir)
        generation_published = True
        _fsync_directory(generations_dir)
        registration = register_dashboard(
            root_dir,
            dashboard,
            json_path,
            markdown_path,
            archived_at,
            safe_generation_id,
        )
    except Exception as exc:
        if (
            not generation_published
            and pending_dir is not None
            and pending_dir.exists()
        ):
            shutil.rmtree(pending_dir)
        state = (
            f"; complete generation retained but not indexed: {generation_dir}"
            if generation_published
            else ""
        )
        raise DashboardArchiveError(
            f"dashboard archive transaction failed: {exc}{state}"
        ) from exc

    return {
        "stock_code": stock_code,
        "archived_at": archived_at.isoformat(),
        "generation_id": safe_generation_id,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "index_path": str(registration["index_path"]),
        "index_updated": registration["index_updated"],
        "is_latest": (
            registration["active_entry"].get("generation_id")
            == safe_generation_id
        ),
        "latest_json_path": str(
            root_dir / registration["active_entry"]["json_path"]
        ),
    }


def save_dashboard():
    parser = argparse.ArgumentParser(description="Save a research-only stock dashboard.")
    parser.add_argument(
        "--stock",
        required=True,
        help="Expected stock code in the dashboard payload.",
    )
    parser.add_argument("--content", help="JSON content string. If not provided, reads from stdin.")
    parser.add_argument("--file", help="Path to a JSON file containing the dashboard data.")
    parser.add_argument("--output-dir", help="Required archive directory; alternatively set PIA_DASHBOARD_DIR.")
    parser.add_argument(
        "--append-journal",
        action="store_true",
        help="Append a research snapshot after saving.",
    )
    parser.add_argument(
        "--journal-path",
        help="Research journal path; alternatively set PIA_ADVICE_JOURNAL.",
    )
    parser.add_argument("--delete-input", action="store_true", help="Delete --file only after a successful save.")
    args = parser.parse_args()

    configured_output = args.output_dir or os.environ.get("PIA_DASHBOARD_DIR")
    if not configured_output:
        parser.error("output directory is required; pass --output-dir or set PIA_DASHBOARD_DIR")
    if args.delete_input and args.file:
        lexical_input = Path(args.file).expanduser().absolute()
        lexical_archive_root = Path(configured_output).expanduser().absolute()
        resolved_input = lexical_input.resolve()
        resolved_archive_root = lexical_archive_root.resolve()
        if (
            lexical_input.is_relative_to(lexical_archive_root)
            or resolved_input.is_relative_to(resolved_archive_root)
        ):
            print(
                "Error: --delete-input refuses files inside the Dashboard "
                "archive root.",
                file=sys.stderr,
            )
            sys.exit(1)

    content = args.content
    input_identity = None
    if args.file:
        input_source = Path(args.file)
        source_stat = input_source.lstat()
        input_identity = (
            source_stat.st_dev,
            source_stat.st_ino,
            source_stat.st_size,
            source_stat.st_mtime_ns,
        )
        content = input_source.read_text(encoding="utf-8")
    elif not content:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        content = sys.stdin.read()

    if not content:
        print("Error: No content provided.", file=sys.stderr)
        sys.exit(1)

    # Extract JSON block if surrounded by markdown or conversational text
    json_str = content
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        json_str = match.group(0)
        
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON content: {e}. Ensure the agent output is pure JSON.", file=sys.stderr)
        sys.exit(1)

    try:
        archive = archive_dashboard(
            parsed,
            output_dir=configured_output,
            stock_alias=args.stock,
        )
    except DashboardArchiveError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if not archive["index_updated"] or not archive["is_latest"]:
        print(
            "Error: dashboard generation was archived but did not become "
            "the latest indexed generation; input draft was preserved.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.append_journal:
        try:
            append_entry(
                parsed,
                archive_path=archive["markdown_path"],
                journal_path=args.journal_path,
            )
        except Exception as exc:
            safe_print(f"Warning: research journal append failed: {exc}")
    
    if args.delete_input and args.file:
        try:
            input_source = Path(args.file)
            current_stat = input_source.lstat()
            current_identity = (
                current_stat.st_dev,
                current_stat.st_ino,
                current_stat.st_size,
                current_stat.st_mtime_ns,
            )
            if current_identity != input_identity:
                safe_print(
                    "Warning: input draft changed during archive; "
                    "--delete-input was not applied."
                )
            else:
                input_source.unlink()
                safe_print(f"Cleaned up temporary JSON draft: {args.file}")
        except Exception as exc:
            safe_print(f"Warning: could not delete temporary file: {exc}")

    safe_print(f"Dashboard JSON saved to {archive['json_path']}")
    safe_print(f"Dashboard Markdown saved to {archive['markdown_path']}")
    if archive["index_updated"]:
        safe_print(f"Dashboard latest index updated at {archive['index_path']}")
    else:
        safe_print(
            "Dashboard generation archived; latest index retained at "
            f"{archive['index_path']}"
        )


if __name__ == "__main__":
    save_dashboard()
