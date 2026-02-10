import re
import sys
import os

def process_latex_book(body_tex_path, output_path):
    with open(body_tex_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Strip the initial manual TOC part
    # We look for the first \part that is NOT "目录"
    # The TOC part looks like \part{\texorpdfstring{\textbf{目录}}{目录}}
    
    # We'll split by \part command
    parts = re.split(r'\\part{', content)
    
    # Reconstruct body starting from the first real part
    # parts[0] is preamble/junk before first part
    # parts[1] is likely "目录"
    # We iterate and find the first one that doesn't contain "目录" in the title
    
    real_body = ""
    start_index = 0
    
    # Debug: print first few characters of each part title
    for i, p in enumerate(parts):
        if i == 0: continue # Skip pre-part stuff
        
        # Check title. The title is up to the closing brace }
        # But braces can be nested. Simple heuristic: look at first 50 chars.
        if "目录" in p[:100]:
            print(f"Skipping TOC Part {i}")
            continue
        else:
            print(f"Found Content Part {i}: {p[:50]}...")
            start_index = i
            break
            
    if start_index > 0:
        # Reconstruct: Add "\part{" back because split removed it
        # We join all parts from start_index to end
        real_body = ""
        for p in parts[start_index:]:
            real_body += r"\part{" + p
    else:
        # Fallback if no parts found or all are TOC (unlikely)
        real_body = content

    # 2. O'Reilly Preamble
    preamble = r"""\documentclass[11pt, openany, a4paper]{ctexbook}

% ---------------------------------------------------------
% O'Reilly-Style Preamble
% ---------------------------------------------------------
\usepackage[top=2.5cm, bottom=2.5cm, left=2.5cm, right=2.5cm, headheight=15pt, marginparsep=10pt]{geometry}
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
\usepackage{parskip}
\usepackage[hidelinks, colorlinks=true, linkcolor=black, urlcolor=oreillyRed, citecolor=black]{hyperref}
\usepackage{calc}
\usepackage{array}
\usepackage{caption}
\usepackage{newunicodechar}

% Fix for Pandoc's \LTcaptype{none} issue with caption package
\newcounter{none}

% Fix for missing characters
\newunicodechar{≈}{$\approx$}

% ---------------------------------------------------------
% Colors
% ---------------------------------------------------------
\definecolor{oreillyRed}{RGB}{176, 19, 26}
\definecolor{headerColor}{RGB}{0, 0, 0}
\definecolor{boxBg}{RGB}{245, 245, 245}

% ---------------------------------------------------------
% Header/Footer
% ---------------------------------------------------------
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\itshape \leftmark}
\fancyhead[R]{\thepage}
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
% Fix Pandoc-generated quirks
% ---------------------------------------------------------
\providecommand{\tightlist}{%
  \setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

% ---------------------------------------------------------
% Metadata & Cover
% ---------------------------------------------------------
\title{\bfseries\sffamily 医疗大语言模型二十讲}
\author{师成}
\date{2025-11-12}

\begin{document}

\frontmatter

% Custom Title Page
\begin{titlepage}
    \begin{tikzpicture}[remember picture, overlay]
        % Top Red Bar
        \fill[oreillyRed] (current page.north west) rectangle ([yshift=-3cm]current page.north east);
    \end{tikzpicture}
    
    \vspace*{3cm}
    
    \begin{center}
        \sffamily
        
        % Series Title (Optional)
        {\Large\color{gray} \textbf{O'REILLY} \textit{Like Style} \par}
        
        \vspace{2cm}
        
        % Main Title
        {\Huge\bfseries\color{black} 医疗大语言模型二十讲 \par}
        \vspace{0.5cm}
        {\Large\bfseries Medical LLM: 20 Lectures \par}
        
        \vspace{1.5cm}
        \noindent\rule{0.6\textwidth}{1pt}
        \vspace{1.5cm}
        
        % Subtitle or Description
        {\Large 洞见权力、风险与成本的本质 \par}
        \vspace{0.5cm}
        {\large 从“第一性原理”到“方案构建”的完整战略闭环 \par}
        
        \vfill
        
        % Author
        {\Large\bfseries 师成 \par}
        \vspace{1cm}
        {\large 2025-11-12 \par}
        
    \end{center}
\end{titlepage}

\tableofcontents

\mainmatter
"""

    postamble = r"""
\end{document}
"""

    full_latex = preamble + real_body + postamble
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_latex)
    return True

if __name__ == '__main__':
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    if os.path.exists(input_file):
        process_latex_book(input_file, output_file)
        print(f"Generated LaTeX file at {output_file}")
    else:
        print(f"Error: Input file {input_file} not found.")
