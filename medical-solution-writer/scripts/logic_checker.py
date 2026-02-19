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
from collections import Counter

class MECELogicChecker:
    """
    医疗方案逻辑检查器：验证方案是否符合 MECE 原则
    - ME (Mutually Exclusive): 相互独立，检查章节间是否存在高度语义重叠。
    - CE (Collectively Exhaustive): 完全穷尽，检查核心战略维度是否缺失。
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
        # 提取所有二级和三级标题
        return re.findall(r'^(##+)\s+(.*)$', self.content, re.MULTILINE)

    def _split_sections(self):
        # 按标题分割内容块
        sections = {}
        parts = re.split(r'^##+\s+.*$', self.content, flags=re.MULTILINE)
        titles = [h[1] for h in self.headings]
        for i, title in enumerate(titles):
            if i + 1 < len(parts):
                sections[title] = parts[i+1].strip()
        return sections

    def check_me(self):
        """检查相互独立性 (Mutually Exclusive)"""
        overlaps = []
        titles = list(self.sections.keys())
        
        # 简单语义重叠检测：标题词频碰撞
        for i in range(len(titles)):
            for j in range(i + 1, len(titles)):
                t1, t2 = titles[i], titles[j]
                words1 = set(re.findall(r'\w+', t1))
                words2 = set(re.findall(r'\w+', t2))
                intersection = words1.intersection(words2)
                
                # 如果标题中有 2 个以上实词重叠，视为潜在 ME 风险
                ignored_words = {'的', '与', '及', '和', '中', '基于', '在'}
                meaningful_overlap = [w for w in intersection if w not in ignored_words]
                
                if len(meaningful_overlap) >= 2:
                    overlaps.append({
                        "sections": [t1, t2],
                        "overlap_keywords": meaningful_overlap,
                        "type": "Heading Overlap"
                    })
        return overlaps

    def check_ce(self):
        """检查完全穷尽性 (Collectively Exhaustive)"""
        # 顶级医疗数字化方案必须包含的维度
        mandatory_dimensions = {
            "架构": ["语义层", "MSL", "真相引擎", "架构"],
            "流程": ["业务流", "闭环", "T2A", "动作编排"],
            "合规": ["HITL", "分级", "责任", "问责", "安全"],
            "价值": ["ROI", "价值", "降本", "增效", "临床意义"]
        }
        
        missing = []
        full_text = self.content.lower()
        
        for dim, keywords in mandatory_dimensions.items():
            found = any(k.lower() in full_text for k in keywords)
            if not found:
                missing.append({
                    "dimension": dim,
                    "missing_keywords": keywords,
                    "suggestion": f"方案可能缺失【{dim}】维度，建议补充相关章节。"
                })
        return missing

    def run_audit(self):
        me_risks = self.check_me()
        ce_risks = self.check_ce()
        
        report = {
            "file": self.file_path,
            "status": "Warning" if (me_risks or ce_risks) else "Passed",
            "me_violations_count": len(me_risks),
            "ce_violations_count": len(ce_risks),
            "details": {
                "me_risks": me_risks,
                "ce_risks": ce_risks
            }
        }
        
        print(json.dumps(report, indent=4, ensure_ascii=False))
        
        # 如果存在严重缺失，建议 Exit 1
        if len(ce_risks) > 1:
            sys.exit(1)
        else:
            sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python logic_checker.py <file_path>")
        sys.exit(1)
    
    checker = MECELogicChecker(sys.argv[1])
    checker.run_audit()
