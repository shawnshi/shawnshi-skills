import os
import sys
import glob
import time
import argparse
import datetime
from pathlib import Path
import google.generativeai as genai

# Setup paths
SKILL_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = SKILL_ROOT.parent.parent
DIARY_DIR = WORKSPACE_ROOT / "MEMORY" / "raw" / "privacy" / "Diary"
USER_MD = WORKSPACE_ROOT / "USER.md"
SOUL_MD = WORKSPACE_ROOT / "pai" / "SOUL.md"
OUTPUT_DIR = WORKSPACE_ROOT / "MEMORY" / "raw" / "read"
TMP_DIR = WORKSPACE_ROOT / "tmp" / "playgrounds" / "book_mirror"

AGENT_PROMPT_PATH = SKILL_ROOT / "agents" / "mirror-agent.md"

def extract_text(file_path: Path):
    print(f"[*] Extracting text from {file_path.name}...")
    chapters = []
    
    if file_path.suffix.lower() == '.epub':
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
        
        book = epub.read_epub(str(file_path))
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_body_content(), 'html.parser')
                text = soup.get_text('\n')
                text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
                if len(text.split()) > 100:  # Skip tiny frontmatters
                    chapters.append(text)
                    
    elif file_path.suffix.lower() == '.pdf':
        import fitz  # PyMuPDF
        doc = fitz.open(str(file_path))
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        
        # Naive split for PDFs, ideally look for "Chapter" but here we just chunk by 10k chars
        chunk_size = 10000
        for i in range(0, len(text), chunk_size):
            chapters.append(text[i:i+chunk_size])
            
    else:
        # Fallback to plain text
        text = file_path.read_text(encoding='utf-8', errors='replace')
        chunk_size = 10000
        for i in range(0, len(text), chunk_size):
            chapters.append(text[i:i+chunk_size])
            
    return chapters

def build_context_pack():
    print("[*] Building high-density context pack from past 14 days of Diary...")
    context = ""
    
    if USER_MD.exists():
        context += "## USER.md\n" + USER_MD.read_text(encoding='utf-8') + "\n\n"
    if SOUL_MD.exists():
        context += "## SOUL.md\n" + SOUL_MD.read_text(encoding='utf-8') + "\n\n"
        
    context += "## Recent Diary (Last 14 Days)\n"
    
    if DIARY_DIR.exists():
        now = datetime.datetime.now()
        fourteen_days_ago = now - datetime.timedelta(days=14)
        
        # Simple glob for markdown files, assuming they might have dates in names or we just check modification time
        for md_file in DIARY_DIR.glob("*.md"):
            mtime = datetime.datetime.fromtimestamp(md_file.stat().st_mtime)
            if mtime >= fourteen_days_ago:
                try:
                    content = md_file.read_text(encoding='utf-8')
                    context += f"### Entry: {md_file.name} (Date: {mtime.strftime('%Y-%m-%d')})\n{content}\n\n"
                except Exception as e:
                    pass
                    
    return context

def process_chapter(chapter_text, context_pack, agent_prompt, model):
    prompt = f"""{agent_prompt}

===
<CONTEXT_PACK>
{context_pack}
</CONTEXT_PACK>

===
<CHAPTER_CONTENT>
{chapter_text}
</CHAPTER_CONTENT>
"""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"| ⚠️ Error | 大模型调用失败: {str(e)} |"

def record_telemetry(duration_sec):
    telemetry_dir = WORKSPACE_ROOT / "MEMORY" / "skill_audit" / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    record_file = telemetry_dir / f"record_{{int(time.time())}}.json"
    
    import json
    data = {
        "skill_name": "cognitive-book-mirror",
        "status": "success",
        "duration_sec": round(duration_sec, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    with open(record_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    parser = argparse.ArgumentParser(description="Cognitive Book Mirror Execution")
    parser.add_argument("--file", type=str, required=True, help="Path to the EPUB or PDF book")
    args = parser.parse_args()
    
    target_file = Path(args.file)
    if not target_file.exists():
        print(f"[-] Error: File not found: {args.file}")
        sys.exit(1)
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[-] Error: GEMINI_API_KEY is not set.")
        sys.exit(1)
        
    start_time = time.time()
    
    genai.configure(api_key=api_key)
    # Use Gemini 1.5 Pro or similar suitable model. Flash is good enough usually.
    model = genai.GenerativeModel('gemini-3.5-flash') 
    
    # 1. Extraction
    chapters = extract_text(target_file)
    if not chapters:
        print("[-] Error: No content extracted.")
        sys.exit(1)
        
    # 2. Context Packing
    context_pack = build_context_pack()
    agent_prompt = AGENT_PROMPT_PATH.read_text(encoding='utf-8')
    
    # 3. Agent Execution
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{target_file.stem}_personalized_mirror.md"
    
    print(f"[*] Beginning Sandbox Reading Phase for {len(chapters)} chapters...")
    
    with open(output_file, 'w', encoding='utf-8') as out_f:
        out_f.write(f"# 认知镜像伴读: {target_file.stem}\n\n")
        
        for i, chapter in enumerate(chapters, 1):
            print(f"  -> Processing chunk {i}/{len(chapters)}...")
            result = process_chapter(chapter, context_pack, agent_prompt, model)
            out_f.write(f"## Section {i}\n\n{result}\n\n")
            # Minimal sleep to avoid extreme rate limiting
            time.sleep(2)
            
    print(f"[+] Success! Personalized mirror written to: {output_file}")
    
    # 4. Telemetry
    record_telemetry(time.time() - start_time)

if __name__ == "__main__":
    main()
