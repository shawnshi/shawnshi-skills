"""
Standard Header
Pos: @SKILL/scripts/expert_panel.py
Description: 虚拟专家圆桌会议 (Synthetic Expert Panel)。模拟行业专家视角，提取 Quotes。
"""

import sys
from utils import write_json_response

def convene_panel():
    return {
        "panel_members": [
            {"role": "Local CIO", "focus": "Stability & Data Migration"},
            {"role": "Insurer/Gov Official", "focus": "Policy Compliance & Cost Control"},
            {"role": "Sales Lead", "focus": "Relationship & Pricing"}
        ],
        "instruction": "Simulate a roundtable. Generate 1 direct quote from each expert regarding the proposed strategy."
    }

if __name__ == "__main__":
    result = convene_panel()
    write_json_response(result)
