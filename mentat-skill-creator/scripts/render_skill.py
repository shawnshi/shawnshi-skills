import json
import sys
import os

def render_skill_ir(json_path):
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        sys.exit(1)
        
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Output directory should be the same as json_path
    out_dir = os.path.dirname(json_path)
    md_path = os.path.join(out_dir, "SKILL.md")

    # Frontmatter
    fm = data.get("frontmatter", {})
    md_lines = []
    md_lines.append("---")
    for k, v in fm.items():
        if isinstance(v, list):
            md_lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            # quote description if it contains spaces and no quotes
            if k == "description" and not v.startswith("'") and not v.startswith('"'):
                md_lines.append(f"{k}: '{v}'")
            else:
                md_lines.append(f"{k}: {v}")
    md_lines.append("---")
    md_lines.append("")

    # Strategy Gene
    sg = data.get("strategy_gene")
    if sg:
        md_lines.append("<strategy-gene>")
        if sg.get("keywords"):
            if isinstance(sg["keywords"], list):
                md_lines.append(f"Keywords: {', '.join(sg['keywords'])}")
            else:
                md_lines.append(f"Keywords: {sg['keywords']}")
        if sg.get("summary"):
            md_lines.append(f"Summary: {sg['summary']}")
        
        strategy = sg.get("strategy", [])
        if strategy:
            md_lines.append("Strategy:")
            for i, step in enumerate(strategy, 1):
                md_lines.append(f"{i}. {step}")
        
        avoid = sg.get("avoid")
        if avoid:
            if isinstance(avoid, list):
                md_lines.append(f"AVOID: {' '.join(avoid)}")
            else:
                md_lines.append(f"AVOID: {avoid}")
        md_lines.append("</strategy-gene>")
        md_lines.append("")

    # Title & Intro
    md_lines.append(f"# {data.get('title', fm.get('name', 'Untitled Skill'))}")
    md_lines.append("")
    intro = data.get("intro")
    if intro:
        md_lines.append(intro)
        md_lines.append("")

    # Trajectory
    traj = data.get("trajectory")
    if traj:
        md_lines.append("## Tool Trajectory")
        md_lines.append("**[IN_ORDER]** 执行需遵循以下轨迹流：")
        for i, step in enumerate(traj, 1):
            md_lines.append(f"{i}. {step}")
        md_lines.append("")

    # Sections
    sections = data.get("sections", [])
    for sec in sections:
        title = sec.get("title", "")
        content = sec.get("content", "")
        if title:
            if not title.startswith("#"):
                md_lines.append(f"## {title}")
            else:
                md_lines.append(title)
        if isinstance(content, list):
            md_lines.append("\n".join(content))
        else:
            md_lines.append(content)
        md_lines.append("")

    # Write SKILL.md
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_lines))
    print(f"Successfully compiled {json_path} -> {md_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python render_skill.py <path_to_skill.json>")
        sys.exit(1)
    render_skill_ir(sys.argv[1])
