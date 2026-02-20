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
        """启发式审计：标题是否过短（通常意味着描述性标签而非判词性标题）"""
        violations = []
        for level, title in self.headings:
            # 去除序号等干扰
            clean_title = re.sub(r'^\d+(\.\d+)*\s*', '', title)
            # 如果标题长度小于 8 个字符，大概率不是完整的逻辑判词
            if len(clean_title) < 8:
                violations.append({
                    "title": title,
                    "reason": "Title is too short. V4.0 requires 'Action Titles' (complete logical statements).",
                    "suggestion": f"将【{title}】重写为结论性语句（如：通过 XXX 提升 XXX）。"
                })
        return violations

    def check_me(self):
        overlaps = []
        titles = list(self.sections.keys())
        for i in range(len(titles)):
            for j in range(i + 1, len(titles)):
                t1, t2 = titles[i], titles[j]
                words1 = set(re.findall(r'\w+', t1))
                words2 = set(re.findall(r'\w+', t2))
                intersection = words1.intersection(words2)
                ignored_words = {'的', '与', '及', '和', '中', '基于', '在', '如何', '实现'}
                meaningful_overlap = [w for w in intersection if w not in ignored_words]
                if len(meaningful_overlap) >= 3: # 提升阈值，更严谨
                    overlaps.append({
                        "sections": [t1, t2],
                        "overlap_keywords": meaningful_overlap,
                        "type": "Heading Semantic Overlap"
                    })
        return overlaps

    def check_ce(self):
        # V4.0 强制性战略维度
        mandatory_dimensions = {
            "叙事轴心": ["SCQA", "冲突", "痛点", "背景"],
            "语义架构": ["MSL", "语义层", "真相引擎", "架构"],
            "意图流": ["T2A", "意图流", "动作编排", "ACI", "环境智能"],
            "责任归因": ["HITL", "人机回环", "归因", "安全边界", "数字防火墙"],
            "战略价值": ["So-What", "ROI", "价值", "收益", "影响", "Implications"]
        }
        missing = []
        full_text = self.content.lower()
        for dim, keywords in mandatory_dimensions.items():
            found = any(k.lower() in full_text for k in keywords)
            if not found:
                missing.append({
                    "dimension": dim,
                    "missing_keywords": keywords,
                    "suggestion": f"方案可能缺失【{dim}】维度，这是 V4.0 架构师标准的硬要求。"
                })
        return missing

    def run_audit(self):
        me_risks = self.check_me()
        ce_risks = self.check_ce()
        title_risks = self.check_action_titles()
        
        report = {
            "file": self.file_path,
            "status": "Warning" if (me_risks or ce_risks or title_risks) else "Passed",
            "metrics": {
                "me_violations": len(me_risks),
                "ce_violations": len(ce_risks),
                "title_violations": len(title_risks)
            },
            "details": {
                "action_title_risks": title_risks,
                "me_risks": me_risks,
                "ce_risks": ce_risks
            }
        }
        
        print(json.dumps(report, indent=4, ensure_ascii=False))
        if len(ce_risks) > 0 or len(title_risks) > 2:
            sys.exit(1)
        else:
            sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python logic_checker.py <file_path>")
        sys.exit(1)
    checker = MECELogicChecker(sys.argv[1])
    checker.run_audit()
