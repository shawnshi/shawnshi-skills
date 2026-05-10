# -*- coding: utf-8 -*-
"""
commercial.py - Commercial metadata taxonomy for healthcare presentation assets.
"""
from __future__ import annotations

BUYER_PERSONAS = [
    "chairman",
    "president",
    "cio",
    "cmo",
    "clinical_expert",
    "procurement",
]

DEAL_STAGES = [
    "awareness",
    "strategy_alignment",
    "solution_evaluation",
    "pilot_design",
    "procurement",
    "board_approval",
]

OBJECTION_TAGS = [
    "roi_unclear",
    "implementation_risk",
    "governance_risk",
    "clinical_trust",
    "data_security",
    "integration_complexity",
    "vendor_differentiation",
]

PROOF_TYPES = [
    "policy",
    "case",
    "product",
    "research",
    "quantitative_outcome",
    "architecture",
]

EVIDENCE_TIERS = [
    "weak",
    "medium",
    "strong",
    "decisive",
]

COMMERCIAL_TAG_COLUMNS = {
    "buyer_personas": "TEXT",
    "deal_stage": "TEXT",
    "objection_tags": "TEXT",
    "proof_type": "TEXT",
    "evidence_tier": "TEXT",
}

DECK_MODE_PRESETS = {
    "board_strategy": {
        "buyer_persona": "chairman",
        "preferred_proof_types": ["quantitative_outcome", "case", "policy", "architecture"],
        "preferred_evidence_tiers": ["strong", "decisive"],
    },
    "hospital_leadership": {
        "buyer_persona": "president",
        "preferred_proof_types": ["case", "quantitative_outcome", "architecture"],
        "preferred_evidence_tiers": ["strong", "decisive"],
    },
    "cio_architecture": {
        "buyer_persona": "cio",
        "preferred_proof_types": ["architecture", "case", "product"],
        "preferred_evidence_tiers": ["medium", "strong", "decisive"],
    },
    "clinical_expert": {
        "buyer_persona": "clinical_expert",
        "preferred_proof_types": ["research", "case", "quantitative_outcome"],
        "preferred_evidence_tiers": ["strong", "decisive"],
    },
    "bid_response": {
        "buyer_persona": "procurement",
        "preferred_proof_types": ["case", "architecture", "product", "quantitative_outcome"],
        "preferred_evidence_tiers": ["strong", "decisive"],
    },
}


def ensure_tag_columns(conn) -> None:
    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(tags)").fetchall()
    }
    for column_name, column_type in COMMERCIAL_TAG_COLUMNS.items():
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE tags ADD COLUMN {column_name} {column_type}")


def json_contains_pattern(value: str) -> str:
    return f"%{value}%"


def infer_commercial_metadata(slide_like: dict) -> dict:
    title = str(slide_like.get("title") or "")
    body_text = str(slide_like.get("body_text") or "")
    summary = str(slide_like.get("summary") or "")
    content = "\n".join([title, body_text, summary]).lower()

    def has_any(*terms: str) -> bool:
        lowered_terms = [term.lower() for term in terms]
        return any(term in content for term in lowered_terms)

    buyer_personas = []
    if has_any("董事长", "集团", "资本", "投资回报", "回报率", "战略锚点", "治理体系"):
        buyer_personas.append("chairman")
    if has_any("院长", "高质量发展", "医院管理", "建设优势", "一体化", "管理闭环"):
        buyer_personas.append("president")
    if has_any("架构", "平台", "中台", "互联互通", "私有部署", "治理", "集成", "云原生", "信创"):
        buyer_personas.append("cio")
    if has_any("医疗质量", "患者安全", "VTE", "肿瘤分期", "临床决策", "诊疗", "质控"):
        buyer_personas.append("cmo")
    if has_any("临床", "医生", "病历", "报告", "影像", "专科", "诊断", "查房", "辅助决策"):
        buyer_personas.append("clinical_expert")
    if has_any("采购", "招标", "交付", "实施路径", "服务体系", "实施保障", "风险对冲"):
        buyer_personas.append("procurement")
    if not buyer_personas:
        buyer_personas = ["president"]

    if has_any("roi", "投资回报", "回报率", "资本", "集团", "董事会"):
        deal_stage = "board_approval"
    elif has_any("试点", "实施路径", "推进路径", "路线图", "复制"):
        deal_stage = "pilot_design"
    elif has_any("战略", "蓝图", "顶层设计", "原生医院", "架构演进"):
        deal_stage = "strategy_alignment"
    elif has_any("方案", "产品", "场景", "copilot", "wingpt", "智能体"):
        deal_stage = "solution_evaluation"
    elif has_any("采购", "招标", "信创", "服务体系", "建设优势"):
        deal_stage = "procurement"
    else:
        deal_stage = "awareness"

    objection_tags = []
    if has_any("roi", "投资回报", "成本", "降本增效", "效率", "回报率"):
        objection_tags.append("roi_unclear")
    if has_any("实施路径", "推进路径", "复制", "分阶段", "落地", "演进"):
        objection_tags.append("implementation_risk")
    if has_any("治理", "主权", "合规", "数据治理", "模型治理"):
        objection_tags.append("governance_risk")
    if has_any("临床", "医生", "质控", "病历", "辅助决策", "分期", "诊疗"):
        objection_tags.append("clinical_trust")
    if has_any("私有部署", "安全", "数据", "信创", "自主可控"):
        objection_tags.append("data_security")
    if has_any("集成", "平台", "互联互通", "中台", "架构"):
        objection_tags.append("integration_complexity")
    if has_any("建设优势", "领军企业", "标杆", "案例", "实践之道"):
        objection_tags.append("vendor_differentiation")

    if has_any("政策", "卫健委", "医保局", "国家", "红头文件"):
        proof_type = "policy"
    elif has_any("案例", "实践", "标杆", "医院", "客户"):
        proof_type = "case"
    elif has_any("radiology", "研究", "期刊", "论文", "评价研究"):
        proof_type = "research"
    elif has_any("成本", "效率", "回报", "%", "60%-70%", "量化", "节约"):
        proof_type = "quantitative_outcome"
    elif has_any("架构", "平台", "中台", "蓝图", "部署"):
        proof_type = "architecture"
    else:
        proof_type = "product"

    if has_any("radiology", "顶级期刊", "董事长", "集团", "国家", "标杆案例", "连续五年"):
        evidence_tier = "decisive"
    elif proof_type in {"case", "policy", "research", "quantitative_outcome"}:
        evidence_tier = "strong"
    elif proof_type in {"architecture", "product"}:
        evidence_tier = "medium"
    else:
        evidence_tier = "weak"

    return {
        "buyer_personas": sorted(set(buyer_personas)),
        "deal_stage": deal_stage,
        "objection_tags": sorted(set(objection_tags)),
        "proof_type": proof_type,
        "evidence_tier": evidence_tier,
    }
