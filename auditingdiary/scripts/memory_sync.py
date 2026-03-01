import argparse
import os
import re
import json
import sys

# Standard path for memory.md in PAI context
MEMORY_FILE = "C:/Users/shich/.gemini/pai/memory.md"

def update_memory_section(category, items_to_add):
    """
    Updates memory.md with new unique items in the Gemini Added Memories section.
    category: e.g., '战略偏好' or '行业洞察'
    items_to_add: list of strings or dicts with 'content' and optional 'impact_vector'
    """
    if not os.path.exists(MEMORY_FILE):
        return {"status": "error", "message": f"memory.md not found at {MEMORY_FILE}"}

    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {"status": "error", "message": f"Failed to read memory.md: {str(e)}"}

    # Identify the 'Gemini Added Memories' section
    marker = "## Gemini Added Memories"
    if marker not in content:
        # If not found, append it to the end
        content += f"\n\n{marker}\n"
    
    # We will append new items to the end of the file/section
    added_items = []
    for item_data in items_to_add:
        if isinstance(item_data, dict):
            content_str = item_data.get('content', '')
            impact = item_data.get('impact_vector', '')
            full_item = f"[{category}] {content_str}"
            if impact:
                full_item += f" (Impact Vector: {impact})"
        else:
            full_item = f"[{category}] {item_data}"
        
        # Prevent duplicates
        if f"- {full_item}" not in content:
            added_items.append(full_item)

    if not added_items:
        return {"status": "success", "message": f"No new unique items found for '{category}'."}

    # Construct the new content
    # Append new items at the end of the section (end of file for now)
    new_lines = [f"- {item}" for item in added_items]
    updated_content = content.strip() + "\n" + "\n".join(new_lines) + "\n"
    
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        return {
            "status": "success", 
            "message": f"Successfully added {len(added_items)} items to memory.",
            "added": added_items
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to write memory.md: {str(e)}"}

def main():
    parser = argparse.ArgumentParser(description="Memory Sync Utility for AuditingDiary (Optimized)")
    parser.add_argument('--category', required=True, help="Category prefix, e.g., '战略偏好' or '行业洞察'")
    parser.add_argument('--items', help="JSON array of items to add")
    parser.add_argument('--file', help="Path to a JSON file containing items to add")
    
    args = parser.parse_args()
    
    items_to_add = []
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                items_to_add = json.load(f)
        except Exception as e:
            print(json.dumps({"status": "error", "message": f"Failed to read items file: {str(e)}"}, ensure_ascii=False))
            sys.exit(1)
    elif args.items:
        try:
            items_to_add = json.loads(args.items)
        except Exception as e:
            print(json.dumps({"status": "error", "message": f"Invalid items format: {str(e)}"}, ensure_ascii=False))
            sys.exit(1)
    else:
        print(json.dumps({"status": "error", "message": "Either --items or --file must be provided."}, ensure_ascii=False))
        sys.exit(1)

    if not isinstance(items_to_add, list):
        print(json.dumps({"status": "error", "message": "Items must be a JSON array."}, ensure_ascii=False))
        sys.exit(1)
        
    result = update_memory_section(args.category, items_to_add)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
