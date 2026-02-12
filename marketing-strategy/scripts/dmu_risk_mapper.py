"""
Standard Header
Pos: @SKILL/scripts/dmu_risk_mapper.py
Description: B2B 决策单元 (DMU) 风险与利益对齐工具。
"""

import sys
import json
from utils import write_json_response, safe_json_load

def map_dmu_risk(stakeholders):
    """
    stakeholders: list of { "role": str, "influence": 1-5, "support": 1-5, "pain_point": str }
    """
    matrix = []
    total_resistance = 0
    
    for sh in stakeholders:
        influence = sh.get("influence", 3)
        support = sh.get("support", 3)
        # 阻力计算：影响力高且支持度低
        resistance = influence * (6 - support)
        total_resistance += resistance
        
        matrix.append({
            "role": sh.get("role"),
            "resistance_score": resistance,
            "strategy": "Empower" if support > 3 else "Neutralize" if influence > 3 else "Ignore"
        })
    
    avg_resistance = total_resistance / len(stakeholders) if stakeholders else 0
    
    return {
        "dmu_matrix": matrix,
        "overall_risk": "High" if avg_resistance > 15 else "Medium" if avg_resistance > 8 else "Low",
        "action_required": "Immediate multi-level lobbying" if avg_resistance > 15 else "Standard engagement"
    }

if __name__ == "__main__":
    if not sys.stdin.isatty():
        input_content = sys.stdin.read()
    elif len(sys.argv) > 1:
        input_content = sys.argv[1]
    else:
        input_content = "{}"
        
    input_data = safe_json_load(input_content)
    if "error" in input_data:
        write_json_response(input_data)
    else:
        result = map_dmu_risk(input_data.get("stakeholders", []))
        write_json_response(result)
