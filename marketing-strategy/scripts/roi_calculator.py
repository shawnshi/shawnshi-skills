"""
Standard Header
Pos: @SKILL/scripts/roi_calculator.py
Description: ROI 测算引擎 V3.1。增加地缘基准自动填充功能。
"""

import sys
from utils import write_json_response, safe_json_load

def calculate_roi(input_data):
    # 地缘默认基准 (基于 2026 行业均价)
    defaults = {
        "budget": 450,        # 万元 (中型三甲升级均价)
        "leads": 50,          # 目标客户数
        "conv_rate": 0.20,    # 转化率
        "initial_clv": 1000   # 万元 (5年 LTV)
    }
    
    # 自动填充缺失值
    data = {k: input_data.get(k, defaults[k]) for k in defaults}
    
    revenue = data["leads"] * data["conv_rate"] * data["initial_clv"]
    cost = data["leads"] * data["conv_rate"] * data["budget"]
    roi = (revenue - cost) / cost if cost > 0 else 0
    
    return {
        "revenue_projection": revenue,
        "cost_estimate": cost,
        "roi": round(roi, 2),
        "is_using_defaults": any(k not in input_data for k in defaults)
    }

if __name__ == "__main__":
    if not sys.stdin.isatty():
        input_content = sys.stdin.read()
    else:
        input_content = "{}"
    
    input_data = safe_json_load(input_content)
    result = calculate_roi(input_data)
    write_json_response(result)
