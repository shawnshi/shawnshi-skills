"""Read-only-by-default orchestration for the document summarizer."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def run(script, *arguments):
    command = [sys.executable, str(SCRIPT_DIR / script), *map(str, arguments)]
    result = subprocess.run(command, check=False)
    if result.returncode:
        print(
            f"ERROR[stage]: {script} exited with {result.returncode}; "
            "the pipeline stopped without retrying",
            file=sys.stderr,
        )
    return result.returncode


def add_external_flags(command, allowed, external_max_chars):
    if not allowed:
        return command
    return [
        *command,
        "--allow-external-model",
        "--external-max-chars",
        external_max_chars,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Document summarizer pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract")
    extract.add_argument("--dir", required=True, type=Path)
    extract.add_argument("--output-dir", required=True, type=Path)
    extract.add_argument("--workers", type=int, default=4)

    generate = commands.add_parser("generate")
    generate.add_argument("--input", required=True, type=Path)
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--max-chars", required=True, type=int)
    generate.add_argument("--allow-external-model", action="store_true")
    generate.add_argument("--external-max-chars", type=int)

    scan = commands.add_parser("scan-terms")
    scan.add_argument("--input", required=True, type=Path)
    scan.add_argument("--output", required=True, type=Path)

    inventory = commands.add_parser("inventory")
    inventory.add_argument("--input", required=True, type=Path)
    inventory.add_argument("--output", required=True, type=Path)

    all_cmd = commands.add_parser(
        "all", help="extract, summarize, locate terms and build an inventory; no source write-back"
    )
    all_cmd.add_argument("--dir", required=True, type=Path)
    all_cmd.add_argument("--output-dir", required=True, type=Path)
    all_cmd.add_argument("--workers", type=int, default=4)
    all_cmd.add_argument("--max-chars", required=True, type=int)
    all_cmd.add_argument("--allow-external-model", action="store_true")
    all_cmd.add_argument("--external-max-chars", type=int)

    apply_cmd = commands.add_parser("apply", help="preview or explicitly apply metadata")
    apply_cmd.add_argument("--summaries", required=True, type=Path)
    apply_cmd.add_argument("--mapping", required=True, type=Path)
    apply_cmd.add_argument("--backup-dir", type=Path)
    apply_cmd.add_argument("--apply", action="store_true")
    apply_cmd.add_argument("--overwrite-existing", action="store_true")

    clean = commands.add_parser("clean")
    clean.add_argument("--output-dir", required=True, type=Path)
    clean.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    if args.command in {"generate", "all"}:
        if args.max_chars <= 0:
            print("ERROR[argument]: --max-chars must be positive", file=sys.stderr)
            return 2
        if args.allow_external_model and (
            args.external_max_chars is None or args.external_max_chars <= 0
        ):
            print(
                "ERROR[authorization]: --allow-external-model requires a positive "
                "--external-max-chars data boundary",
                file=sys.stderr,
            )
            return 2
        if args.external_max_chars is not None and not args.allow_external_model:
            print(
                "ERROR[argument]: --external-max-chars requires --allow-external-model",
                file=sys.stderr,
            )
            return 2

    if args.command == "extract":
        args.output_dir.mkdir(parents=True, exist_ok=True)
        return run(
            "extract_text.py",
            "--dir", args.dir,
            "--workers", args.workers,
            "--output", args.output_dir / "extracted_content.json",
            "--mapping", args.output_dir / "file_id_mapping.json",
        )
    if args.command == "generate":
        return run(
            "generate_summaries_enhanced.py",
            *add_external_flags(
                [
                    "--input",
                    args.input,
                    "--output",
                    args.output,
                    "--max-chars",
                    args.max_chars,
                ],
                args.allow_external_model,
                args.external_max_chars,
            ),
        )
    if args.command == "scan-terms":
        return run("medical_standard_checker.py", "--input", args.input, "--output", args.output)
    if args.command == "inventory":
        return run("portfolio_audit.py", "--input", args.input, "--output", args.output)
    if args.command == "apply":
        if args.apply and not args.backup_dir:
            print("ERROR[authorization]: --apply requires --backup-dir", file=sys.stderr)
            return 2
        command = ["--summaries", args.summaries, "--mapping", args.mapping]
        if args.backup_dir:
            command += ["--backup-dir", args.backup_dir]
        if args.apply:
            command.append("--apply")
        if args.overwrite_existing:
            command.append("--overwrite-existing")
        return run("apply_metadata_enhanced.py", *command)
    if args.command == "clean":
        candidates = [
            path
            for name in (
                "extracted_content.json",
                "file_id_mapping.json",
                "document_summaries.json",
                "term_locations.json",
                "portfolio_inventory.json",
            )
            if (path := args.output_dir / name).is_file()
        ]
        for path in candidates:
            print(path.resolve())
        if args.apply:
            for path in candidates:
                path.unlink()
        else:
            print("PREVIEW_ONLY: add --apply to delete the listed generated files")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    extracted = args.output_dir / "extracted_content.json"
    mapping = args.output_dir / "file_id_mapping.json"
    summaries = args.output_dir / "document_summaries.json"
    terms = args.output_dir / "term_locations.json"
    portfolio = args.output_dir / "portfolio_inventory.json"
    stages = [
        ("extract_text.py", ["--dir", args.dir, "--workers", args.workers, "--output", extracted, "--mapping", mapping]),
        (
            "generate_summaries_enhanced.py",
            add_external_flags(
                [
                    "--input",
                    extracted,
                    "--output",
                    summaries,
                    "--max-chars",
                    args.max_chars,
                ],
                args.allow_external_model,
                args.external_max_chars,
            ),
        ),
        ("medical_standard_checker.py", ["--input", extracted, "--output", terms]),
        ("portfolio_audit.py", ["--input", summaries, "--output", portfolio]),
    ]
    for script, arguments in stages:
        status = run(script, *arguments)
        if status:
            return status
    print("PIPELINE_PASS: source documents were not modified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
