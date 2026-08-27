import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "resources" / "template.md"
MODES = ("quick", "standard", "deep")
MIN_TEMPLATE_PLACEHOLDERS = 3

PLACEHOLDER_TOKEN_RE = re.compile(r"\{[^{}]{1,500}\}", re.DOTALL)
GENERIC_PLACEHOLDER_HINT_RE = re.compile(
    r"请[^{}\n]{0,20}(?:填写|补充|替换|输入)|待(?:填写|补充|完善|完成)|"
    r"(?:论文)?标题|作者列表|发表场所|唯一标识|实际分析版本|"
    r"关键主张|来源定位|支撑内容|判断与置信度|最可靠的结论"
)
UNFINISHED_RE = re.compile(
    r"(?i)(?<![\w-])(?:TODO|TBD|FIXME)(?![\w-])|"
    r"待填写|待补充|待完善|待完成"
)
EVIDENCE_INDEX_HEADING_RE = re.compile(
    r"(?im)^[ \t]{0,3}#{1,6}[ \t]*"
    r"(?:\d+(?:\.\d+)*[.)、]?[ \t]*)?"
    r"(?:证据索引|Evidence[ \t]+Index)(?:[ \t:：(（]|$)"
)
SOURCE_SCOPE_LABEL_RE = re.compile(
    r"(?im)^[ \t]*(?:[-*>][ \t]*)?(?:\*\*|__)?"
    r"(?:来源范围|溯源范围|联网范围|检索范围|"
    r"Source[ \t]+Scope|Traceback[ \t]+Scope|Evidence[ \t]+Scope)"
    r"(?:\*\*|__)?[ \t]*[:：][ \t]*\S+"
)
SOURCE_SCOPE_HEADING_RE = re.compile(
    r"(?im)^[ \t]{0,3}#{1,6}[ \t]*"
    r"(?:来源范围|溯源范围|联网范围|检索范围|"
    r"Source[ \t]+Scope|Traceback[ \t]+Scope|Evidence[ \t]+Scope)"
    r"[ \t]*$"
)
NO_NETWORK_RE = re.compile(
    r"(?i)未(?:进行|使用)?联网|没有联网|无联网|"
    r"未(?:检索|查询|访问)(?:外部|网络|在线)?(?:资料|来源|资源|信息)?|"
    r"not[ \t]+(?:connected[ \t]+to|using|searched?)[ \t]+(?:the[ \t]+)?(?:web|internet)|"
    r"offline[ \t]+only"
)


class TemplateError(RuntimeError):
    """The audit template cannot safely define its placeholders."""


def _remove_format_characters(text: str) -> str:
    return "".join(char for char in text if unicodedata.category(char) != "Cf")


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _is_effectively_empty(text: str) -> bool:
    visible = _remove_format_characters(_strip_html_comments(text))
    return not visible.strip()


def _strip_fenced_code(text: str) -> str:
    """Remove Markdown fenced blocks while preserving non-code line boundaries."""
    result: list[str] = []
    fence_char: str | None = None
    fence_length = 0

    for line in text.splitlines(keepends=True):
        marker = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if fence_char is None:
            if marker:
                fence_char = marker.group(1)[0]
                fence_length = len(marker.group(1))
                result.append("\n" if line.endswith(("\n", "\r")) else "")
            else:
                result.append(line)
            continue

        closing = re.match(
            rf"^[ \t]{{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*(?:\r?\n)?$",
            line,
        )
        result.append("\n" if line.endswith(("\n", "\r")) else "")
        if closing:
            fence_char = None
            fence_length = 0

    return "".join(result)


def _strip_inline_code(text: str) -> str:
    """Remove CommonMark-style backtick spans, including spans with inner ticks."""
    output: list[str] = []
    cursor = 0
    length = len(text)

    while cursor < length:
        if text[cursor] != "`":
            output.append(text[cursor])
            cursor += 1
            continue

        run_end = cursor
        while run_end < length and text[run_end] == "`":
            run_end += 1
        marker = text[cursor:run_end]
        closing = -1
        search_at = run_end
        while search_at < length:
            candidate = text.find("`", search_at)
            if candidate < 0:
                break
            candidate_end = candidate
            while candidate_end < length and text[candidate_end] == "`":
                candidate_end += 1
            if candidate_end - candidate == len(marker):
                closing = candidate
                break
            search_at = candidate_end
        if closing < 0:
            output.append(marker)
            cursor = run_end
            continue

        removed = text[cursor : closing + len(marker)]
        output.append("".join("\n" if char == "\n" else " " for char in removed))
        cursor = closing + len(marker)

    return "".join(output)


def _prose_for_audit(text: str) -> str:
    without_comments = _strip_html_comments(text)
    without_fences = _strip_fenced_code(without_comments)
    return _strip_inline_code(without_fences)


def _normalize_placeholder(token: str) -> str:
    normalized = unicodedata.normalize("NFKC", _remove_format_characters(token))
    return re.sub(r"\s+", "", normalized).casefold()


