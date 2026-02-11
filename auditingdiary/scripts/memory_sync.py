import argparse
import os
import re
import json
import sys

# Standard path for memory.md
MEMORY_FILE = "C:/Users/shich/.gemini/memory.md"

def update_memory_section(category, items_to_add):
    """
    Updates a specific section in memory.md with new unique items.
    category: '战略偏好' or '行业洞察'
    items_to_add: list of strings
    """
    if not os.path.exists(MEMORY_FILE):
        return {"status": "error", "message": f"memory.md not found at {MEMORY_FILE}"}

    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {"status": "error", "message": f"Failed to read memory.md: {str(e)}"}

    # Find the section header
    # Format matches: * ** 战略偏好** or * ** 行业洞察**
    pattern_section = rf"\* \*\* {category}\*\*"
    match = re.search(pattern_section, content)
    if not match:
        return {"status": "error", "message": f"Section '{category}' not found in memory.md"}

    section_start = match.end()
    # Find the end of this sub-section (before the next bullet point or next main header)
    next_section_match = re.search(r"\n\* \*\*|\n##", content[section_start:])
    section_end = section_start + next_section_match.start() if next_section_match else len(content)
    
    section_content = content[section_start:section_end]
    
    # Extract existing items (quoted strings) to prevent duplicates
    # Matches "...", or "..." (with optional trailing comma)
    existing_items = re.findall(r'"([^"]+)"', section_content)
    
    added_items = []
    for item in items_to_add:
        clean_item = item.strip().strip('"').strip("'")
        if not clean_item:
            continue
        # Normalize for comparison (basic check)
        if clean_item not in existing_items:
            added_items.append(clean_item)
            existing_items.append(clean_item) # Prevent duplicates in the same batch

    if not added_items:
        return {"status": "success", "message": f"No new unique items found for '{category}'."}

    # Format the new lines. Prepend them for chronological visibility.
    # Indentation is 4 spaces.
    new_lines = [f'    "{item}",' for item in added_items]
    
    # Construct the updated section content
    # Preserve the existing structure. We insert right after the section header line.
    prefix = "\n" if not section_content.startswith("\n") else ""
    updated_section_content = prefix + "\n".join(new_lines) + section_content
    
    new_full_content = content[:section_start] + updated_section_content + content[section_end:]
    
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            f.write(new_full_content)
        return {
            "status": "success", 
            "message": f"Successfully added {len(added_items)} items to '{category}'.",
            "added": added_items
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to write memory.md: {str(e)}"}

def main():
    parser = argparse.ArgumentParser(description="Memory Sync Utility for AuditingDiary")
    parser.add_argument('--category', choices=['战略偏好', '行业洞察'], required=True, help="Target section in memory.md")
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
        print(json.dumps({"status": "error", "message": "Items must be a JSON array of strings."}, ensure_ascii=False))
        sys.exit(1)
        
    result = update_memory_section(args.category, items_to_add)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
