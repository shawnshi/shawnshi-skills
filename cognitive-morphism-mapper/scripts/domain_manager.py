"""
<!-- Input: Action (list/add), Domain Name, Metadata -->
<!-- Output: JSON Result or Domain File -->
<!-- Pos: scripts/domain_manager.py. Semantic Knowledge Base Manager. -->

!!! Maintenance Protocol: Ensure generated files comply with V2 Standard (100 fundamentals).
"""

import argparse
import os
import json
import glob
from pathlib import Path

# Configuration
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
REF_DIR = ROOT_DIR / "references"
CUSTOM_DIR = REF_DIR / "custom"

V2_TEMPLATE = """# Domain: {name}
# Source: {source}
# Structural_Primitives: {primitives}

## Fundamentals (100 基本基石)

### 导语
[100-150字，点破该领域最核心矛盾，冷峻简练宗师口吻]

### 一、哲学观 (18条)
[编号1-18，每条≤20字，有力简练，无常识]
...

### 二、核心原则 (22条)
[编号19-40，每条≤20字]
...

### 三、思维模型 (28条)
[编号41-68，每条≤20字]
...

### 四、关键方法论 (22条)
[编号69-90，每条≤20字]
...

### 五、避坑指南 (10条)
[编号91-100，每条≤20字]
...

## Core Objects (14个)
- **[Object 1]**: [定义]
  - *本质*: [一句话本质]
  - *关联*: [关联对象]
...

## Core Morphisms (14个)
- **[Morphism 1]**: [定义]
  - *涉及*: [涉及对象]
  - *动态*: [动态描述]
...

## Theorems / Patterns (18个)

### 1. [定理名称]
**内容**: [定理详细描述]

**Applicable_Structure**: [适用结构]

**Mapping_Hint**: [具体可操作："当Domain A...时，识别...，通过...实现..."]

**Case_Study**: [案例研究]
...

## Tags
[标签列表]
"""

def list_domains():
    domains = []
    # Built-in
    for f in glob.glob(str(REF_DIR / "*.md")):
        name = Path(f).stem
        if name.startswith("_") or name == "protocols" or name == "modules": continue
        domains.append({"name": name, "type": "builtin"})
    
    # Custom
    if CUSTOM_DIR.exists():
        for f in glob.glob(str(CUSTOM_DIR / "*_v2.md")):
            name = Path(f).stem.replace("_v2", "")
            domains.append({"name": name, "type": "custom"})
            
    return {"status": "success", "count": len(domains), "domains": domains}

def add_domain(name, source="Unknown", primitives="Unknown"):
    if not CUSTOM_DIR.exists():
        CUSTOM_DIR.mkdir(parents=True)
        
    safe_name = "".join([c for c in name if c.isalnum() or c in ('_', '-')])
    filename = f"{safe_name}_v2.md"
    file_path = CUSTOM_DIR / filename
    
    if file_path.exists():
        return {"status": "error", "message": f"Domain {safe_name} already exists."}
        
    content = V2_TEMPLATE.format(name=name, source=source, primitives=primitives)
    
    try:
        file_path.write_text(content, encoding="utf-8")
        return {"status": "success", "path": str(file_path), "message": "Domain template created."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    
    p_list = subparsers.add_parser("list")
    
    p_add = subparsers.add_parser("add")
    p_add.add_argument("name")
    p_add.add_argument("--source", default="TBD")
    p_add.add_argument("--primitives", default="TBD")
    
    args = parser.parse_args()
    
    if args.command == "list":
        print(json.dumps(list_domains(), indent=2, ensure_ascii=False))
    elif args.command == "add":
        print(json.dumps(add_domain(args.name, args.source, args.primitives), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
