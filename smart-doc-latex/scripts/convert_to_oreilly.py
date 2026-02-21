import re
import sys
import os

def parse_markdown_to_latex(md_content):
    latex_lines = []
    
    # State tracking
    in_list = False
    list_type = None # 'ul' or 'ol'
    in_table = False
    table_lines = []
    
    lines = md_content.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Skip TOC lines (links at the start) until we hit the first Module
        if len(latex_lines) == 0 and not line.startswith('# 模块'):
            continue
            
        # --- Structural Elements ---
        
        # Level 1 Header: Module -> Part
        if line.startswith('# '):
            if in_list: latex_lines.append(r'\end{itemize}' if list_type == 'ul' else r'\end{enumerate}'); in_list = False
            title = line[2:].strip()
            latex_lines.append(r'\part{' + title + '}')
            continue
            
        # Level 2 Header: Lecture -> Chapter
        if line.startswith('## '):
            if in_list: latex_lines.append(r'\end{itemize}' if list_type == 'ul' else r'\end{enumerate}'); in_list = False
            title = line[2:].strip()
            # Remove "第X讲" prefix for cleaner TOC if desired, but keep for now
            latex_lines.append(r'\chapter{' + title + '}')
            continue
            
        # Level 3 Header: Section
        if line.startswith('### '):
            if in_list: latex_lines.append(r'\end{itemize}' if list_type == 'ul' else r'\end{enumerate}'); in_list = False
            title = line[4:].strip()
            latex_lines.append(r'\section{' + title + '}')
            continue
            
        # Level 4 Header: Subsection
        if line.startswith('#### '):
            if in_list: latex_lines.append(r'\end{itemize}' if list_type == 'ul' else r'\end{enumerate}'); in_list = False
            title = line[5:].strip()
            latex_lines.append(r'\subsection{' + title + '}')
            continue

        # --- Tables (Grid Tables from Pandoc) ---
        # Detect table lines (starting with + or | or -)
        # This is a simple heuristic for the grid table shown in the example
        if line.startswith('-------') or (line.startswith('|') and line.endswith('|')) or (len(line) > 5 and line.strip('-') == ''):
             # Complex table parsing is hard with regex. 
             # For this specific file, we might skip table parsing or use a simplified block handler.
             # Given the "O'Reilly" request, tables should be nice.
             # Let's try to detect the start/end of the table.
             # The example table had "---" lines.
             pass 

        # --- Lists ---
        # Unordered list
        if line.startswith('- ') or line.startswith('* '):
            if not in_list:
                latex_lines.append(r'\begin{itemize}')
                in_list = True
                list_type = 'ul'
            content = line[2:].strip()
            content = process_inline_formatting_v2(content)
            latex_lines.append(r'\item ' + content)
            continue
            
        # Ordered list
        elif re.match(r'^\d+\.\s', line):
            if not in_list:
                latex_lines.append(r'\begin{enumerate}')
                in_list = True
                list_type = 'ol'
            content = re.sub(r'^\d+\.\s', '', line).strip()
            content = process_inline_formatting_v2(content)
            latex_lines.append(r'\item ' + content)
            continue
        
        else:
            if in_list and line == '':
                # Empty line might end list, but markdown allows loose lists.
                # For safety in LaTeX, we close list on empty line followed by non-indent
                pass
            elif in_list and not (line.startswith('-') or re.match(r'^\d+\.', line)):
                # If content continues, it's part of the item, but usually markdown requires indent.
                # We'll close list if we see text that looks like a paragraph
                latex_lines.append(r'\end{itemize}' if list_type == 'ul' else r'\end{enumerate}')
                in_list = False

        # --- Text Paragraphs ---
        if line == '':
            latex_lines.append('')
            continue
            
        # Process bold/italic/code
        content = process_inline_formatting_v2(line)
        latex_lines.append(content + '\n')

    if in_list:
        latex_lines.append(r'\end{itemize}' if list_type == 'ul' else r'\end{enumerate}')

    return '\n'.join(latex_lines)

def process_inline_formatting(text):
    # Bold **text**
    text = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', text)
    # Italic *text*
    text = re.sub(r'\*(.*?)\*', r'\\textit{\1}', text)
    # Code `text`
    text = re.sub(r'`(.*?)`', r'\\texttt{\1}', text)
    # Escape LaTeX special chars
    text = text.replace('%', r'\%').replace('$', r'\$').replace('_', r'\_').replace('&', r'\&').replace('#', r'\#')
    # Un-escape formatting commands we just added (hacky but works for simple cases)
    text = text.replace(r'\\textbf{', r'\textbf{').replace(r'\\textit{', r'\textit{').replace(r'\\texttt{', r'\texttt{')
    # Re-fix the closing brace which was escaped
    # This naive escape/unescape is risky. Better to tokenize.
    # But for now, let's just escape specific chars that are NOT part of our commands.
    # Actually, simpler: escape FIRST, then apply regex.
    return text

