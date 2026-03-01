import os
import sys
import json
import argparse
from datetime import datetime

def save_dashboard():
    parser = argparse.ArgumentParser(description="Save Stock Analysis Dashboard")
    parser.add_argument("--stock", required=True, help="Stock name (e.g. 腾讯)")
    parser.add_argument("--content", help="JSON content string. If not provided, reads from stdin.")
    
    args = parser.parse_args()
    
    content = args.content
    if not content:
        content = sys.stdin.read()
        
    try:
        # validate json
        parsed = json.loads(content)
        formatted_content = json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON content: {e}")
        sys.exit(1)
        
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{args.stock}_{date_str}.json"
    
    base_dir = os.path.join(os.path.expanduser("~"), ".gemini", "MEMORY", "stocks")
    
    os.makedirs(base_dir, exist_ok=True)
    
    filepath = os.path.join(base_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(formatted_content)
        
    print(f"Successfully saved dashboard to {filepath}")

if __name__ == "__main__":
    save_dashboard()
