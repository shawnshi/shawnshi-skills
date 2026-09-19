"""
<!-- Input: Source file path (.md/.docx/.txt), Style (academic/cv/book/...), Metadata (Title/Author) -->
<!-- Output: Professional PDF and LaTeX Source (.tex) -->
<!-- Pos: scripts/smart_engine.py. Core orchestration engine handling conversion, styling, and compilation. -->

!!! Maintenance Protocol: If new styles are added to templates/, update detect_style()
    heuristics, STYLE_TIE_PRIORITY, DEFAULT_NUMBER_SECTIONS and BOX_MAPS.
!!! Dependency: Requires Pandoc and XeLaTeX (TeX Live/MiKTeX) in system PATH.

Language routing: the templates take one switch, `cjk`, which selects the CTeX
`scheme` (Chinese heading names plus CTeX leading, or English names plus the
class baseline inside the 120-145% leading target) and the document labels.
This module derives `cjk` from the source text unless it is set explicitly.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Configuration
SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_ROOT / "templates"
FILTER_DIR = SKILL_ROOT / "scripts"

PANDOC_TIMEOUT = 60
XELATEX_TIMEOUT = 40
MAX_LATEX_PASSES = 3

DEFAULT_STYLE = "tech_report"
# Deterministic order used when two styles score equally (most specific first).
STYLE_TIE_PRIORITY = ["academic", "cv", "tech_book", "book", "tech_report"]

# Styles whose headings are chapters, not sections.
CHAPTER_STYLES = {"book", "tech_book"}
# Styles converted with --listings instead of Pandoc's default highlighting.
LISTINGS_STYLES = {"tech_report"}
# Styles that number headings unless the caller says otherwise.
DEFAULT_NUMBER_SECTIONS = {"academic", "book", "tech_book", "tech_report"}
# Styles that receive a table of contents.
TOC_STYLES = {"tech_report", "book", "tech_book"}
# Fenced-div classes each style can typeset, mapped to its tcolorbox.
BOX_MAPS = {
    "book": "definition:definitionBox,theorem:theoremBox,alert:alertBox,note:alertBox,tip:alertBox",
    "tech_book": "note:techNote,tip:techNote",
    "tech_report": "code:codeBox,tip:tipBox,note:tipBox",
}
# Styles that need the two-column table rewriter (longtable is single-column only).
TWOCOLUMN_STYLES = {"academic"}

TEXT_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".html", ".htm", ".tex"}
CLEAN_SUFFIXES = (
    ".aux", ".log", ".out", ".toc", ".lof", ".lot", ".pdf", ".fls",
    ".fdb_latexmk", ".synctex.gz", ".INCOMPLETE.pdf",
)
RERUN_MARKERS = (
    "Rerun to get cross-references right",
    "Rerun LaTeX",
    "Label(s) may have changed",
    "Package rerunfilecheck Warning",
    "There were undefined references",
)

FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_RE = re.compile(r"[A-Za-z]")
CJK_RATIO_THRESHOLD = 0.20

STYLE_KEYWORDS = {
    "academic": [
        "abstract", "introduction", "reference", "conclusion", "method",
        "doi", "figure", "table",
    ],
    "cv": [
        "education", "experience", "skills", "project", "resume",
        "curriculum vitae", "contact", "email",
    ],
    "tech_report": [
        "code", "python", "java", "function", "api", "install", "usage",
        "guide", "tutorial",
    ],
    "book": ["chapter", "prologue", "once upon a time", "dialogue", "story"],
    "tech_book": ["o'reilly", "technical", "programming", "software", "hardware"],
}


def read_source_text(file_path, limit=None):
    """Return the source as text, or '' when it is unreadable or binary."""
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as handle:
            return handle.read() if limit is None else handle.read(limit)
    except OSError as error:
        print(f"Warning: Could not read file for analysis: {error}")
        return ""


def detect_style(file_path):
    """
    Keyword-based document classifier.

    Words are matched on word boundaries over the first 3000 characters, fenced
    code blocks add a bonus for text-like sources, ties follow
    STYLE_TIE_PRIORITY and an all-zero result falls back to DEFAULT_STYLE.
    """
    content = read_source_text(file_path, limit=3000).lower()
    if not content:
        return DEFAULT_STYLE

    scores = {style: 0 for style in STYLE_KEYWORDS}
    for style, words in STYLE_KEYWORDS.items():
        for word in words:
            scores[style] += len(re.findall(r"\b" + re.escape(word) + r"\b", content))

    if Path(file_path).suffix.lower() in TEXT_SUFFIXES and re.search(r"```|~~~", content):
        scores["tech_report"] += 5
        scores["tech_book"] += 5

    best = max(scores.values())
    if best == 0:
        print(f"Style scores: {scores} -> no signal, using {DEFAULT_STYLE}")
        return DEFAULT_STYLE
    for style in STYLE_TIE_PRIORITY:
        if scores[style] == best:
            print(f"Style scores: {scores} -> {style}")
            return style
    return DEFAULT_STYLE


def frontmatter_lang(text):
    """Return the `lang` value of a leading YAML front matter block, if any."""
    match = re.match(r"---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not match:
        return None
    lang = re.search(r"^lang:\s*[\"']?([A-Za-z][A-Za-z0-9_-]*)", match.group(1), re.M)
    return lang.group(1) if lang else None


def detect_language(text, requested="auto"):
    """
    Return 'zh' or 'en'.

    An explicit request or a `lang` front matter field wins; otherwise the
    ratio of CJK ideographs to Latin letters decides, so English documents that
    quote a few Chinese characters stay English.  Chinese is chosen from 20%
    ideographs upwards, which separates Chinese prose (usually well above 50%)
    from English prose with Chinese terms.  Code is stripped first because code
    samples must not decide the document language.
    """
    if requested in ("zh", "en"):
        return requested
    declared = frontmatter_lang(text)
    if declared:
        return "zh" if declared.lower().startswith("zh") else "en"

    prose = INLINE_CODE_RE.sub(" ", FENCE_RE.sub(" ", text))
    cjk = len(CJK_RE.findall(prose))
    latin = len(LATIN_RE.findall(prose))
    if cjk + latin == 0:
        return "en"
    return "zh" if cjk >= CJK_RATIO_THRESHOLD * (cjk + latin) else "en"


def find_bibliography(input_file):
    """Return the single .bib file next to the source, or None."""
    candidates = sorted(Path(input_file).resolve().parent.glob("*.bib"))
    if len(candidates) == 1:
        print(f"Using bibliography: {candidates[0].name}")
        return candidates[0]
    if len(candidates) > 1:
        print(
            "Warning: several .bib files found next to the source "
            f"({', '.join(p.name for p in candidates)}); pass --bibliography to choose one."
        )
    return None


def build_pandoc_command(
    input_file,
    template_path,
    output_tex,
    style,
    title=None,
    author=None,
    *,
    cjk=False,
    number_sections=False,
    secnumdepth=None,
    linespread=None,
    top_level_division=None,
    bibliography=None,
    csl=None,
):
    """
    Build the Pandoc command line.

    Pandoc runs with the output directory as its working directory, so
    `--extract-media=media` produces relative references that survive moving
    the delivered directory, and `-o` receives the bare file name.
    """
    output_tex = Path(output_tex).resolve()
    command = [
        "pandoc",
        str(Path(input_file).resolve()),
        "-t", "latex",
        "--template", str(template_path),
        "--resource-path", str(Path(input_file).resolve().parent),
        "--extract-media", "media",
        "-o", output_tex.name,
        "-M", f"cjk={'true' if cjk else 'false'}",
    ]

    if title:
        command.extend(["-V", f"title={title}"])
    if author:
        command.extend(["-V", f"author={author}"])
    if style in LISTINGS_STYLES:
        command.append("--listings")
    if style in TOC_STYLES:
        command.extend(["-V", "toc=true"])
    if number_sections:
        command.append("--number-sections")
    if secnumdepth is not None:
        command.extend(["-M", f"secnumdepth={secnumdepth}"])
    if linespread is not None:
        command.extend(["-V", f"linespread={linespread}"])

    division = top_level_division
    if division is None:
        division = "chapter" if style in CHAPTER_STYLES else "auto"
    if division != "auto":
        command.append(f"--top-level-division={division}")

    if bibliography:
        command.extend(["--citeproc", f"--bibliography={bibliography}"])
    if csl:
        command.append(f"--csl={csl}")

    if style in TWOCOLUMN_STYLES:
        filter_path = FILTER_DIR / "twocol_table.lua"
        if filter_path.exists():
            command.extend(["--lua-filter", str(filter_path)])
        else:
            print(f"Warning: {filter_path.name} is missing; two-column tables may fail.")

    boxes = BOX_MAPS.get(style)
    if boxes:
        filter_path = FILTER_DIR / "div_boxes.lua"
        if filter_path.exists():
            command.extend(
                ["--lua-filter", str(filter_path), "-M", f"boxes={boxes}"]
            )
        else:
            print(f"Warning: {filter_path.name} is missing; fenced divs stay plain.")

    return command


def convert_and_compile(
    input_file,
    template_path,
    output_tex,
    style,
    title,
    author,
    **options,
):
    """
    Convert the input document with the given template.

    Note the deliberate asymmetry with compile_tex(): a conversion failure is
    fatal for the process (exit code 1) because nothing downstream can proceed,
    while compile_tex returns False so the caller can report and clean up.
    """
    command = build_pandoc_command(
        input_file, template_path, output_tex, style, title, author, **options
    )
    # Windows needs an explicit UTF-8 environment for console output.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"Running Pandoc conversion with template: {Path(template_path).name}...")
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            env=env,
            cwd=str(Path(output_tex).resolve().parent),
            timeout=PANDOC_TIMEOUT,
        )
        return True
    except subprocess.CalledProcessError as error:
        print("Error running pandoc:")
        print(format_error_output(error))
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"Error: Pandoc conversion timed out after {PANDOC_TIMEOUT} seconds.")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: 'pandoc' not found; conversion was not performed.")
        sys.exit(1)


def format_error_output(error):
    """Return the most useful text a failed subprocess produced."""
    for stream in (error.stderr, error.stdout):
        if stream and stream.strip():
            return stream.strip()[-800:]
    return "(no output captured)"


def clean_previous_outputs(tex_path):
    """
    Remove artifacts of an earlier run for this source.

    A stale PDF or .aux file must never be mistaken for the result of the run
    that is starting now.
    """
    for suffix in CLEAN_SUFFIXES:
        stale = tex_path.parent / (tex_path.stem + suffix)
        try:
            stale.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            print(f"Warning: could not remove stale {stale.name}: {error}")


def needs_rerun(tex_path):
    """Return True when the LaTeX log asks for another pass."""
    log_file = tex_path.with_suffix(".log")
    if not log_file.exists():
        return False
    log_text = log_file.read_text(encoding="utf-8", errors="ignore")
    return any(marker in log_text for marker in RERUN_MARKERS)


def format_latex_error(log_text):
    """
    Return the first LaTeX error with its line context.

    Pandoc's `! ...` header alone ("! Package fontspec Error:") is not
    actionable, so the block is reported together with the offending source
    line, which follows the `l.<number>` marker.  Failures that never produce a
    `! ` line (for example an image the PDF driver cannot decode) are reported
    from their diagnostic lines instead of from the memory statistics.
    """
    lines = log_text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("! ")), None)
    if start is None:
        return "\n".join(diagnostic_lines(lines))
    block = lines[start : start + 14]
    for offset, line in enumerate(block):
        if re.match(r"^l\.\d+", line):
            block = block[: offset + 2]
            break
    return "\n".join(block).strip()


def diagnostic_lines(lines):
    """Return the diagnostic tail of a log that carries no `! ` error line."""
    pattern = re.compile(r"(?i)error|fatal|undefined|cannot|driver return")
    hits = [
        line.strip()
        for line in lines[-60:]
        if pattern.search(line) and "TeX's memory" not in line
    ]
    return hits[-12:] if hits else [line.strip() for line in lines[-20:] if line.strip()]


def quarantine_incomplete_pdf(tex_path):
    """
    Rename a PDF left behind by a failed compile.

    XeLaTeX can write a truncated PDF before it stops, so the file is kept for
    diagnosis under an explicit name instead of being delivered as the result.
    """
    pdf = tex_path.with_suffix(".pdf")
    if not pdf.exists():
        return None
    rejected = tex_path.parent / (tex_path.stem + ".INCOMPLETE.pdf")
    try:
        pdf.replace(rejected)
    except OSError as error:
        print(f"Warning: could not rename the partial PDF {pdf.name}: {error}")
        return None
    print(f"Rejected partial PDF kept for diagnosis: {rejected}")
    return rejected


def compile_tex(tex_file, max_passes=MAX_LATEX_PASSES, timeout=XELATEX_TIMEOUT):
    """
    Compile a .tex file to PDF with XeLaTeX.

    Runs up to `max_passes` times, stopping as soon as the log stops asking for
    another pass, so tables of contents and cross references settle.  Shell
    escape stays disabled and the compile runs inside the output directory so
    Windows path separators are never read as TeX commands.
    """
    tex_path = Path(tex_file).resolve()
    clean_previous_outputs(tex_path)
    command = [
        "xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-no-shell-escape",
        tex_path.name,
    ]
    run_options = {
        "check": True,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "cwd": str(tex_path.parent),
        "timeout": timeout,
    }

    for attempt in range(1, max_passes + 1):
        print(f"Compiling (pass {attempt}/{max_passes}): {' '.join(command)}")
        try:
            subprocess.run(command, **run_options)
        except subprocess.TimeoutExpired:
            print(f"Error: XeLaTeX compilation timed out after {timeout} seconds per pass.")
            quarantine_incomplete_pdf(tex_path)
            return False
        except FileNotFoundError:
            print("Error: 'xelatex' not found; PDF was not compiled.")
            return False
        except subprocess.CalledProcessError as error:
            print("Error: Compilation failed. Please check the .log file.")
            log_file = tex_path.with_suffix(".log")
            if log_file.exists():
                print("\n--- LaTeX Error Detected ---")
                print(format_latex_error(log_file.read_text(encoding="utf-8", errors="ignore")))
            else:
                print("\n--- Command Output ---")
                print(format_error_output(error))
            quarantine_incomplete_pdf(tex_path)
            return False
        if attempt == max_passes or not needs_rerun(tex_path):
            break

    print(f"Compilation successful: {tex_path.with_suffix('.pdf')}")
    return True


def resolve_language(input_file, requested):
    """Return ('zh'|'en', explanation) for the run."""
    text = read_source_text(input_file)
    language = detect_language(text, requested)
    if requested in ("zh", "en"):
        return language, "explicit --lang"
    declared = frontmatter_lang(text)
    if declared:
        return language, f"front matter lang={declared}"
    return language, "detected from the source text"


def main():
    parser = argparse.ArgumentParser(description="Smart Doc-to-LaTeX Native Engine")
    parser.add_argument("--input", required=True, help="Input file path (.md, .docx, .txt)")
    parser.add_argument(
        "--style",
        default="auto",
        choices=["auto", "academic", "cv", "tech_report", "book", "tech_book"],
        help="Target document style",
    )
    parser.add_argument("--title", help="Document title override")
    parser.add_argument("--author", help="Document author override")
    parser.add_argument("--output", help="Output directory (default: input file's directory)")
    parser.add_argument(
        "--lang",
        default="auto",
        choices=["auto", "zh", "en"],
        help="Language routing for spacing, leading and labels (default: detect)",
    )
    parser.add_argument(
        "--linespread",
        type=float,
        help="Explicit leading override; overrides the language-routed default",
    )
    parser.add_argument("--secnumdepth", type=int, help="Heading depth to number")
    numbering = parser.add_mutually_exclusive_group()
    numbering.add_argument(
        "--number-sections", dest="number_sections", action="store_true", default=None,
        help="Number headings (default: on for academic/tech_report/book/tech_book)",
    )
    numbering.add_argument(
        "--no-number-sections", dest="number_sections", action="store_false",
        help="Leave headings unnumbered",
    )
    parser.add_argument(
        "--top-level-division",
        default="auto",
        choices=["auto", "section", "chapter", "part"],
        help="Heading level used for the top-level Markdown heading",
    )
    parser.add_argument("--bibliography", help="BibTeX/BibLaTeX file; enables --citeproc")
    parser.add_argument("--csl", help="CSL style file for citations")

    args = parser.parse_args()

    # 1. Validation
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file '{args.input}' not found.")
        sys.exit(1)

    # 2. Style detection
    style = args.style
    if style == "auto":
        print("Analyzing document structure...")
        style = detect_style(args.input)
        print(f"Detected Style: {style.upper()}")

    # 3. Load template
    template_path = TEMPLATE_DIR / f"{style}.tex"
    if not template_path.exists():
        print(f"Error: Template for '{style}' not found at {template_path}")
        sys.exit(1)

    # 4. Language routing and metadata (only explicit CLI overrides win)
    language, reason = resolve_language(args.input, args.lang)
    cjk = language == "zh"
    number_sections = (
        style in DEFAULT_NUMBER_SECTIONS
        if args.number_sections is None
        else args.number_sections
    )
    bibliography = args.bibliography or find_bibliography(args.input)

    # 5. Output location
    output_dir = Path(args.output) if args.output else input_path.resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_tex = output_dir / f"{input_path.stem}_{style}.tex"

    print(
        f"Language routing: {'Chinese' if cjk else 'English'} ({reason}); "
        f"heading numbering: {'on' if number_sections else 'off'}"
    )

    # 6. Convert with the native Pandoc template engine
    convert_and_compile(
        args.input,
        template_path,
        output_tex,
        style,
        args.title,
        args.author,
        cjk=cjk,
        number_sections=number_sections,
        secnumdepth=args.secnumdepth,
        linespread=args.linespread,
        top_level_division=None if args.top_level_division == "auto" else args.top_level_division,
        bibliography=bibliography,
        csl=args.csl,
    )
    print(f"Generated source: {output_tex}")

    # 7. Compile to PDF
    if not compile_tex(output_tex):
        sys.exit(1)

    print(f"Delivered: {output_tex.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
