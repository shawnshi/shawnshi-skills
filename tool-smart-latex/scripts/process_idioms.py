"""
<!-- Input: An intermediate .tex file whose sections look like "48. A sweet tooth" -->
<!-- Output: A standalone ctexbook .tex collecting each entry's gloss and examples -->
<!-- Pos: scripts/process_idioms.py. Optional helper for idiom/dictionary sources. -->

!!! Maintenance Protocol: this helper is separate from smart_engine.py; it never
    rewrites the source file and never deletes numeric data from entries.

Usage:
    python process_idioms.py --input intermediate.tex --output idioms.tex
"""

import argparse
import re
import sys
from pathlib import Path

# A trailing "048.1" style audio marker is metadata; the same pattern inline in
# a sentence is real content and must survive.
TRAILING_MARKER_RE = re.compile(r"\s+\d{3,4}\.\d+\s*$")
SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{.*?(\d+)\.\s*(.*?)\}")
SECTION_WRAPPER_RE = re.compile(r"\\(?:sub)*section\*?\{([^{}]*)\}")
HYPERREF_RE = re.compile(r"\\hyperref\[[^\]]*\]\{([^{}]*)\}")
LABEL_RE = re.compile(r"\\label\{[^{}]*\}")
AUDIO_TAG_RE = re.compile(r"<audio[^>]*>.*?</audio>", re.S)
SPAN_TAG_RE = re.compile(r"</?span[^>]*>")
WHITESPACE_RE = re.compile(r"\s{2,}")

DEFINITION_MARKERS = ("释义",)
EXAMPLE_MARKERS = ("例句",)
SECTION_LINE_RE = re.compile(r"^\\(?:sub)*section\b")


def smarten_quotes(text):
    """Convert straight double quotes into alternating typographic pairs."""
    out = []
    opening = True
    for char in text:
        if char == '"':
            out.append("“" if opening else "”")
            opening = not opening
        else:
            out.append(char)
    return "".join(out)


SINGLE_QUOTE_MARKER = r"\textquotesingle"


def replace_directed_single_quotes(text):
    r"""
    Turn \textquotesingle markers into typographic single quotes.

    These sources use one markup form for both sides of a quotation.  A marker
    that follows a letter is an apostrophe or a closing mark (O'Reilly,
    students'); the remaining markers alternate between opening and closing, so
    'quoted' becomes an opening and a closing pair.  An elision at the start of
    a word ('tis) cannot be told apart from a quotation and reads as opening.
    """
    out = []
    index = 0
    opening = True
    while True:
        found = text.find(SINGLE_QUOTE_MARKER, index)
        if found < 0:
            out.append(text[index:])
            break
        before = text[found - 1] if found else " "
        out.append(text[index:found])
        if before.isalnum():
            out.append("’")
        else:
            out.append("‘" if opening else "’")
            opening = not opening
        index = found + len(SINGLE_QUOTE_MARKER)
    return "".join(out)


def smarten_apostrophes(text):
    """
    Convert remaining ASCII single quotes in prose to right single marks.

    At this point the directed pairs are already resolved, so a lone ASCII
    quote is an apostrophe or an unpaired close (O'Reilly, 'tis, students').
    """
    return text.replace("'", "’")


ITEM_PREFIX_RE = re.compile(r"^(?:\\item\b\s*)+")


def as_list_item(example):
    """Return one example as exactly one LaTeX list item."""
    return "\\item " + ITEM_PREFIX_RE.sub("", example)


def clean_text(text):
    """
    Strip markup from one entry line.

    Only a trailing audio marker is removed: the same digit pattern elsewhere
    is data and is preserved.
    """
    text = AUDIO_TAG_RE.sub("", text)
    text = SPAN_TAG_RE.sub("", text)
    text = HYPERREF_RE.sub(r"\1", text)
    text = LABEL_RE.sub("", text)
    text = replace_directed_single_quotes(text)
    text = text.replace(SINGLE_QUOTE_MARKER, "’")
    text = text.replace(r"\textquotedblleft", "“")
    text = text.replace(r"\textquotedblright", "”")
    text = text.replace("``", "“").replace("''", "”")
    text = SECTION_WRAPPER_RE.sub(r"\1", text)
    text = text.replace("**", "")
    text = ITEM_PREFIX_RE.sub("", text)
    text = TRAILING_MARKER_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)
    return smarten_apostrophes(smarten_quotes(text)).strip()


