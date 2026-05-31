import os
import json
import glob
from collections import defaultdict
from datetime import datetime

LOG_FILE = os.path.join(os.path.expanduser("~"), ".gemini", "MEMORY", "skill_audit", "skill-usage.jsonl")
TELEMETRY_DIR = os.path.join(os.path.expanduser("~"), ".gemini", "MEMORY", "skill_audit", "telemetry")

def analyze_telemetry():
    if not os.path.exists(TELEMETRY_DIR):
        os.makedirs(TELEMETRY_DIR, exist_ok=True)

    stats = defaultdict(lambda: {"count": 0, "total_duration": 0, "failures": 0, "total_input_tokens": 0, "total_output_tokens": 0})
    total_executions = 0
    total_failures = 0
    total_tokens = 0

    def process_data(data):
        nonlocal total_executions, total_failures, total_tokens
        skill = data.get("skill_name", "unknown")
        stats[skill]["count"] += 1
        stats[skill]["total_duration"] += data.get("duration_sec", 0)
        stats[skill]["total_input_tokens"] += data.get("input_tokens", 0)
        stats[skill]["total_output_tokens"] += data.get("output_tokens", 0)
        
        if data.get("status", "success").lower() != "success":
            stats[skill]["failures"] += 1
            total_failures += 1
            
        total_executions += 1
        total_tokens += data.get("input_tokens", 0) + data.get("output_tokens", 0)

    # 1. Process distributed JSON files (New Native Approach)
    json_files = glob.glob(os.path.join(TELEMETRY_DIR, "*.json"))
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors='ignore') as f:
                data = json.load(f)
                process_data(data)
        except (json.JSONDecodeError, IOError):
            continue

    # 2. Process legacy JSONL file (Fallback)
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8-sig", errors='ignore') as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        data = json.loads(line)
                        process_data(data)
                    except json.JSONDecodeError:
                        continue
        except IOError:
            pass

    if total_executions == 0:
        return "No telemetry data found in telemetry/ directory or legacy skill-usage.jsonl. Execute some skills first."

    output = f"### Quantitative Retro Analysis ({datetime.now().strftime('%Y-%m-%d')})\n\n"
    output += f"**Global Metrics:**\n"
    output += f"- Total Skill Executions: {total_executions}\n"
    output += f"- Total Failures: {total_failures} ({(total_failures/total_executions)*100:.1f}%)\n"
    output += f"- Total Tokens Consumed: {total_tokens}\n\n"

    output += f"**Skill-Specific Metrics:**\n"
    for skill, data in sorted(stats.items(), key=lambda x: x[1]["total_input_tokens"] + x[1]["total_output_tokens"], reverse=True):
        avg_duration = data["total_duration"] / data["count"] if data["count"] > 0 else 0
        avg_tokens = (data["total_input_tokens"] + data["total_output_tokens"]) / data["count"] if data["count"] > 0 else 0
        failure_rate = (data["failures"] / data["count"]) * 100
        
        output += f"- **{skill}**: Executed {data['count']} times\n"
        output += f"  - Avg Duration: {avg_duration:.2f}s | Failure Rate: {failure_rate:.1f}%\n"
        output += f"  - Avg Tokens/Call: {avg_tokens:.0f} (Total: {data['total_input_tokens'] + data['total_output_tokens']})\n"

    output += "\n**Agent Instruction:** Use this quantitative data to identify 'Token Heavy' or 'High Friction' skills. Propose architectural changes or `Gotchas` to optimize them."
    return output

if __name__ == "__main__":
    print(analyze_telemetry())
