import json
with open(r'C:\Users\shich\.gemini\antigravity-cli\brain\68315b05-bc65-4d4e-818c-f63dbd3bffab\.system_generated\tasks\task-125.log', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

start = text.find('[\n  {\n    "query"')
if start == -1:
    start = text.find('[')
json_str = text[start:text.rfind(']')+1]
try:
    data = json.loads(json_str)[0]
    with open('562910_raw.json', 'w', encoding='utf-8') as f:
        json.dump([data], f, ensure_ascii=False, indent=2)
    print("Extracted successfully!")
except Exception as e:
    print("Failed to extract:", e)
