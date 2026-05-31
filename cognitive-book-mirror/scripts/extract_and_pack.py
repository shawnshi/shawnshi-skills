import os
import sys
import json
import argparse
import datetime
from pathlib import Path

# Setup paths
SKILL_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = SKILL_ROOT.parent.parent.parent
DIARY_DIR = WORKSPACE_ROOT / "MEMORY" / "raw" / "privacy" / "Diary"
USER_MD = WORKSPACE_ROOT / "USER.md"
SOUL_MD = WORKSPACE_ROOT / "pai" / "SOUL.md"
TMP_DIR = WORKSPACE_ROOT / "tmp" / "playgrounds" / "book_mirror"
AGENT_PROMPT_PATH = SKILL_ROOT / "agents" / "mirror-agent.md"

def extract_text(file_path: Path):
    print(f"[*] Extracting text from {file_path.name}...")
    
    ext = file_path.suffix.lower()
    if ext not in ['.md', '.txt']:
        print(f"[-] Error: Expected .md or .txt, but got {ext}.")
        sys.exit(1)
        
    def semantic_chunking(text, max_size=10000):
        chunks = []
        paragraphs = text.split('\n')
        current_chunk = ""
        for p in paragraphs:
            if len(current_chunk) + len(p) > max_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = p + "\n"
            else:
                current_chunk += p + "\n"
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        return chunks

    text = file_path.read_text(encoding='utf-8', errors='replace')
    chapters = semantic_chunking(text)
            
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
        
        for md_file in DIARY_DIR.glob("*.md"):
            mtime = datetime.datetime.fromtimestamp(md_file.stat().st_mtime)
            if mtime >= fourteen_days_ago:
                try:
                    content = md_file.read_text(encoding='utf-8')
                    context += f"### Entry: {md_file.name} (Date: {mtime.strftime('%Y-%m-%d')})\n{content}\n\n"
                except Exception:
                    pass
                    
    return context

def main():
    parser = argparse.ArgumentParser(description="Cognitive Book Mirror - Extract & Pack")
    parser.add_argument("--file", type=str, required=True, help="Path to the EPUB or PDF book")
    args = parser.parse_args()
    
    target_file = Path(args.file)
    if not target_file.exists():
        print(f"[-] Error: File not found: {args.file}")
        sys.exit(1)
        
    ext = target_file.suffix.lower()
    if ext not in ['.md', '.txt']:
        print(f"[*] Non-Markdown format detected ({ext}). Automatically routing to tool-markdown-converter...")
        converter_script = SKILL_ROOT.parent / "tool-markdown-converter" / "scripts" / "converter.py"
        md_file_path = target_file.with_suffix('.md')
        
        import subprocess
        try:
            cmd = [sys.executable, str(converter_script), str(target_file), "-o", str(md_file_path)]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if md_file_path.exists():
                print(f"[+] Successfully converted to Markdown: {md_file_path.name}")
                target_file = md_file_path
            else:
                print(f"[-] Auto-conversion failed or output file missing.\n{result.stderr}")
                sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"[-] Error: Auto-conversion failed.\n{e.stderr}")
            sys.exit(1)
        
    # 1. Extraction
    chapters = extract_text(target_file)
    if not chapters:
        print("[-] Error: No content extracted.")
        sys.exit(1)
        
    # 2. Context Packing
    context_pack = build_context_pack()
    
    # 3. Output to TMP_DIR
    book_tmp_dir = TMP_DIR / target_file.stem
    chunks_dir = book_tmp_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    
    context_file = book_tmp_dir / "context.md"
    context_file.write_text(context_pack, encoding='utf-8')
    
    agent_prompt = AGENT_PROMPT_PATH.read_text(encoding='utf-8')
    prompt_file = book_tmp_dir / "prompt.md"
    prompt_file.write_text(agent_prompt, encoding='utf-8')
    
    manifest = {
        "book_name": target_file.stem,
        "book_path": str(target_file),
        "total_chunks": len(chapters),
        "context_file": str(context_file),
        "prompt_file": str(prompt_file),
        "chunks": []
    }
    
    print(f"[*] Saving {len(chapters)} chunks to {chunks_dir}...")
    for i, chapter in enumerate(chapters, 1):
        chunk_file = chunks_dir / f"chunk_{i:03d}.txt"
        chunk_file.write_text(chapter, encoding='utf-8')
        manifest["chunks"].append({
            "index": i,
            "file": str(chunk_file)
        })
        
    manifest_file = book_tmp_dir / "manifest.json"
    with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        
    print(f"[+] Extraction complete. Manifest saved to: {manifest_file}")

if __name__ == "__main__":
    main()
