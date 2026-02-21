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

def convert_to_latex_body(input_file):
    """
    Use Pandoc to convert input doc to a LaTeX fragment (body only).
    """
    try:
        # Explicitly set encoding to utf-8 to avoid CP1252 errors on Windows
        # Added --extract-media . to handle images in .docx files
        cmd = ['pandoc', input_file, '-t', 'latex', '--extract-media', '.']
        # On Windows, we might need to force the environment to use UTF-8
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', check=True, env=env)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running pandoc: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: 'pandoc' not found. Please install Pandoc.")
        sys.exit(1)
    except UnicodeDecodeError as e:
         print(f"Encoding Error: {e}")
         sys.exit(1)

def compile_tex(tex_file):
    """
    Compile .tex file to PDF using xelatex.
    """
    try:
        # Run twice for references/TOC
        cmd = ['xelatex', '-interaction=nonstopmode', '-shell-escape', tex_file]
        print(f"Compiling: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL) # First pass
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL) # Second pass
        print(f"Compilation successful: {tex_file.replace('.tex', '.pdf')}")
    except subprocess.CalledProcessError:
        print("Error: Compilation failed. Please check the .log file.")
        # Try to print last few lines of log
        log_file = tex_file.replace('.tex', '.log')
        if os.path.exists(log_file):
             with open(log_file, 'r', errors='ignore') as f:
                 print("\n--- Log Tail ---")
                 print(''.join(f.readlines()[-20:]))

def post_process_latex(latex_content):
    """
    Apply regex replacements to improve LaTeX quality.
    - Convert longtable to tabularx for width control.
    """
    # 1. Convert longtable to tabularx
    # Note: This is a heuristic. It assumes the table environment structure matches Pandoc's output.
    # We change the column specifier to 'X' for all columns to ensure they fit. 
    # This is aggressive but fulfills the requirement "Use tabularx".
    
    # Replace \begin{longtable} with \begin{tabularx}{\linewidth}
    # Pattern: \begin{longtable}[]{col_spec} ... \end{longtable}
    # We capture the col_spec (e.g., @{}ll@{}), and replace 'l', 'c', 'r' with 'X'
    
    def replacer(match):
        options = match.group(1) # e.g. []
        col_spec = match.group(2) # e.g. {@{}ll@{}}
        content = match.group(3)
        
        # Naive conversion of l/c/r to X to force width fitting
        new_col_spec = col_spec.replace('l', 'X').replace('c', 'X').replace('r', 'X')
        # Remove @{} to let X columns breathe? Or keep them. Let's keep structure but change alignment.
        
        return f"\\begin{{tabularx}}{{\\linewidth}}{options}{new_col_spec}{content}\\end{{tabularx}}"

    # Regex to find longtable blocks
    # Note: DOTALL is essential to match across lines
    pattern = r'\\begin\{longtable\}(\[.*?\])?(\{.*?\})(.*?)\\end\{longtable\}'
    processed = re.sub(pattern, replacer, latex_content, flags=re.DOTALL)
    
    return processed

def main():
    parser = argparse.ArgumentParser(description="Smart Doc-to-LaTeX Engine")
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

    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()

    # 4. Conversion
    print(f"Converting content using Pandoc...")
    body_latex = convert_to_latex_body(args.input)
    
    # Post-process body (Tables, etc.)
    body_latex = post_process_latex(body_latex)

    # 5. Injection & Metadata
    # Simple string replacement (in production, use Jinja2)
    filename_base = os.path.splitext(os.path.basename(args.input))[0]
    title = args.title if args.title else filename_base.replace('_', ' ').title()
    author = args.author if args.author else "Author"
    
    # Extract abstract if academic
    abstract = ""
    if style == 'academic':
        # Simple extraction: look for abstract env or use first paragraph
        # This is a placeholder for more complex logic
        pass 

    final_latex = template_content.replace('$body$', body_latex)
    final_latex = final_latex.replace('$title$', title)
    final_latex = final_latex.replace('$author$', author)
    final_latex = final_latex.replace('$date$', '\today')
    final_latex = final_latex.replace('$abstract$', abstract)
    
    # Handle missing conditional blocks (simple cleanup)
    final_latex = re.sub(r'\$if\(.*?\)\$.*?\$endif\$', '', final_latex, flags=re.DOTALL)

    # 6. Save Output
    output_dir = args.output if args.output else os.path.dirname(os.path.abspath(args.input))
    os.makedirs(output_dir, exist_ok=True)
    output_tex = os.path.join(output_dir, f"{filename_base}_{style}.tex")
    with open(output_tex, 'w', encoding='utf-8') as f:
        f.write(final_latex)
    
    print(f"Generated source: {output_tex}")

    # 7. Compile
    compile_tex(output_tex)

if __name__ == "__main__":
    main()
