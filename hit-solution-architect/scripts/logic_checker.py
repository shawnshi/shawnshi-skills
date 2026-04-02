"""
<!-- Standard Header -->
@Input: [ProjectName]_Draft.md (Markdown file)
@Output: MECE Audit Result (Standard Out/JSON)
@Pos: Phase 5 (Audit Phase)
@Maintenance Protocol: Logic rules update must sync SKILL.md.
"""
import re
import sys
import json

class MECELogicChecker:
    """
    医疗方案战略逻辑检查器 V4.0：验证方案是否符合 MBB 合伙人级标准
    - ME (Mutually Exclusive): 相互独立，检查章节间是否存在高度语义重叠。
    - CE (Collectively Exhaustive): 完全穷尽，检查 V4.0 核心架构维度是否缺失。
    - Action Titles Audit: 启发式审计标题是否具备“判词性”。
    """
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.content = self._read_file()
        self.headings = self._extract_headings()
        self.sections = self._split_sections()

    def _read_file(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading file: {e}")
            sys.exit(1)

    def _extract_headings(self):
        # 提取二级和三级标题
        return re.findall(r'^(##+)\s+(.*)$', self.content, re.MULTILINE)

    def _split_sections(self):
        sections = {}
        parts = re.split(r'^##+\s+.*$', self.content, flags=re.MULTILINE)
        titles = [h[1] for h in self.headings]
        for i, title in enumerate(titles):
            if i + 1 < len(parts):
                sections[title] = parts[i+1].strip()
        return sections

    def check_action_titles(self):
        """启发式审计：标题是否具备动作导向（Action-oriented）与判词性"""
        violations = []
        # 动作导向关键词（判词性特征）
        action_patterns = [r"通过", r"实现", r"构建", r"打造", r"优化", r"提升", r"重构", r"驱动", r"赋能", r"解决"]
        
        for level, title in self.headings:
            # 去除序号等干扰
            clean_title = re.sub(r'^\d+(\.\d+)*\s*', '', title)
            
            # 规则 1：长度审计（过短通常不是完整判词）
            is_short = len(clean_title) < 8
            
            # 规则 2：动作模式审计
            has_action = any(re.search(p, clean_title) for p in action_patterns)
            
            if is_short or not has_action:
                reason = "标题过于简略或缺乏动作导向。" if is_short else "标题缺乏结论性判词特征（缺少动作谓语或逻辑关联词）。"
                violations.append({
                    "title": title,
                    "reason": f"{reason} V8.5 要求使用 'Action Titles'。",
                    "suggestion": f"建议重写为包含『动作+目标+价值』的判词。例：『通过 WiNEX 临床路径重构实现医保结余提留』。"
                })
        return violations

    def check_empty_metrics(self):
        """检查是否存在空洞的量化描述（如只说提升效率而不给指标预估）"""
        empty_metrics_patterns = [r"提升效率", r"降低成本", r"优化流程", r"增强体验", r"提高质量"]
        violations = []
        for title, content in self.sections.items():
            for pattern in empty_metrics_patterns:
                if pattern in content:
                    # 检查附近是否有百分比或数字
                    context = re.findall(rf".{{0,30}}{pattern}.{{0,30}}", content)
                    for ctx in context:
                        if not re.search(r"\d+%|\d+倍|\d+分", ctx):
                            violations.append({
                                "section": title,
                                "context": ctx.strip(),
                                "reason": f"检测到空洞量化词『{pattern}』，缺乏具体的百分比或数字支撑。",
                                "suggestion": "请补充具体指标预估，如『提升效率 30% 以上』。"
                            })
        return violations

    def check_ce(self):
        # V8.5 强制性战略维度（与 SKILL.md V8.5 核心约束对齐）
        mandatory_dimensions = {
            "叙事与背景": ["背景", "挑战", "愿景", "痛点", "冲突", "现状"],
            "信创合规": ["信创", "国产化", "等保", "安全", "合规", "自主可控", "华为", "昇腾", "海光", "达梦"],
            "旧城改造": ["迁移", "割接", "并行", "双活", "旧系统", "数据清洗", "平滑", "无损"],
            "TCO与ROI": ["TCO", "ROI", "成本", "总体拥有成本", "投资回报", "预算", "节省", "产出"],
            "受众分层": ["院长", "CIO", "临床", "科主任", "护士", "管理层"],
            "DRG与医保": ["DRG", "DIP", "医保", "控费", "结余", "国考", "盈亏"],
            "架构设计": ["架构", "微服务", "中台", "云原生", "API", "FHIR", "WiNEX"],
            "AI赋能": ["AI", "GPT", "大模型", "Copilot", "智能助手", "WiNGPT"]
        }
        missing = []
        full_text = self.content.lower()
        for dim, keywords in mandatory_dimensions.items():
            found = any(k.lower() in full_text for k in keywords)
            if not found:
                missing.append({
                    "dimension": dim,
                    "missing_keywords": keywords,
                    "suggestion": f"方案可能缺失【{dim}】维度，这是 V8.5 架构师标准的硬要求。"
                })
        return missing

    def run_audit(self):
        me_risks = self.check_me()
        ce_risks = self.check_ce()
        title_risks = self.check_action_titles()
        metric_risks = self.check_empty_metrics()
        
        report = {
            "file": self.file_path,
            "status": "Warning" if (me_risks or ce_risks or title_risks or metric_risks) else "Passed",
            "metrics": {
                "me_violations": len(me_risks),
                "ce_violations": len(ce_risks),
                "title_violations": len(title_risks),
                "empty_metrics_violations": len(metric_risks)
            },
            "details": {
                "action_title_risks": title_risks,
                "empty_metrics_risks": metric_risks,
                "me_risks": me_risks,
                "ce_risks": ce_risks
            }
        }
        
        print(json.dumps(report, indent=4, ensure_ascii=False))
        # V8.5 门控：若缺失维度或标题风险过多，强制熔断
        if len(ce_risks) > 0 or len(title_risks) > 3 or len(metric_risks) > 5:
            sys.exit(1)
        else:
            sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python logic_checker.py <file_path>")
        sys.exit(1)
    checker = MECELogicChecker(sys.argv[1])
    checker.run_audit()