# Improved formatted: Escape first, then regex
def process_inline_formatting_v2(text):
    # 1. Escape special characters
    chars_to_escape = ['%', '$', '_', '&', '#', '{', '}'] # Don't escape \ yet
    for char in chars_to_escape:
        text = text.replace(char, '\\' + char)
    
    # 2. Apply Markdown Regex
    # Note: Pandoc outputs **text** for bold.
    text = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', text)
    text = re.sub(r'\*(.*?)\*', r'\\textit{\1}', text)
    text = re.sub(r'`(.*?)`', r'\\texttt{\1}', text)
    
    # 3. Handle Images ![]() -> \includegraphics
    # pattern: ![\[alt\]](path)
    # text = re.sub(r'![\[(.*?)\]]\((.*?)\)', r'\\begin{figure}[h]\n\\centering\n\\includegraphics[width=0.8\\textwidth]{\2}\n\\caption{\1}\n\\end{figure}', text)
    
    return text

def generate_oreilly_latex(content_md, output_path, title="Book Title", author="Author", date="\\today"):
    preamble = r"""\documentclass[11pt, openany, a4paper]{ctexbook}

% ---------------------------------------------------------
% O'Reilly-Style Preamble
% ---------------------------------------------------------
\usepackage{geometry}
\geometry{
    top=2.5cm, bottom=2.5cm, 
    left=2.5cm, right=2.5cm,
    headheight=15pt,
    marginparsep=10pt
}

\usepackage{amsmath, amssymb, amsfonts}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{xcolor}
\usepackage{titlesec}
\usepackage{fancyhdr}
\usepackage[most]{tcolorbox}
\usepackage{fontspec}
\usepackage{enumitem}
\usepackage{parskip} % Non-indented paragraphs with spacing

% ---------------------------------------------------------
% Colors
% ---------------------------------------------------------
\definecolor{oreillyRed}{RGB}{176, 19, 26}  % Approximate O'Reilly Red
\definecolor{headerColor}{RGB}{0, 0, 0}
\definecolor{boxBg}{RGB}{245, 245, 245}

% ---------------------------------------------------------
% Fonts & Typography
% ---------------------------------------------------------
% Note: ctex handles Chinese fonts. 
% We set English sans-serif for headers.
\setsansfont{Arial} % Common fallback, or use Helvetica if available

% ---------------------------------------------------------
% Header/Footer
% ---------------------------------------------------------
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\itshape \leftmark}
\fancyhead[R]{\thepage}
\renewcommand{\headrulewidth}{0pt} % No line in some styles, or keeping it thin
\renewcommand{\headrulewidth}{0.5pt}

\fancypagestyle{plain}{
    \fancyhf{}
    \fancyfoot[C]{\thepage}
    \renewcommand{\headrulewidth}{0pt}
}

% ---------------------------------------------------------
% Headings
% ---------------------------------------------------------
% Part
\titleformat{\part}[display]
  {\sffamily\Huge\bfseries\color{headerColor}}
  {\partname\ \thepart}
  {20pt}
  {\thispagestyle{empty}}

% Chapter
\titleformat{\chapter}[display]
  {\sffamily\huge\bfseries\color{headerColor}}
  {\Large\chaptertitlename\ \thechapter}
  {20pt}
  {\Huge}
\titlespacing*{\chapter}{0pt}{0pt}{40pt}

% Section
\titleformat{\section}
  {\sffamily\Large\bfseries\color{oreillyRed}}
  {\thesection}{1em}{}

% Subsection
\titleformat{\subsection}
  {\sffamily\large\bfseries\color{headerColor}}
  {\thesubsection}{1em}{}

% ---------------------------------------------------------
% Custom Boxes (Sidebars, Tips)
% ---------------------------------------------------------
\newtcolorbox{oreillyBox}[1][]{
    enhanced,
    colback=boxBg,
    colframe=boxBg,
    borderline west={4pt}{0pt}{oreillyRed},
    sharp corners,
    fonttitle=\sffamily\bfseries,
    coltitle=black,
    title=#1,
    boxrule=0pt,
    left=10pt, right=10pt, top=10pt, bottom=10pt
}

% ---------------------------------------------------------
% Metadata
% ---------------------------------------------------------
\title{\bfseries\sffamily """ + title + r"""}
\author{""" + author + r"""}
\date{""" + date + r"""}

\begin{document}

\frontmatter
\maketitle
\tableofcontents

\mainmatter
"""
    
    body = parse_markdown_to_latex(content_md)
    
    postamble = r"""
\end{document}
"""
    
    full_latex = preamble + body + postamble
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_latex)
    return True

if __name__ == '__main__':
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    generate_oreilly_latex(content, output_file)
    print(f"Generated LaTeX file at {output_file}")
