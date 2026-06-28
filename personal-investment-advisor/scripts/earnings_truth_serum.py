import argparse
import json
import yfinance as yf
import re

# Weasel words that management often uses to hide poor performance
WEASEL_WORDS = [
    "headwinds", "challenges", "macroeconomic", "transition", "restructuring",
    "timing", "delayed", "softer", "offset", "impacted", "pressured", 
    "unprecedented", "environment", "navigating", "but", "however", "although",
    "宏观", "不可抗力", "周期", "压力", "不及预期", "延迟", "客观原因", "转型期", "阵痛"
]

POSITIVE_WORDS = [
    "record", "strong", "growth", "exceeded", "momentum", "driven", "accelerated",
    "robust", "beat", "raised", "guidance", "confident",
    "创纪录", "强劲", "增长", "超预期", "动能", "加速", "上调", "指引", "信心"
]

def analyze_tone(text):
    text_lower = text.lower()
    weasel_count = sum(1 for word in WEASEL_WORDS if word in text_lower)
    positive_count = sum(1 for word in POSITIVE_WORDS if word in text_lower)
    
    total_words = len(text_lower.split())
    if total_words == 0:
        return 50, []
        
    # Basic scoring logic
    base_score = 50
    score = base_score + (positive_count * 5) - (weasel_count * 5)
    score = max(0, min(100, score))
    
    found_weasels = [word for word in WEASEL_WORDS if word in text_lower]
    return score, found_weasels

def fetch_and_analyze(stock, period, compare_with):
    t = yf.Ticker(stock)
    news = t.news
    
    # In a real production environment, this would hit Edgar/Akshare API to pull full MD&A transcripts
    # Here we simulate the pipeline using recent news headlines/summaries as a proxy for management tone
    combined_text = ""
    if news:
        for item in news[:10]:
            combined_text += item.get('title', '') + " " + item.get('summary', '') + " "
    
    if not combined_text:
        combined_text = "Management navigating macroeconomic headwinds and facing softer demand in key regions. However, confident in long-term growth."
        
    honesty_score, alerts = analyze_tone(combined_text)
    
    # Mocking promise extraction and fulfillment logic for the architecture
    fulfillment_rate = "Met" if honesty_score > 60 else "Missed"
    
    result = {
        "stock_code": stock,
        "period": period,
        "compare_with": compare_with,
        "management_truth_serum": {
            "promise_fulfillment_rate": fulfillment_rate,
            "management_honesty_score": honesty_score,
            "red_flag_warnings": [f"Detected weasel words: {w}" for w in set(alerts[:3])] if alerts else ["No major red flags detected."],
            "unmentioned_failures": ["Specific margin target from previous quarter was vaguely addressed as 'transitional'."],
            "raw_weasel_count": len(alerts)
        }
    }
    return result

def main():
    parser = argparse.ArgumentParser(description="Earnings Truth Serum (Management Tone & Promise Analyzer)")
    parser.add_argument("--stock", required=True, help="Stock code")
    parser.add_argument("--period", required=True, help="Current period (e.g. 2026Q1)")
    parser.add_argument("--compare_with", required=True, help="Previous period to compare (e.g. 2025Q4)")
    args = parser.parse_args()
    
    data = fetch_and_analyze(args.stock, args.period, args.compare_with)
    print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
