"""
Standard Header
Pos: @SKILL/scripts/expert_panel.py
Description: 医疗信息化虚拟专家圆桌会议 (Synthetic Expert Panel)。集成 logic-adversary 的 Debate (共识) 模式。
"""

import sys
from utils import write_json_response

def convene_panel():
    return {
        "panel_members": [
            {
                "role": "Regulator (卫健委/医保局视角)", 
                "focus": "合规性、DRG/DIP 控费、互联互通评级、数据要素安全与不跨院"
            },
            {
                "role": "Hospital President (院长)", 
                "focus": "医院整体政绩、一把手工程安全责任、现金流压力、社会与学术影响力"
            },
             {
                "role": "VP of IT (分管信息化副院长)", 
                "focus": "跨部门业务指标达标率、国考绩效排名提升、信息系统建设与医院战略规划的匹配度"
            },
            {
                "role": "Local CIO (三甲医院信息科主任)", 
                "focus": "微服务架构、系统双活高可用、旧系统历史数据无损迁移、信创适配"
            },
            {
                "role": "Sales Lead (一线销售老战狼)", 
                "focus": "客情深度、控标点设计、友商防守壁垒、招投标暗箱操作风险"
            }
        ],
        "instruction": (
            "MANDATORY INTEGRATION: You MUST use the `logic-adversary` skill to conduct this panel. "
            "Specifically, execute the 'Debate' workflow (refer to @logic-adversary/Workflows/Debate.md). "
            "Treat the `panel_members` defined above as 'Custom Council Members'. "
            "Run a full 3-round multi-agent debate (Round 1: Initial Positions -> Round 2: Responses & Challenges -> Round 3: Synthesis -> Council Synthesis) "
            "evaluating the proposed Medical IT strategic plan. Ensure high intellectual friction."
        )
    }

if __name__ == "__main__":
    result = convene_panel()
    write_json_response(result)
