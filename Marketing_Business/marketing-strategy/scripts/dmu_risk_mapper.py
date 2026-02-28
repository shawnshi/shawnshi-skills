"""
Standard Header
Pos: @SKILL/scripts/dmu_risk_mapper.py
Description: 医疗大 B 端决策单元 (DMU) 风险与权力地图映射工具。
"""

import sys
import json
from utils import write_json_response, safe_json_load

def map_dmu_risk(stakeholders):
    """
    stakeholders: list of { "role": str, "influence": 1-5, "support": 1-5, "veto_power": bool, "pain_point": str }
    """
    matrix = []
    total_resistance = 0
    high_risk_flags = []
    
    # 预设的医疗典型角色识别
    role_archetypes = {
        "院长": {"focus": "政绩与安全", "base_influence": 5},
        "分管副院长": {"focus": "业务指标达标", "base_influence": 4},
        "信息科主任": {"focus": "系统稳定性与运维压力", "base_influence": 4},
        "医务处长": {"focus": "国考排名与医疗质量", "base_influence": 3},
        "财务": {"focus": "现金流与医保飞检合规", "base_influence": 4},
        "医保办": {"focus": "现金流与医保飞检合规", "base_influence": 4},
    }
    
    for sh in stakeholders:
        role_name = sh.get("role", "Unknown")
        influence = sh.get("influence", 3)
        support = sh.get("support", 3)
        veto_power = sh.get("veto_power", False)
        
        # 匹配 Archetype 进行自动校准
        archetype = None
        for k, v in role_archetypes.items():
            if k in role_name:
                archetype = v
                break
                
        if archetype and "influence" not in sh:
            influence = archetype["base_influence"]
            
        # 阻力计算：影响力高且支持度低，如果有否决权则阻力翻倍
        resistance = influence * (6 - support)
        if veto_power and support < 3:
            resistance *= 2
            high_risk_flags.append(f"Veto Risk: {role_name} is actively opposing the project.")
            
        total_resistance += resistance
        
        strategy = "Empower (Highlight Political/Academic Value)" if support > 3 and influence >= 4 \
                   else "Align (Address Core Pain Point)" if support <= 3 and influence >= 3 \
                   else "Neutralize (Bypass or Isolate)" if influence < 3 and support < 3 \
                   else "Monitor"
                   
        matrix.append({
            "role": role_name,
            "inferred_focus": archetype["focus"] if archetype else "Unknown",
            "resistance_score": resistance,
            "has_veto": veto_power,
            "tactical_move": strategy
        })
    
    valid_count = len(stakeholders) if stakeholders else 1
    avg_resistance = total_resistance / valid_count
    
    overall_risk = "Critical (Immediate Intervention Required)" if avg_resistance > 12 or high_risk_flags \
                   else "High (Lobbying Needed)" if avg_resistance > 8 \
                   else "Manageable"
                   
    return {
        "dmu_matrix": matrix,
        "overall_risk_level": overall_risk,
        "red_flags": high_risk_flags,
        "action_required": "Initiate top-down alignment starting with Veto holders." if high_risk_flags else "Standard engagement sequence."
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