def parse_tex(file_path):
    """Parse `N. Term` sections with their gloss and example lines."""
    lines = Path(file_path).read_text(encoding="utf-8").splitlines()

    idioms = []
    current = None
    state = "NONE"

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        match = SECTION_RE.search(line)
        if match:
            if current:
                idioms.append(current)
            current = {
                "id": match.group(1),
                "term": match.group(2),
                "definition": [],
                "examples": [],
            }
            state = "NONE"
            continue

        if any(marker in line for marker in DEFINITION_MARKERS):
            state = "DEF"
            continue
        if any(marker in line for marker in EXAMPLE_MARKERS):
            state = "EXAMPLES"
            continue
        if current is None:
            continue
        if line.startswith(("\\begin", "\\end")) or SECTION_LINE_RE.match(line):
            continue

        cleaned = clean_text(line)
        if not cleaned:
            continue
        if state == "DEF":
            current["definition"].append(cleaned)
        elif state == "EXAMPLES":
            current["examples"].append(cleaned)

    if current:
        idioms.append(current)
    return idioms


HEADER = r"""\documentclass[10pt, openany]{book}
\usepackage[UTF8, scheme=plain]{ctex}
\usepackage[a5paper, margin=2cm]{geometry}
\usepackage{graphicx}
\usepackage{fancyhdr}
\usepackage{tcolorbox}
\usepackage{xcolor}
\usepackage{titlesec}
\usepackage{parskip}
\usepackage{ragged2e}

% Colors
\definecolor{mainblue}{RGB}{0, 105, 180}
\definecolor{lightgray}{RGB}{240, 240, 240}

% Title Formatting
\titleformat{\section}{\Large\bfseries\color{mainblue}}{}{0em}{}[\hrule]

% Idiom Environment
\newcommand{\idiomentry}[4]{
    \section{#1. #2}
    \begin{tcolorbox}[colback=lightgray, colframe=mainblue, title=Definition and Origin, arc=2mm]
        #3
    \end{tcolorbox}
    \textbf{Examples:}
    \begin{itemize}
        #4
    \end{itemize}
    \vspace{1cm}
}

\pagestyle{fancy}
\fancyhf{}
\fancyhead[LE,RO]{\thepage}
\fancyhead[RE,LO]{@@RUNNINGHEAD@@}

\begin{document}

\frontmatter
\title{\textbf{@@TITLE@@}}
\author{@@AUTHOR@@}
\date{}
\maketitle

\tableofcontents
\mainmatter

"""


def generate_latex(idioms, output_path, title="Most Common American Idioms", author="Dictionary"):
    """Write the collected entries as a standalone LaTeX document."""
    def sort_key(item):
        try:
            return (0, int(item["id"]))
        except (TypeError, ValueError):
            return (1, 0)

    ordered = sorted(idioms, key=sort_key)

    parts = [
        HEADER.replace("@@TITLE@@", title)
        .replace("@@AUTHOR@@", author)
        .replace("@@RUNNINGHEAD@@", title)
    ]
    for item in ordered:
        definition = "\n\n".join(item["definition"])
        examples = "".join(f"{as_list_item(example)}\n" for example in item["examples"])
        parts.append(
            f"\\idiomentry{{{item['id']}}}{{{item['term']}}}"
            f"{{{definition}}}{{{examples}}}\n"
        )
    parts.append(r"\end{document}")

    Path(output_path).write_text("".join(parts), encoding="utf-8")
    return len(ordered)


def main():
    parser = argparse.ArgumentParser(description="Idiom/dictionary LaTeX post-processor")
    parser.add_argument("--input", default="intermediate.tex", help="Intermediate .tex file")
    parser.add_argument(
        "--output", default="most-common-american-idioms.tex", help="Output .tex file"
    )
    parser.add_argument("--title", default="Most Common American Idioms")
    parser.add_argument("--author", default="Dictionary")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: input file '{args.input}' not found.")
        sys.exit(1)

    idioms = parse_tex(args.input)
    count = generate_latex(idioms, args.output, args.title, args.author)
    print(f"Parsed {count} idioms.")
    print(f"Generated source: {args.output}")
    if count == 0:
        print("Warning: no 'N. Term' sections were found; check the input structure.")


if __name__ == "__main__":
    main()
