"""
<!-- Input: Source file path (.md/.docx), Style (academic/cv/book), Metadata (Title/Author) -->
<!-- Output: Professional PDF and LaTeX Source (.tex) -->
<!-- Pos: scripts/smart_engine.py. Core orchestration engine handling conversion, styling, and compilation. -->

!!! Maintenance Protocol: If new styles are added to templates/, update detect_style() heuristics.
!!! Dependency: Requires Pandoc and XeLaTeX (TeX Live/MiKTeX) in system PATH.
"""

import os
import sys
import argparse
import subprocess
import re
import shutil

# Configuration
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')

def detect_style(file_path):
    """
    Simple keyword-based document classifier.
    """
    try:
        # Read first 3000 chars for analysis
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(3000).lower()
    except Exception as e:
        print(f"Warning: Could not read file for analysis: {e}")
        return "tech_report" # Default

    scores = {
        "academic": 0,
        "cv": 0,
        "tech_report": 0,
        "book": 0,
        "tech_book": 0
    }

    # Keyword Weights
    keywords = {
        "academic": ["abstract", "introduction", "reference", "conclusion", "method", "doi", "figure", "table"],
        "cv": ["education", "experience", "skills", "project", "resume", "curriculum vitae", "contact", "email"],
        "tech_report": ["code", "python", "java", "function", "api", "install", "usage", "guide", "tutorial"],
        "book": ["chapter", "prologue", "once upon a time", "dialogue", "story"],
        "tech_book": ["o'reilly", "technical", "programming", "software", "hardware"]
    }

    for style, words in keywords.items():
        for word in words:
            scores.setdefault(style, 0)
            scores[style] += content.count(word)

    # Heuristics
    if file_path.endswith('.md') and "```" in content:
        scores["tech_report"] += 5
        scores["tech_book"] += 5
    
    # Return style with max score
    best_style = max(scores, key=scores.get)
    print(f"DEBUG: Detection scores: {scores}")
    return best_style

def convert_and_compile(input_file, template_path, output_tex, style, title, author):
    """
    Use Pandoc to convert input doc and compile with the specified template natively.
    """
    try:
        # Build pandoc command array natively using the template
        cmd = [
            'pandoc', input_file,
            '--template', template_path,
            '--extract-media', '.',
            '-o', output_tex
        ]
        
        # Add metadata variables
        if title:
            cmd.extend(['-V', f'title={title}'])
        if author:
            cmd.extend(['-V', f'author={author}'])
            
        # Add conditional variables based on style
        if style == 'academic' or style == 'tech_report':
            # Simplified abstract extraction placeholder. 
            cmd.extend(['-V', 'abstract=']) 
            if style == 'tech_report':
                cmd.extend(['-V', 'toc=true'])
        
        if style == 'book' or style == 'tech_book':
             cmd.extend(['-V', 'toc=true'])

        # On Windows, we might need to force the environment to use UTF-8
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        print(f"Running Pandoc conversion with template: {os.path.basename(template_path)}...")
        subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', check=True, env=env)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running pandoc: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: 'pandoc' not found. Please install Pandoc.")
        sys.exit(1)

def compile_tex(tex_file):
    """
    Compile .tex file to PDF using xelatex.
    """
    try:
        # Run twice for references/TOC
        cmd = ['xelatex', '-interaction=nonstopmode', '-shell-escape', tex_file]
        print(f"Compiling: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True, text=True) # First pass
        subprocess.run(cmd, check=True, capture_output=True, text=True) # Second pass
        print(f"Compilation successful: {tex_file.replace('.tex', '.pdf')}")
    except subprocess.CalledProcessError as e:
        print("Error: Compilation failed. Please check the .log file.")
        
        # Output detailed error context from log instead of just last 20 lines
        log_file = tex_file.replace('.tex', '.log')
        if os.path.exists(log_file):
             with open(log_file, 'r', errors='ignore') as f:
                 log_content = f.read()
                 # Search for the first LaTeX Error line to provide actionable feedback
                 error_match = re.search(r'!\s(.*?\n(?:l\.\d+.*?\n)?)', log_content, flags=re.MULTILINE)
                 if error_match:
                     print("\n--- LaTeX Error Detected ---")
                     print(error_match.group(0).strip())
                 else:
                     print("\n--- Log Tail ---")
                     print(''.join(log_content.splitlines()[-20:]))
        else:
             print("\n--- Command Output ---")
             print(e.stdout[-500:])

def main():
    parser = argparse.ArgumentParser(description="Smart Doc-to-LaTeX Native Engine")
    parser.add_argument('--input', required=True, help="Input file path (.md, .docx, .txt)")
    parser.add_argument('--style', default='auto', choices=['auto', 'academic', 'cv', 'tech_report', 'book', 'tech_book'], help="Target document style")
    parser.add_argument('--title', help="Document title override")
    parser.add_argument('--author', help="Document author override")
    parser.add_argument('--output', help="Output directory (default: input file's directory)")
    
    args = parser.parse_args()

    # 1. Validation
    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found.")
        sys.exit(1)

    # 2. Style Detection
    style = args.style
    if style == 'auto':
        print("Analyzing document structure...")
        style = detect_style(args.input)
        print(f"Detected Style: {style.upper()}")

    # 3. Load Template
    template_path = os.path.join(TEMPLATE_DIR, f"{style}.tex")
    if not os.path.exists(template_path):
        print(f"Error: Template for '{style}' not found at {template_path}")
        sys.exit(1)

    # 4. Metadata
    filename_base = os.path.splitext(os.path.basename(args.input))[0]
    title = args.title if args.title else filename_base.replace('_', ' ').title()
    author = args.author if args.author else "Author"

    # 5. Save Output Logic
    output_dir = args.output if args.output else os.path.dirname(os.path.abspath(args.input))
    os.makedirs(output_dir, exist_ok=True)
    output_tex = os.path.join(output_dir, f"{filename_base}_{style}.tex")

    # 6. Conversion logic using Pandoc's Native Template Engine
    convert_and_compile(args.input, template_path, output_tex, style, title, author)
    print(f"Generated source: {output_tex}")

    # 7. Compile to PDF
    compile_tex(output_tex)

if __name__ == "__main__":
    main()
