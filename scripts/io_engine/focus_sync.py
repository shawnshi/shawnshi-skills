import argparse
import os
import re
import json

FOCUS_FILE = r"C:\Users\shich\.gemini\references\strategic_focus.json"

def extract_tactics(log_file):
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading log file: {e}")
        return None

    # Try to find Next Day Tactics section
    match = re.search(r'## 明日战术锁定[^\n]*\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if not match:
        return None

    tactics_block = match.group(1).strip()
    if not tactics_block:
        return None

    # Parse lines that look like list items
    lines = tactics_block.split('\n')
    all_tactics = []
    
    for line in lines:
        line = line.strip()
        # Match "1. xxx" or "- xxx" or "1、 xxx" or "1) xxx"
        cleaned = re.sub(r'^(\d+[\.\)\]、]|[-*])\s*', '', line)
        if cleaned:
            # Strip markdown bold tags if any
            cleaned = cleaned.replace('**', '')
            all_tactics.append(cleaned)

    if not all_tactics:
        return None

    # Identify high priority markers
    high_priority_markers = ['高优先', '绝对防御', '强干预', '系统强制', '🔴', '优先级-高', '优先级：高', '必须']
    
    high_priority_tactics = []
    for t in all_tactics:
        if any(marker in t for marker in high_priority_markers):
            high_priority_tactics.append(t)
            
    # If we found explicit high priority tasks, take the top 2
    if high_priority_tactics:
        tactics_to_use = high_priority_tactics[:2]
    else:
        # Fallback: just take the top 2 overall
        tactics_to_use = all_tactics[:2]

    # Clean up markers like [高优先级] for a cleaner title
    clean_tactics = []
    for t in tactics_to_use:
        t = re.sub(r'\[(高优先级|绝对防御|系统强制|强制干预|优先级-高)\]\s*', '', t)
        t = re.sub(r'【(系统强制|强制干预)】\s*', '', t)
        t = t.replace('🔴', '').strip()
        
        # Limit length per tactic to avoid overly long titles
        if len(t) > 40:
            t = t[:38] + "..."
        clean_tactics.append(t)

    return " | ".join(clean_tactics)

def update_strategic_focus(focus_text):
    data = {
        "current_focus": focus_text,
        "priority": "High",
        "auto_synced": True
    }
    
    os.makedirs(os.path.dirname(FOCUS_FILE), exist_ok=True)
    
    try:
        with open(FOCUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Success: Updated strategic_focus.json to '{focus_text}'")
    except Exception as e:
        print(f"Error writing strategic_focus.json: {e}")

def main():
    parser = argparse.ArgumentParser(description="Extract Next Day Tactics and sync to strategic_focus.json")
    parser.add_argument('--log_file', required=True, help="Path to the temporary diary markdown file")
    args = parser.parse_args()

    focus_text = extract_tactics(args.log_file)
    if focus_text:
        update_strategic_focus(focus_text)
    else:
        print("No valid tactics found in the log file, skipping focus sync.")

if __name__ == "__main__":
    main()
