import argparse
import json
import sys
from pathlib import Path


def generate_alerts(data: dict) -> list[str]:
    """Return research-monitoring notices without transaction instructions."""
    alerts: list[str] = []

    catalyst_map = data.get("catalyst_map", {})
    for item in catalyst_map.get("upcoming", []):
        alerts.append(f"待核验事件: {item}")
    for item in catalyst_map.get("broken", []):
        alerts.append(f"核心假设证伪信号: {item}")
    for item in catalyst_map.get("data_gaps", []):
        alerts.append(f"数据缺口: {item}")

    return alerts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate non-transactional research monitoring alerts."
    )
    parser.add_argument("json_path")
    args = parser.parse_args()

    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    alerts = generate_alerts(payload)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    message = json.dumps(alerts, ensure_ascii=False, indent=2)
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
