"""
Standard Header
Pos: @SKILL/scripts/roi_calculator.py
Description: ROI 测算引擎 V4.0 (卫宁医疗版)。引入 License、AMC、实施费、硬件集成费，以及 DSO 影响。
"""

import sys
from utils import write_json_response, safe_json_load

def calculate_roi(input_data):
    # 医疗 IT 标准基准（三级医院千万级项目默认值）
    defaults = {
        "leads": 10,                 # 目标区域高意向客户数（如三甲）
        "conv_rate": 0.30,           # 核心客户转化率
        "budget_license": 500,       # 万元，软件授权费
        "budget_implementation": 300,# 万元，实施交付费
        "budget_hardware": 200,      # 万元，硬件及三方集成
        "amc_rate": 0.10,            # 维保比例 (基于软件+实施)
        "dso_months": 18,            # 医疗回款周期 (Days Sales Outstanding 换算为月)
        "cost_of_capital": 0.05      # 资金占用成本 (年化)
    }
    
    data = {k: input_data.get(k, defaults[k]) for k in defaults}
    
    # 单项目营收
    single_project_revenue = data["budget_license"] + data["budget_implementation"] + data["budget_hardware"]
    # 5年 LTV: 建设期收入 + 4年 AMC
    annual_amc = (data["budget_license"] + data["budget_implementation"]) * data["amc_rate"]
    single_project_ltv = single_project_revenue + (annual_amc * 4)
    
    # 预期总营收
    expected_projects = data["leads"] * data["conv_rate"]
    total_pipeline_revenue = expected_projects * single_project_revenue
    total_pipeline_ltv = expected_projects * single_project_ltv
    
    # 预估成本 (研发摊销 + 驻场实施 + 销售费用 + 资金成本)
    # 粗略估计总成本约为合同额的 60%，外加针对 DSO 的资金占用成本
    base_cost_margin = 0.60 
    capital_cost_rate = data["cost_of_capital"] * (data["dso_months"] / 12)
    
    total_cost = total_pipeline_revenue * base_cost_margin
    dso_capital_cost = total_pipeline_revenue * capital_cost_rate
    true_cost = total_cost + dso_capital_cost
    
    roi = (total_pipeline_ltv - true_cost) / true_cost if true_cost > 0 else 0
    
    return {
        "metrics": {
            "expected_projects": round(expected_projects, 1),
            "single_project_initial_revenue_W": single_project_revenue,
            "single_project_5y_ltv_W": single_project_ltv,
            "annual_amc_W": annual_amc
        },
        "financials": {
            "total_pipeline_revenue_projection_W": round(total_pipeline_revenue, 2),
            "total_pipeline_ltv_projection_W": round(total_pipeline_ltv, 2),
            "base_execution_cost_W": round(total_cost, 2),
            "dso_capital_cost_penalty_W": round(dso_capital_cost, 2),
            "roi_5y": round(roi, 2)
        },
        "risk_warning": "DSO 超过 12 个月将显著吞噬项目净利润。请在商务条款中锁定终验回款比例。" if data["dso_months"] > 12 else "回款周期健康。",
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
