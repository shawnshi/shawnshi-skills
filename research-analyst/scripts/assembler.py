"""
<!-- Input: Project Path, Output Filename, Report Title, Strict Mode Toggle -->
<!-- Output: Merged Report Path, Strategic Summary, Quality Audit Report -->
<!-- Pos: scripts/assembler.py. The "Partner's Forge" that assembles the strategic report. V9.0 -->

!!! Maintenance Protocol: This script MUST verify character counts and enforce "Action-Title" extraction.
!!! ALL metadata blocks must be stripped, but strategic formatting (bolding) is now PERMITTED for emphasis.
"""

import argparse
import os
import glob
import sys
import re
import json

def clean_content(content):
    """Removes technical metadata while preserving strategic substance."""
    # 1. Remove GEB-Flow Metadata blocks (Triple quotes with comments)
    content = re.sub(r'"""[\s\S]*?"""', '', content)
    
    # 2. Remove YAML headers (--- ... ---) from intermediate chapters to prevent clutter
    content = re.sub(r'^---\n.*?\n---\n*', '', content, flags=re.MULTILINE | re.DOTALL)
    
    # 3. Trim whitespace
    return content.strip()
def extract_action_titles(content):
    """Extracts H1 and H2 headers to generate a Strategic Table of Contents."""
    titles = re.findall(r'^(#|##)\s+(.*)', content, re.MULTILINE)
    return [t[1] for t in titles]

def assemble_report(project_path, output_filename="final_report.md", title="Strategic Deep Dive Report", min_words=1200):
    # 1. Locate Chapters and Metadata
    patterns = [
        os.path.join(project_path, "chapter*.md"),
        os.path.join(project_path, "[0-9]*.md"),
        os.path.join(project_path, "chapters", "chapter*.md"),
        os.path.join(project_path, "chapters", "[0-9]*.md")
    ]
    
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    
    # Remove duplicates and sort by numeric prefix
    files = list(set(files))
    try:
        files.sort(key=lambda x: int(re.search(r'\d+', os.path.basename(x)).group()) if re.search(r'\d+', os.path.basename(x)) else 999)
    except:
        files.sort()

    scqa_path = os.path.join(project_path, "scqa_summary.md")
    hypothesis_path = os.path.join(project_path, "hypothesis_matrix.json")

    # 2. Forge Final Text with strict YAML metadata
    from datetime import datetime
    current_date = datetime.now().strftime('%Y-%m-%d')
    merged_content = []
    yaml_header = f"""---
Title: {title}
Date: {current_date}
Status: 🔴 归档冻结
Author: Healthcare Digital Strategy Partner
Version: V1.0 - Final Draft
Audience: Strategic Decision Makers
---

# {title}
> Strategic Intelligence Report | Research Analyst V14.0

"""
    merged_content.append(yaml_header)
    
    # Add SCQA if exists
    if os.path.exists(scqa_path):
        with open(scqa_path, 'r', encoding='utf-8') as f:
            merged_content.append("## [Executive Storyline: SCQA]\n")
            merged_content.append(clean_content(f.read()))
            merged_content.append("\n\n---\n\n")

    # Strategic Table of Contents (Action Titles)
    toc = []
    
    audit_results = []
    chapter_contents = []

    for f_path in files:
        with open(f_path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
            # Word count check: CJK characters + English words
            cjk_count = len(re.findall(r'[\u4e00-\u9fff]', raw_text))
            en_word_count = len(re.findall(r'\b[a-zA-Z0-9]+\b', raw_text))
            word_count = cjk_count + en_word_count
            
            clean_text = clean_content(raw_text)
            toc.extend(extract_action_titles(clean_text))
            
            chapter_contents.append(clean_text)
            
            audit_results.append({
                "file": os.path.basename(f_path),
                "words": word_count,
                "passed_depth": word_count >= min_words
            })

    # Insert TOC
    if toc:
        merged_content.append("## [Strategic Insight Index]\n")
        for idx, t in enumerate(toc):
            merged_content.append(f"{idx+1}. **{t}**\n")
        merged_content.append("\n---\n\n")

    # Append Chapters
    for content in chapter_contents:
        merged_content.append(content)
        merged_content.append("\n\n---\n\n")

    # Append Hypothesis Matrix if exists
    if os.path.exists(hypothesis_path):
        with open(hypothesis_path, 'r', encoding='utf-8') as f:
            try:
                hypo_data = json.load(f)
                merged_content.append("## [Appendix: Hypothesis Validation Matrix]\n")
                merged_content.append("| Hypothesis | Status | Summary |\n|---|---|---|\n")
                for h in hypo_data.get("hypotheses", []):
                    merged_content.append(f"| {h['statement']} | {h['status']} | {h.get('finding', 'N/A')} |\n")
            except:
                pass

    final_text = "".join(merged_content)
    
    # 3. Save
    output_path = os.path.abspath(os.path.join(project_path, output_filename))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_text)
    
    status = "success"
    failed_chapters = [a["file"] for a in audit_results if not a["passed_depth"]]
    if failed_chapters:
        status = "warning_depth_insufficient"
    
    return {
        "status": status,
        "path": output_path,
        "chapters_merged": len(files),
        "audit": audit_results,
        "failed_depth_list": failed_chapters,
        "final_size": len(final_text)
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--output", default="final_report.md")
    parser.add_argument("--title", default="Strategic Deep Dive Report")
    parser.add_argument("--min_words", type=int, default=1200)
    args = parser.parse_args()
    
    result = assemble_report(args.path, args.output, args.title, args.min_words)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
