import re
import os

def clean_text(text):
    # Remove hyperref and label
    text = re.sub(r'\\hyperref\[.*?\]\{(.*?)\}', r'\1', text)
    text = re.sub(r'\\label\{.*?\}', '', text)
    # Remove textquotesingle
    text = text.replace(r'\\textquotesingle', "'")
    # Remove \section, \subsection wrappers if they remain
    text = re.sub(r'\\(sub)*section\{', '', text)
    text = text.replace('}', '')
    # Remove bold markers from markdown
    text = text.replace('**', '')
    # Remove audio IDs like 048.1, 1005.2 at end of lines
    text = re.sub(r'\d{3,4}\.\d+', '', text)
    # Remove other artifacts
    text = text.replace(r'\\textless/span\textgreater{}', '')
    text = text.replace(r'\\textless audio controls\textgreater\\textless source src="audio/', '')
    text = text.replace('"', "''") # Fix quotes roughly
    return text.strip()

def parse_tex(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    idioms = []
    current_idiom = None
    state = 'NONE' # NONE, DEF, EXAMPLES
    
    # Very permissive regex
    # Matches \section{... 48. A sweet tooth...}
    idiom_pattern = re.compile(r'\\(sub)*section\{.*?(\d+)\.\s*(.*?)\}')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Check for new idiom
        m = idiom_pattern.search(line)
        if m:
            if current_idiom:
                idioms.append(current_idiom)
            current_idiom = {
                'id': m.group(2),
                'term': m.group(3),
                'definition': [],
                'examples': []
            }
            state = 'NONE'
            continue
            
        if 'nt**释义**' in line or '**释义**' in line or '释义' == line:
            state = 'DEF'
            continue
            
        if 'nt**例句**' in line or '**例句**' in line or '例句' == line:
            state = 'EXAMPLES'
            continue
            
        if current_idiom is None:
            continue

        if state == 'DEF':
            if line.startswith('\\begin') or line.startswith('\\end') or line.startswith('\\') and 'section' in line:
                continue
            cleaned = clean_text(line)
            if cleaned:
                current_idiom['definition'].append(cleaned)
                
        elif state == 'EXAMPLES':
            if line.startswith('\\begin') or line.startswith('\\end') or line.startswith('\\') and 'section' in line:
                continue
            cleaned = clean_text(line)
            if cleaned:
                current_idiom['examples'].append(cleaned)

    if current_idiom:
        idioms.append(current_idiom)
        
    return idioms

def generate_latex(idioms, output_path):
    header = r"""\documentclass[10pt, openany]{book}
\usepackage[UTF8, scheme=plain]{ctex}
\usepackage[a5paper, margin=2cm]{geometry}
\usepackage{fancyhdr}
\usepackage{tcolorbox}
\usepackage{xcolor}
\usepackage{titlesec}
\usepackage{parskip}

% Colors
\definecolor{mainblue}{RGB}{0, 105, 180}
\definecolor{lightgray}{RGB}{240, 240, 240}

% Title Formatting
\titleformat{\section}{\Large\bfseries\color{mainblue}}{}{0em}{}[\hrule]

% Idiom Environment
\newcommand{\idiomentry}[4]{
    \section{#1. #2}
    \begin{tcolorbox}[colback=lightgray, colframe=mainblue, title=释义与起源, arc=2mm]
        #3
    \end{tcolorbox}
    \textbf{例句:}
    \begin{itemize}
        #4
    \end{itemize}
    \vspace{1cm}
}

\pagestyle{fancy}
\fancyhf{}
\fancyhead[LE,RO]{\thepage}
\fancyhead[RE,LO]{American Idioms}

\begin{document}

\title{\textbf{Most Common American Idioms}}
\author{Dictionary}
\date{}
\maketitle

\tableofcontents
\mainmatter

"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(header)
        
        # Sort idioms by ID just in case
        try:
            idioms.sort(key=lambda x: int(x['id']))
        except:
            pass # Keep original order if parsing fails
            
        for item in idioms:
            def_text = "\n\n".join(item['definition'])
            
            # Format examples as item list
            examples_text = ""
            for ex in item['examples']:
                examples_text += f"\\item {ex}\n"
            
            f.write(f"\\idiomentry{{{item['id']}}}{{{item['term']}}}{{{def_text}}}{{{examples_text}}}\n")
            
f.write(r"\\end{document}")

if __name__ == "__main__":
    idioms = parse_tex('intermediate.tex')
    print(f"Parsed {len(idioms)} idioms.")
    generate_latex(idioms, 'most-common-american-idioms.tex')