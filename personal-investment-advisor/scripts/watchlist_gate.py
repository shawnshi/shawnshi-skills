import argparse
import json
import sys
from pathlib import Path


def _safe_float(value):
    try:
        if value in (None, "", "N/A"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def generate_alerts(data: dict) -> list[str]:
    alerts: list[str] = []
    price = _safe_float(data.get("dashboard", {}).get("data_perspective", {}).get("price_position", {}).get("current_price"))
    sniper = data.get("dashboard", {}).get("battle_plan", {}).get("sniper_points", {})
    stop_loss = _safe_float(sniper.get("stop_loss"))
    take_profit = _safe_float(sniper.get("take_profit"))
    support = _safe_float(data.get("dashboard", {}).get("data_perspective", {}).get("price_position", {}).get("support_level"))
    resistance = _safe_float(data.get("dashboard", {}).get("data_perspective", {}).get("price_position", {}).get("resistance_level"))

    if price is not None and stop_loss is not None and price <= stop_loss:
        alerts.append("价格已触及或跌破止损位")
    if price is not None and support is not None and price <= support:
        alerts.append("价格接近或跌破关键支撑")
    if price is not None and resistance is not None and price >= resistance:
        alerts.append("价格已接近或突破关键压力位")
    if price is not None and take_profit is not None and price >= take_profit:
        alerts.append("价格已触及止盈位")

    catalyst_map = data.get("catalyst_map", {})
    for item in catalyst_map.get("upcoming", []):
        alerts.append(f"即将到来的催化: {item}")
    for item in catalyst_map.get("broken", []):
        alerts.append(f"thesis 破坏警示: {item}")

    return alerts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate watchlist alerts from dashboard JSON.")
    parser.add_argument("json_path")
    args = parser.parse_args()

    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    alerts = generate_alerts(payload)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    message = json.dumps(alerts, ensure_ascii=False, indent=2)
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