def _load_template_placeholders(template_path: Path | None = None) -> set[str]:
    path = Path(template_path) if template_path is not None else TEMPLATE_PATH
    try:
        template = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TemplateError(f"audit template is missing: {path}") from exc
    except UnicodeError as exc:
        raise TemplateError(f"audit template is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise TemplateError(f"unable to read audit template: {path}: {exc}") from exc

    if _is_effectively_empty(template):
        raise TemplateError(f"audit template is empty or contains no visible content: {path}")

    placeholders = {
        _normalize_placeholder(match.group(0))
        for match in PLACEHOLDER_TOKEN_RE.finditer(template)
    }
    if len(placeholders) < MIN_TEMPLATE_PLACEHOLDERS:
        raise TemplateError(
            "audit template is damaged or contains too few recognizable placeholders: "
            f"{path} (found {len(placeholders)}, need at least "
            f"{MIN_TEMPLATE_PLACEHOLDERS})"
        )
    return placeholders


def known_template_placeholders(template_path: Path | None = None) -> set[str]:
    """Return normalized placeholders, raising when the template is unusable."""
    return _load_template_placeholders(template_path)


def _source_scope_declared(prose: str) -> bool:
    if SOURCE_SCOPE_LABEL_RE.search(prose) or NO_NETWORK_RE.search(prose):
        return True

    heading = SOURCE_SCOPE_HEADING_RE.search(prose)
    if not heading:
        return False
    remainder = prose[heading.end() :]
    next_heading = re.search(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+", remainder)
    section_body = remainder[: next_heading.start()] if next_heading else remainder
    return bool(section_body.strip())


def validate_paper_draft(
    content: str,
    mode: str = "quick",
    template_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Return deterministic errors and low-noise, non-blocking warnings."""
    if mode not in MODES:
        raise ValueError(f"unsupported audit mode: {mode}")

    errors: list[str] = []
    warnings: list[str] = []

    try:
        template_placeholders = _load_template_placeholders(template_path)
    except TemplateError as exc:
        errors.append(str(exc))
        return errors, warnings

    if _is_effectively_empty(content):
        errors.append("draft is empty")
        return errors, warnings

    prose = _prose_for_audit(content)
    placeholder_hits = sorted(
        {
            match.group(0).strip()
            for match in PLACEHOLDER_TOKEN_RE.finditer(prose)
            if _normalize_placeholder(match.group(0)) in template_placeholders
            or GENERIC_PLACEHOLDER_HINT_RE.search(match.group(0))
        }
    )
    if placeholder_hits:
        preview = ", ".join(hit[:80] for hit in placeholder_hits[:5])
        errors.append(f"unresolved template placeholders: {preview}")

    unfinished_hits = sorted({match.group(0) for match in UNFINISHED_RE.finditer(prose)})
    if unfinished_hits:
        errors.append(f"unfinished markers: {', '.join(unfinished_hits[:8])}")

    if mode in ("standard", "deep") and not EVIDENCE_INDEX_HEADING_RE.search(prose):
        errors.append(f"{mode} mode requires an evidence index section")

    if mode == "deep" and not _source_scope_declared(prose):
        errors.append(
            "deep mode requires a source-scope or traceback-scope declaration "
            "(an explicit no-network statement is allowed)"
        )

    if re.search(r"\$\$.+?\$\$", prose, re.DOTALL):
        warnings.append(
            "block LaTeX found; explain symbols and intuition when the audience needs it"
        )

    return errors, warnings


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except OSError:
        return first.resolve(strict=False) == second.resolve(strict=False)


def audit_file(
    output_path: Path,
    *,
    mode: str = "quick",
    source_path: Path | None = None,
    source_sha256: str | None = None,
    expected_output_dir: Path | None = None,
    template_path: Path | None = None,
) -> dict[str, Any]:
    """Audit an output and return a JSON-serializable result."""
    output_path = Path(output_path)
    source_path = Path(source_path) if source_path is not None else None
    expected_output_dir = (
        Path(expected_output_dir) if expected_output_dir is not None else None
    )
    result: dict[str, Any] = {
        "ok": False,
        "mode": mode,
        "output_path": str(output_path),
        "source_path": str(source_path) if source_path is not None else None,
        "expected_output_dir": (
            str(expected_output_dir) if expected_output_dir is not None else None
        ),
        "errors": [],
        "warnings": [],
        "hashes": {"algorithm": "sha256", "output": None, "source": None},
    }
    errors: list[str] = result["errors"]

    source_before: str | None = None
    if source_sha256 is not None and source_path is None:
        errors.append("--source-sha256 requires --source-path")
    if source_path is not None and source_sha256 is None:
        errors.append(
            "--source-path requires --source-sha256 recorded before analysis"
        )

    if source_path is not None:
        source_evidence = {
            "expected": source_sha256,
            "before": None,
            "after": None,
            "unchanged": None,
            "matches_expected": None,
        }
        result["hashes"]["source"] = source_evidence
        if not source_path.is_file():
            errors.append(f"source file not found: {source_path}")
        else:
            try:
                source_before = _sha256_file(source_path)
                source_evidence["before"] = source_before
                if source_sha256 is not None:
                    matches = source_before == source_sha256.lower()
                    source_evidence["matches_expected"] = matches
                    if not matches:
                        errors.append(
                            "source SHA-256 mismatch: "
                            f"expected {source_sha256.lower()}, got {source_before}"
                        )
            except OSError as exc:
                errors.append(f"unable to hash source file: {source_path}: {exc}")

    if not output_path.is_file():
        errors.append(f"output file not found: {output_path}")
    else:
        if source_path is not None and _same_path(output_path, source_path):
            errors.append("output file must not be the source file")

        if expected_output_dir is not None:
            if not expected_output_dir.is_dir():
                errors.append(f"expected output directory not found: {expected_output_dir}")
            elif output_path.parent.resolve(strict=False) != expected_output_dir.resolve(
                strict=False
            ):
                errors.append(
                    "output directory mismatch: "
                    f"expected {expected_output_dir.resolve(strict=False)}, "
                    f"got {output_path.parent.resolve(strict=False)}"
                )

        try:
            output_digest = _sha256_file(output_path)
            result["hashes"]["output"] = {"sha256": output_digest}
            if source_before is not None and output_digest == source_before:
                errors.append("output content must not be identical to source content")
        except OSError as exc:
            errors.append(f"unable to hash output file: {output_path}: {exc}")

        try:
            content = output_path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            errors.append(f"output is not valid UTF-8: {output_path}: {exc}")
        except OSError as exc:
            errors.append(f"unable to read UTF-8 output: {output_path}: {exc}")
        else:
            draft_errors, warnings = validate_paper_draft(
                content, mode=mode, template_path=template_path
            )
            errors.extend(draft_errors)
            result["warnings"].extend(warnings)

    if source_path is not None and source_before is not None:
        source_evidence = result["hashes"]["source"]
        try:
            source_after = _sha256_file(source_path)
            source_evidence["after"] = source_after
            source_evidence["unchanged"] = source_before == source_after
            if source_before != source_after:
                errors.append(
                    "source file changed during audit: "
                    f"before {source_before}, after {source_after}"
                )
        except OSError as exc:
            errors.append(f"unable to re-hash source file: {source_path}: {exc}")

    result["ok"] = not errors
    return result


def _sha256_argument(value: str) -> str:
    normalized = value.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise argparse.ArgumentTypeError("must be exactly 64 hexadecimal characters")
    return normalized


def _safe_text(message: str, stream: Any) -> None:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    safe = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe, file=stream)


def _emit_text_result(result: dict[str, Any]) -> None:
    for warning in result["warnings"]:
        _safe_text(f"[WARN] {warning}", sys.stderr)

    hashes = result["hashes"]
    output_hash = hashes.get("output")
    if output_hash:
        _safe_text(f"[HASH] output sha256={output_hash['sha256']}", sys.stdout)
    source_hash = hashes.get("source")
    if source_hash:
        fields = [
            f"before={source_hash.get('before')}",
            f"after={source_hash.get('after')}",
            f"unchanged={str(source_hash.get('unchanged')).lower()}",
        ]
        if source_hash.get("expected") is not None:
            fields.append(f"expected={source_hash['expected']}")
            fields.append(
                f"matches_expected={str(source_hash.get('matches_expected')).lower()}"
            )
        _safe_text(f"[HASH] source sha256 {' '.join(fields)}", sys.stdout)

    if result["errors"]:
        _safe_text("[FAIL] deterministic audit errors:", sys.stderr)
        for error in result["errors"]:
            _safe_text(f"- {error}", sys.stderr)
        return

    _safe_text(
        f"[PASS] audit completed with {len(result['warnings'])} warning(s)", sys.stdout
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Academic Paper Reader outputs. Deterministic integrity and "
            "completion errors block delivery."
        )
    )
    parser.add_argument("file_path", help="Path to the Markdown output to audit.")
    parser.add_argument("--mode", choices=MODES, default="quick")
    parser.add_argument("--source-path", help="Path to the original source document.")
    parser.add_argument(
        "--source-sha256",
        type=_sha256_argument,
        help="Expected pre-audit SHA-256 of the source document.",
    )
    parser.add_argument(
        "--expected-output-dir",
        help="Directory in which the audited output must reside.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit one structured JSON result."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = audit_file(
        Path(args.file_path),
        mode=args.mode,
        source_path=Path(args.source_path) if args.source_path else None,
        source_sha256=args.source_sha256,
        expected_output_dir=(
            Path(args.expected_output_dir) if args.expected_output_dir else None
        ),
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        _emit_text_result(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
