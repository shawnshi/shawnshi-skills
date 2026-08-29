#!/usr/bin/env python3
"""Build a validated, model-neutral flat-design image prompt.

The script intentionally uses observable visual features rather than creator,
brand, or existing-work style anchors. It depends only on the Python standard
library and can emit human-readable text or structured JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Iterable, Optional


SCHEMA_VERSION = 1

CARRIERS = {
    "generic": {
        "zh": "通用平面视觉",
        "en": "generic flat graphic",
        "ratio": "1:1",
        "safe_zh": "关键主体距离四周边缘至少5%，保持稳定留白",
        "safe_en": "keep key content at least 5% away from every edge",
    },
    "article-hero": {
        "zh": "文章头图",
        "en": "article hero image",
        "ratio": "16:9",
        "safe_zh": "主体集中在一侧约60%，另一侧约35%保持低细节标题安全区",
        "safe_en": "place the subject on roughly 60% of one side and keep about 35% low-detail title-safe space on the other",
    },
    "social-cover": {
        "zh": "社交媒体封面",
        "en": "social media cover",
        "ratio": "4:5",
        "safe_zh": "四周保留至少8%安全边距，缩略图下保持单一焦点",
        "safe_en": "keep at least 8% safe margin on every edge and preserve one focal point at thumbnail size",
    },
    "poster": {
        "zh": "竖版海报",
        "en": "portrait poster",
        "ratio": "2:3",
        "safe_zh": "主视觉远看可识别，并为信息层级保留连续区域",
        "safe_en": "make the main visual readable at distance and reserve a continuous area for information hierarchy",
    },
    "book-cover": {
        "zh": "书籍封面底图",
        "en": "book-cover artwork",
        "ratio": "2:3",
        "safe_zh": "标题区与作者区分离，关键图形在缩略图下仍可识别",
        "safe_en": "separate title and author zones and keep the key symbol readable at thumbnail size",
    },
    "album-cover": {
        "zh": "专辑封面",
        "en": "album cover",
        "ratio": "1:1",
        "safe_zh": "核心符号在小尺寸下仍清晰，四周保留呼吸空间",
        "safe_en": "keep the core symbol clear at small size with breathing room around the edges",
    },
    "presentation-cover": {
        "zh": "演示封面",
        "en": "presentation cover",
        "ratio": "16:9",
        "safe_zh": "为标题、副标题和署名保留稳定的低细节区域",
        "safe_en": "reserve a stable low-detail area for title, subtitle, and attribution",
    },
    "event-banner": {
        "zh": "活动横幅",
        "en": "event banner",
        "ratio": "16:9",
        "safe_zh": "主视觉和信息区分离，关键元素避开响应式裁切边缘",
        "safe_en": "separate the hero visual from the information zone and keep key elements away from responsive crop edges",
    },
}

VISUAL_LANGUAGES = {
    "geometric-minimal": {
        "zh": "几何极简、单一焦点、2至3色、硬边色块、大面积留白和克制层级",
        "en": "geometric minimalism, one focal point, two or three colors, hard-edged shapes, generous negative space, restrained hierarchy",
    },
    "negative-space": {
        "zh": "图底反转、隐藏轮廓、视觉双关、双色调和轮廓优先",
        "en": "figure-ground inversion, hidden contour, visual double meaning, duotone palette, silhouette-first design",
    },
    "editorial-flat": {
        "zh": "编辑式平面插画、非对称网格、统一细线、受控色块和明确标题区",
        "en": "editorial flat illustration, asymmetric grid, consistent fine lines, controlled color blocks, explicit title zone",
    },
    "atmospheric-print": {
        "zh": "单一象征物、柔和背景层、纸张颗粒、半色调和轻微套色偏移",
        "en": "one symbolic object, soft background layers, paper grain, halftone texture, slight color-register offset",
    },
    "technical-line": {
        "zh": "精密线条、模块结构、有限高亮色和清晰连接关系，但不伪装成精确技术图",
        "en": "precise linework, modular structure, limited accent color, clear connections, without pretending to be an exact technical diagram",
    },
    "typographic": {
        "zh": "文字承担主要构图、强层级、大字号、清晰对齐和充足留白",
        "en": "type-led composition, strong hierarchy, large scale, clear alignment, ample whitespace",
    },
    "pattern-led": {
        "zh": "原创重复图案、节奏变化、局部破格和有限色板",
        "en": "original repeating pattern, rhythmic variation, one controlled disruption, limited palette",
    },
    "collage": {
        "zh": "剪纸或版画式拼贴、明确前后层、受控元素数量和原创素材",
        "en": "paper-cut or print-like collage, clear foreground and background, controlled element count, original source material",
    },
}

DEFAULT_VISUAL_LANGUAGE = {
    "generic": "geometric-minimal",
    "article-hero": "editorial-flat",
    "social-cover": "editorial-flat",
    "poster": "negative-space",
    "book-cover": "negative-space",
    "album-cover": "geometric-minimal",
    "presentation-cover": "editorial-flat",
    "event-banner": "geometric-minimal",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a validated, original flat-design image prompt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 generate_prompt.py 'data governance before AI' --carrier article-hero --aspect-ratio 16:9\n"
            "  python3 generate_prompt.py 'fictional coastal novel' --carrier book-cover --text '海岸以北' --text-strategy post-layout\n"
            "  python3 generate_prompt.py --list-visual-languages\n"
        ),
    )
    parser.add_argument("subject", nargs="?", help="Theme or subject of the visual")
    parser.add_argument("--carrier", choices=sorted(CARRIERS), default="generic")
    parser.add_argument("--aspect-ratio", "--ratio", type=parse_aspect_ratio)
    parser.add_argument(
        "--orientation",
        choices=["auto", "landscape", "portrait", "square"],
        default="auto",
        help="Validate the requested orientation against the aspect ratio",
    )
    parser.add_argument(
        "--visual-language",
        choices=["auto", *sorted(VISUAL_LANGUAGES)],
        default="auto",
    )
    parser.add_argument("--focus", default="", help="Core focal symbol or visual metaphor")
    parser.add_argument("--palette", default="", help="Color palette or exact provided brand colors")
    parser.add_argument("--audience", default="")
    parser.add_argument("--mood", default="")
    parser.add_argument("--safe-area", default="")
    parser.add_argument(
        "--must-include",
        action="append",
        default=[],
        help="Required element; repeat the option or use comma/semicolon separated values",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Forbidden element; repeat the option or use comma/semicolon separated values",
    )
    parser.add_argument("--text", default="", help="Exact layout copy, if any")
    parser.add_argument(
        "--text-strategy",
        choices=["auto", "no-text", "short-text", "post-layout"],
        default="auto",
    )
    parser.add_argument("--prompt-language", choices=["zh", "en"], default="zh")
    parser.add_argument("--output-format", choices=["text", "json"], default="text")
    parser.add_argument("--list-visual-languages", action="store_true")
    parser.add_argument("--list-carriers", action="store_true")
    return parser


def parse_aspect_ratio(raw: str) -> str:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*", raw)
    if not match:
        raise argparse.ArgumentTypeError("aspect ratio must use positive W:H numbers, for example 16:9")
    width, height = (float(value) for value in match.groups())
    if width <= 0 or height <= 0 or width > 100 or height > 100:
        raise argparse.ArgumentTypeError("aspect ratio values must be greater than 0 and no greater than 100")
    return f"{format_number(width)}:{format_number(height)}"


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def get_orientation(ratio: str) -> str:
    width_raw, height_raw = ratio.split(":", 1)
    width, height = float(width_raw), float(height_raw)
    if abs(width - height) < 1e-9:
        return "square"
    return "landscape" if width > height else "portrait"


def split_items(values: Iterable[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for item in re.split(r"[,;，；]", value):
            cleaned = item.strip()
            if cleaned and cleaned not in items:
                items.append(cleaned)
    return items


def resolve_text_strategy(strategy: str, text_value: str) -> str:
    if strategy == "auto":
        return "post-layout" if text_value else "no-text"
    return strategy


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> dict:
    if not args.subject or not args.subject.strip():
        parser.error("subject is required unless a list option is used")
    if len(args.subject) > 2000:
        parser.error("subject must not exceed 2000 characters")

    carrier = CARRIERS[args.carrier]
    ratio = args.aspect_ratio or carrier["ratio"]
    actual_orientation = get_orientation(ratio)
    if args.orientation != "auto" and args.orientation != actual_orientation:
        parser.error(
            f"orientation '{args.orientation}' conflicts with aspect ratio {ratio} "
            f"({actual_orientation})"
        )

    must_include = split_items(args.must_include)
    excludes = split_items(args.exclude)
    excluded_keys = {item.casefold() for item in excludes}
    overlaps = [item for item in must_include if item.casefold() in excluded_keys]
    if overlaps:
        parser.error("the same item cannot be both required and excluded: " + ", ".join(overlaps))

    text_value = args.text.strip()
    text_strategy = resolve_text_strategy(args.text_strategy, text_value)
    if text_strategy == "no-text" and text_value:
        parser.error("--text conflicts with --text-strategy no-text; use post-layout or short-text")
    if text_strategy == "short-text" and not text_value:
        parser.error("--text-strategy short-text requires --text")

    visual_language = (
        DEFAULT_VISUAL_LANGUAGE[args.carrier]
        if args.visual_language == "auto"
        else args.visual_language
    )
    safe_area = args.safe_area.strip() or carrier[f"safe_{args.prompt_language}"]

    warnings: list[str] = []
    if args.aspect_ratio and args.aspect_ratio != carrier["ratio"]:
        warnings.append(
            f"User ratio {args.aspect_ratio} overrides the {args.carrier} working default {carrier['ratio']}."
        )
    if text_strategy == "short-text":
        warnings.append("Generated text must be checked character by character; use post-layout if accuracy is critical.")

    return {
        "ratio": ratio,
        "orientation": actual_orientation,
        "must_include": must_include,
        "excludes": excludes,
        "text": text_value,
        "text_strategy": text_strategy,
        "visual_language": visual_language,
        "safe_area": safe_area,
        "warnings": warnings,
    }


def build_prompt(args: argparse.Namespace, resolved: dict) -> dict:
    language = args.prompt_language
    carrier = CARRIERS[args.carrier]
    visual = VISUAL_LANGUAGES[resolved["visual_language"]][language]

    if language == "zh":
        positive_parts = [
            f"{resolved['ratio']}画幅的{carrier['zh']}，主题：{args.subject.strip()}",
            f"核心视觉焦点：{args.focus.strip() or '围绕主题建立一个原创、清晰、可识别的象征或视觉隐喻'}",
            f"视觉语言：{visual}",
            f"色板：{args.palette.strip() or '2至4个服务主题的有限色彩，使用单一强调色建立层级'}",
        ]
        if args.audience.strip():
            positive_parts.append(f"受众：{args.audience.strip()}")
        if args.mood.strip():
            positive_parts.append(f"情绪：{args.mood.strip()}")
        if resolved["must_include"]:
            positive_parts.append("必须出现：" + "、".join(resolved["must_include"]))
        positive_parts.append(text_clause_zh(resolved["text_strategy"], resolved["text"]))
        positive_parts.append("安全区：" + resolved["safe_area"])
        positive_parts.append("原创构图，不复刻现有作品、角色标识、标题字标或品牌视觉")

        negatives = [
            "写实摄影",
            "复杂三维渲染",
            "无关物体",
            "拥挤构图",
            "伪文字和乱码",
            "水印",
            "未经提供的品牌标识",
            "复制现有作品构图或角色标识",
        ]
        if resolved["text_strategy"] in {"no-text", "post-layout"}:
            negatives.append("任何可见文字、字母和数字")
        elif resolved["text_strategy"] == "short-text":
            negatives.append("除指定短标题外的任何文字")
        negatives.extend(resolved["excludes"])
        positive_prompt = "；".join(positive_parts) + "。"
        negative_prompt = "、".join(dedupe(negatives)) + "。"
    else:
        positive_parts = [
            f"{resolved['ratio']} {carrier['en']}; subject: {args.subject.strip()}",
            f"core focal idea: {args.focus.strip() or 'one original, clear, recognizable symbol or visual metaphor derived from the subject'}",
            f"visual language: {visual}",
            f"palette: {args.palette.strip() or 'a limited palette of two to four theme-relevant colors with one accent color for hierarchy'}",
        ]
        if args.audience.strip():
            positive_parts.append(f"audience: {args.audience.strip()}")
        if args.mood.strip():
            positive_parts.append(f"mood: {args.mood.strip()}")
        if resolved["must_include"]:
            positive_parts.append("must include: " + ", ".join(resolved["must_include"]))
        positive_parts.append(text_clause_en(resolved["text_strategy"], resolved["text"]))
        positive_parts.append("safe area: " + resolved["safe_area"])
        positive_parts.append("original composition; do not reproduce an existing artwork, character mark, title treatment, or brand identity")

        negatives = [
            "photorealistic stock imagery",
            "complex 3D rendering",
            "irrelevant objects",
            "crowded composition",
            "pseudo-text or gibberish",
            "watermark",
            "brand mark not supplied by the user",
            "copied composition or character mark",
        ]
        if resolved["text_strategy"] in {"no-text", "post-layout"}:
            negatives.append("any visible text, letters, or numbers")
        elif resolved["text_strategy"] == "short-text":
            negatives.append("any text other than the specified short title")
        negatives.extend(resolved["excludes"])
        positive_prompt = "; ".join(positive_parts) + "."
        negative_prompt = ", ".join(dedupe(negatives)) + "."

    return {
        "schema_version": SCHEMA_VERSION,
        "carrier": args.carrier,
        "aspect_ratio": resolved["ratio"],
        "orientation": resolved["orientation"],
        "visual_language": resolved["visual_language"],
        "text_strategy": resolved["text_strategy"],
        "layout_text": resolved["text"],
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "warnings": resolved["warnings"],
    }


def text_clause_zh(strategy: str, text_value: str) -> str:
    if strategy == "no-text":
        return "图中不生成文字、字母、数字、Logo或水印"
    if strategy == "short-text":
        return f"仅尝试排唯一短标题“{text_value}”，使用原创清晰字形，不增加其他文字"
    if text_value:
        return f"生成无字底图，为后期准确排入“{text_value}”预留连续低细节区域"
    return "生成无字底图，为后期标题排版预留连续低细节区域"


def text_clause_en(strategy: str, text_value: str) -> str:
    if strategy == "no-text":
        return "render no text, letters, numbers, logos, or watermarks"
    if strategy == "short-text":
        return f'render only the short title "{text_value}" in original, legible lettering and add no other copy'
    if text_value:
        return f'render a text-free base image and reserve a continuous low-detail area for later accurate layout of "{text_value}"'
    return "render a text-free base image and reserve a continuous low-detail area for later title layout"


def dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def render_text(result: dict, language: str) -> str:
    if language == "zh":
        lines = [
            "正向提示词：",
            result["positive_prompt"],
            "",
            "负面约束：",
            result["negative_prompt"],
            "",
            "参数：",
            f"- 载体：{result['carrier']}",
            f"- 画幅：{result['aspect_ratio']}（{result['orientation']}）",
            f"- 视觉语言：{result['visual_language']}",
            f"- 文字策略：{result['text_strategy']}",
        ]
        if result["warnings"]:
            lines.extend(["", "提醒：", *[f"- {item}" for item in result["warnings"]]])
        return "\n".join(lines)

    lines = [
        "Positive prompt:",
        result["positive_prompt"],
        "",
        "Negative prompt:",
        result["negative_prompt"],
        "",
        "Parameters:",
        f"- Carrier: {result['carrier']}",
        f"- Aspect ratio: {result['aspect_ratio']} ({result['orientation']})",
        f"- Visual language: {result['visual_language']}",
        f"- Text strategy: {result['text_strategy']}",
    ]
    if result["warnings"]:
        lines.extend(["", "Warnings:", *[f"- {item}" for item in result["warnings"]]])
    return "\n".join(lines)


def list_carriers(language: str) -> None:
    for key in sorted(CARRIERS):
        value = CARRIERS[key]
        print(f"{key}\t{value[language]}\tdefault {value['ratio']}")


def list_visual_languages(language: str) -> None:
    for key in sorted(VISUAL_LANGUAGES):
        print(f"{key}\t{VISUAL_LANGUAGES[key][language]}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_carriers:
        list_carriers(args.prompt_language)
        return 0
    if args.list_visual_languages:
        list_visual_languages(args.prompt_language)
        return 0

    resolved = validate_args(parser, args)
    result = build_prompt(args, resolved)
    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result, args.prompt_language))
    return 0


if __name__ == "__main__":
    sys.exit(main())
