import os
import json
import re

def sync_strategic_intelligence():
    """
    Syncs strategic insights between research-analyst and root memory.md.
    """
    # 1. Paths
    root_dir = "C:/Users/shich/.gemini"
    genome_path = os.path.join(root_dir, "skills/research-analyst/memory/strategic_genome.json")
    memory_path = os.path.join(root_dir, "memory.md")
    
    if not os.path.exists(genome_path) or not os.path.exists(memory_path):
        return {"status": "error", "message": f"Required files missing for sync. Path: {genome_path} or {memory_path}"}
    
    # 2. Load Genome
    with open(genome_path, 'r', encoding='utf-8') as f:
        genome = json.load(f)
    
    # 3. Format into Markdown with proper indentation
    prefs_md = ",\n    ".join([f'"{p}"' for p in genome.get("strategic_preferences", [])])
    insights_md = ",\n    ".join([f'"{i}"' for i in genome.get("historical_insights", [])])
    
    # 4. Load memory.md
    with open(memory_path, 'r', encoding='utf-8') as f:
        memory_content = f.read()
    
    # 5. Regex replacement for Strategic Preferences
    # Target: * ** 战略偏好** \n    [content]\n* ** 行业洞察**
    pref_pattern = r'(\* \*\* 战略偏好\*\* \n    )(.*?)(\n\* \*\* 行业洞察\*\*)'
    memory_content = re.sub(pref_pattern, f'\\1{prefs_md}\\3', memory_content, flags=re.DOTALL)
    
    # 6. Regex replacement for Industry Insights
    # Target: * ** 行业洞察** \n    [content]\n\n\n* **引用规范**
    insight_pattern = r'(\* \*\* 行业洞察\*\* \n    )(.*?)(\n\n\n\* \*\*引用规范\*\*)'
    memory_content = re.sub(insight_pattern, f'\\1{insights_md}\\3', memory_content, flags=re.DOTALL)
    
    # 7. Write back
    with open(memory_path, 'w', encoding='utf-8') as f:
        f.write(memory_content)
        
    return {"status": "success", "message": "Strategic intelligence synced to memory.md"}

if __name__ == "__main__":
    result = sync_strategic_intelligence()
    print(json.dumps(result, ensure_ascii=False, indent=2))
