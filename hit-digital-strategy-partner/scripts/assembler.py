import argparse
import glob
import json
import os
import re
from datetime import datetime
from pathlib import Path

MODE_MIN_WORDS = {
    "brief": 600,
    "deep-dive": 1200,
    "board-memo": 350,
}

REQUIRED_ASSETS = [
    "working_memory.json",
    "hypothesis_matrix.json",
    "evidence_matrix.csv",
    "outline.md",
    "implementation_plan.md",
]


def clean_content(content: str) -> str:
    content = re.sub(r'"""[\s\S]*?"""', '', content)
    content = re.sub(r'^---\n.*?\n---\n*', '', content, flags=re.MULTILINE | re.DOTALL)
    return content.strip()


def extract_action_titles(content: str) -> list[str]:
    titles = re.findall(r'^(#|##)\s+(.*)', content, re.MULTILINE)
    return [title for _level, title in titles]


def count_words(text: str) -> int:
    cjk_count = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_word_count = len(re.findall(r'\b[a-zA-Z0-9]+\b', text))
    return cjk_count + en_word_count


def audit_assets(project_path: Path) -> dict:
    return {asset: (project_path / asset).exists() for asset in REQUIRED_ASSETS}


def chapter_patterns(project_path: Path) -> list[str]:
    return [
        str(project_path / "chapter*.md"),
        str(project_path / "[0-9]*.md"),
        str(project_path / "chapters" / "chapter*.md"),
        str(project_path / "chapters" / "[0-9]*.md"),
    ]


def assemble_report(project_path: Path, output_filename: str, title: str, mode: str, min_words: int | None):
    min_words = min_words or MODE_MIN_WORDS[mode]
    files = []
    for pattern in chapter_patterns(project_path):
        files.extend(glob.glob(pattern))
    files = list(set(files))
    files.sort(key=lambda x: int(re.search(r'\d+', os.path.basename(x)).group()) if re.search(r'\d+', os.path.basename(x)) else 999)

    asset_audit = audit_assets(project_path)
    scqa_path = project_path / "scqa_summary.md"
    hypothesis_path = project_path / "hypothesis_matrix.json"

    merged_content = []
    current_date = datetime.now().strftime("%Y-%m-%d")
    yaml_header = f"""---
Title: {title}
Date: {current_date}
Status: 🔴 归档冻结
Author: HIT Digital Strategy Partner
Mode: {mode}
Version: V18.0 - Final Draft
Audience: Strategic Decision Makers
---

# {title}
> Strategic Intelligence Report | V18.0

"""
    merged_content.append(yaml_header)

    if scqa_path.exists():
        merged_content.append("## [Executive Storyline: SCQA]\n")
        merged_content.append(clean_content(scqa_path.read_text(encoding="utf-8")))
        merged_content.append("\n\n---\n\n")

    toc = []
    audit_results = []
    chapter_contents = []
    for file_path in files:
        raw_text = Path(file_path).read_text(encoding="utf-8")
        word_count = count_words(raw_text)
        clean_text = clean_content(raw_text)
        toc.extend(extract_action_titles(clean_text))
        chapter_contents.append(clean_text)
        audit_results.append({
            "file": os.path.basename(file_path),
            "words": word_count,
            "passed_depth": word_count >= min_words,
        })

    if toc:
        merged_content.append("## [Strategic Insight Index]\n")
        for idx, title_item in enumerate(toc, start=1):
            merged_content.append(f"{idx}. **{title_item}**\n")
        merged_content.append("\n---\n\n")

    for content in chapter_contents:
        merged_content.append(content)
        merged_content.append("\n\n---\n\n")

    if hypothesis_path.exists():
        try:
            hypothesis_data = json.loads(hypothesis_path.read_text(encoding="utf-8"))
            merged_content.append("## [Appendix: Hypothesis Validation Matrix]\n")
            merged_content.append("| Hypothesis | Status | Summary |\n|---|---|---|\n")
            for item in hypothesis_data.get("hypotheses", []):
                merged_content.append(f"| {item.get('statement', 'N/A')} | {item.get('status', 'open')} | {item.get('finding', 'N/A')} |\n")
        except json.JSONDecodeError:
            pass

    final_text = "".join(merged_content)
    output_path = project_path / output_filename
    output_path.write_text(final_text, encoding="utf-8")

    failed_chapters = [row["file"] for row in audit_results if not row["passed_depth"]]
    missing_assets = [name for name, exists in asset_audit.items() if not exists]
    status = "success"
    if failed_chapters:
        status = "warning_depth_insufficient"
    if missing_assets:
        status = "warning_missing_assets"

    return {
        "status": status,
        "path": str(output_path.resolve()),
        "mode": mode,
        "chapters_merged": len(files),
        "audit": audit_results,
        "failed_depth_list": failed_chapters,
        "asset_audit": asset_audit,
        "missing_assets": missing_assets,
        "final_size": len(final_text),
    }


def main():
    parser = argparse.ArgumentParser(description="Assemble strategic report")
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--output", default="final_report.md")
    parser.add_argument("--title", default="Strategic Deep Dive Report")
    parser.add_argument("--mode", default="deep-dive", choices=["brief", "deep-dive", "board-memo"])
    parser.add_argument("--min-words", type=int)
    args = parser.parse_args()

    result = assemble_report(args.path, args.output, args.title, args.mode, args.min_words)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
