import sys
import json
import os

# Ensure the script directory is in path
script_dir = r'C:\Users\shich\.gemini\skills\personal-investment-advisor\scripts'
sys.path.append(script_dir)

try:
    from akshare_fetcher import StandaloneDataFetcher
    fetcher = StandaloneDataFetcher()
    metrics = fetcher.get_enhanced_metrics('588000')
    print(json.dumps(metrics, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"error": str(e)}, ensure_ascii=False))
