"""Portable synthetic readable-date grammar tests; no publisher receipts or contacts."""

import hashlib

import article_broker as broker
import pytest
from test_article_broker_contract import new_run  # noqa: F401

URL = "https://example.org/research/release"
NHSA = "https://www.nhsa.gov.cn/art/2026/9/8/art_109_123.html"
TITLE = "Original research publication"
PROSE = (
    "The research describes measured results, implementation methods and documented limitations. "
    * 4
)
CHINESE = (
    "本次发布介绍研究方法和具体实施方案，说明系统的评估结果以及适用范围，并列出实际使用过程中的限制。"
    * 3
)


def body(header, title=TITLE):
    return header + "\n" + title + "\n\n" + PROSE + "\n\n" + PROSE


def exact(text, metadata):
    for date in metadata["dates"]:
        assert text[date["start"] : date["end"]] == date["raw"]
        assert date["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "header",
    [
        "Published: September 4, 2026",
        "Published on September 04, 2026",
        "Publication date：Sep 4, 2026",
        "发布日期：2026年9月4日",
        "发布时间：2026-09-04",
        "发表日期: 2026年09月04日",
        "* **Published:** _September 4, 2026_",
        "- **Published**: **Sep 04, 2026**",
        "• _发布日期：_ **2026年9月4日**",
        "**Published: September 4, 2026**",
        "_September 4, 2026_",
        "***September 4, 2026***",
        "2026-09-04",
        "* 发布日期： 2026-09-04 发布机构： 示例机构",
        "Published: 2026-09-04 | Updated: 2026-09-08",
        "**Published on**：_September 4, 2026_\nUpdated: 2026-09-08",
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_readable_publication_formats_exact_original(header, newline):
    text = body(header).replace("\n", newline)
    result = broker.readable_metadata(text, URL)
    assert result["article"] and result["title"] == TITLE
    assert {d["published_at"] for d in result["dates"]} == {"2026-09-04"}
    exact(text, result)


@pytest.mark.parametrize("month", broker._READABLE_MONTHS)
@pytest.mark.parametrize("abbreviated", [False, True])
def test_readable_english_months(month, abbreviated):
    token = month[:3] if abbreviated else month
    result = broker.readable_metadata(body(f"Published: {token} 8, 2026"), URL)
    assert result["article"]
    assert (
        result["dates"][0]["published_at"]
        == f"2026-{broker._READABLE_MONTHS.index(month) + 1:02d}-08"
    )


@pytest.mark.parametrize(
    "header",
    [
        "Published: September 4",
        "发布日期：2026年2月30日",
        "Published: September 31, 2026",
        "Published: September 4, 26",
        "Published: September 4, 02026",
        "Published: 0000-09-04",
        "Published: 2026-09-04 extra",
        "Published: ２０２６-09-04",
        "Published: 2026-09-04\n* **发布时间：** _2026年9月5日_",
        "Published: 2026-09-04\n_发布日期：2026年2月30日_",
        "Published: 2026-09-04\n**Published: missing**",
        "Published: 2026-09-04 Updated: 2026-09-05 Published: 2026-09-06",
        "Updated: 2026-09-04",
        "Modified: September 4, 2026",
        "日期：2026-09-04",
        "Event date: September 4, 2026",
        "Copyright 2026-09-04",
        "Today: 2026-09-04",
        "The event occurred on 2026年9月4日。",
        "",
    ],
)
def test_readable_invalid_conflicting_or_nonpublication(header):
    result = broker.readable_metadata(body(header), URL + "/2026/9/4")
    assert not result["article"] and not result["dates"]


def test_readable_agreement_unicode_and_window():
    text = body(
        "# 科研成果发布说明书🧪\n- **发布日期**：_2026年9月4日_\nPublished: September 4, 2026"
    )
    result = broker.readable_metadata(text, URL)
    assert result["article"] and len(result["dates"]) == 2
    exact(text, result)
    proof = {"access": {"status": "verified"}, "metadata": result}
    assert broker._usable_article(proof, {"start": "2026-09-04", "end": "2026-09-10"})
    assert not broker._usable_article(
        proof, {"start": "2026-09-08", "end": "2026-09-10"}
    )


@pytest.mark.parametrize(
    "url,eligible",
    [
        (NHSA, True),
        (NHSA.replace("www.nhsa.gov.cn", "example.org"), False),
        (NHSA.replace("www.nhsa.gov.cn", "nhsa.gov.cn"), False),
        (NHSA.replace("www.nhsa.gov.cn", "www.nhsa.gov.cn.evil.test"), False),
        (NHSA.replace("www.nhsa.gov.cn", "user@www.nhsa.gov.cn"), False),
        (NHSA.replace("/9/8/", "/9/9/"), False),
        (NHSA.replace("/art/", "/event/"), False),
    ],
)
def test_readable_nhsa_header_corroboration(url, eligible):
    text = (
        "视力保护色：\n\n"
        + TITLE
        + "\n\n日期：2026-09-08 访问次数： 42 字号：大\n\n"
        + CHINESE
        + "\n\n"
        + CHINESE
    )
    result = broker.readable_metadata(text, url)
    assert result["article"] == eligible
    assert bool(result["dates"]) == eligible
    assert result["title"] == TITLE
    exact(text, result)


def test_readable_nhsa_name_and_adjacent_field():
    text = body(
        "视力保护色：\n* 名称： "
        + TITLE
        + "\n* 索引号： 123\n* **发布日期：** _2026-09-08_ 发布机构："
    )
    result = broker.readable_metadata(text, NHSA)
    assert result["article"] and result["title"] == TITLE
    assert result["dates"][0]["raw"] == "2026-09-08"
    exact(text, result)


def test_readable_nhsa_video_and_body_event_not_articles():
    header = TITLE + "\n\n日期：2026-09-08 访问次数： 42\n\n"
    text = (
        header + "[Video](https://example.org/video.mp4)\n\n" + PROSE + "\n\n" + PROSE
    )
    result = broker.readable_metadata(text, NHSA)
    assert result["dates"] and not result["article"]
    text = body("", title=TITLE) + "\n\n" + header + CHINESE
    assert not broker.readable_metadata(text, NHSA)["article"]


@pytest.mark.parametrize(
    "link,eligible",
    [
        ("[Local Variable Research](/assets/paper.pdf)", True),
        ("[View PDF](/assets/paper.pdf)", False),
        ("[Download](/assets/paper.pdf)", False),
        ("[Local Variable Research](https://example.org/paper.pdf)", False),
        ("[Local Variable Research](//evil.test/paper.pdf)", False),
        ("[Local Variable Research](/paper.pdf) [Other work](/other.pdf)", False),
        ("[Local Variable Research](/paper.pdf)\n[Other work](/other.pdf)", False),
        ("[Download the PDF](/paper.pdf)", False),
    ],
)
def test_readable_introductory_document_title_fallback(link, eligible):
    text = "_September 4, 2026_\n\n" + PROSE + link + "\n\n" + PROSE
    result = broker.readable_metadata(text, URL)
    assert result["dates"] and result["article"] == eligible
    if eligible:
        assert result["title"] == "Local Variable Research"
        assert result["title_source"] == "introductory-document-link"
    assert not broker.readable_metadata(
        text.replace("_September 4, 2026_", "Updated: September 4, 2026"), URL
    )["article"]


@pytest.mark.parametrize(
    "challenge",
    [
        "verify you are human",
        "sign in to continue",
        "website has set up Anubis to protect",
        "Anubis requires the use of modern JavaScript",
    ],
)
def test_readable_challenges_stay_blocked(challenge):
    result = broker.readable_metadata(body("Published: 2026-09-04") + challenge, URL)
    assert not result["article"] and not result["recognizable_body"]


def test_readable_native_proof_candidate_and_mutation(new_run, monkeypatch):  # noqa: F811
    import test_native_article_evidence as native

    original = native.text

    def wrapped_text(day=None):
        text = original(day)
        first, rest = text.split("\n", 1)
        return "* **发布日期：** _" + first.removeprefix("Published: ") + "_\n" + rest

    monkeypatch.setattr(native, "text", wrapped_text)
    native.test_native_receipt_seal_exact_proof_and_mutation(
        new_run, monkeypatch, False
    )


def test_readable_fenced_publication_exact_review_repro():
    text = (
        "# Original research publication\n\n~~~text\n发布日期：2026年9月4日\n~~~\n\n"
        + PROSE
        + "\n\n"
        + PROSE
    )
    result = broker.readable_metadata(text, URL)
    assert not result["dates"] and not result["article"]


def test_readable_inline_publication_exact_review_repro():
    text = body(
        "Published: September 4, 2026 Updated: September 5, 2026 Published on September 6, 2026"
    )
    result = broker.readable_metadata(text, URL)
    assert not result["dates"] and not result["article"]


@pytest.mark.parametrize(
    "structure",
    [
        "```python\n{date}\n```",
        "```` text\n```\n{date}\n````",
        "~~~text\n{date}\n~~~",
        "~~~~ language info\n~~~\n{date}\n~~~~~",
        "   ```markdown\n{date}\n   ```",
        "```\n{date}",
        "    {date}",
        "\t{date}",
        "  \t{date}",
        "> {date}",
        "> quotation\n{date}",
        "    code example\n{date}",
        "A short body sentence.\n{date}",
        "正文已经开始。\n{date}",
        PROSE + "\n\n{date}",
        "## Example\n{date}",
        "Copyright 2026\n{date}",
        "---\n{date}",
        "Footer\n{date}",
        "## References\n# Later title\n{date}",
        "Example content\n\n{date}",
    ],
)
@pytest.mark.parametrize(
    "declaration", ["发布日期：2026年9月4日", "**Published on** _September 4, 2026_"]
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_readable_publication_metadata_region_excludes_structure(
    structure, declaration, newline
):
    text = (
        "# "
        + TITLE
        + "\n\n"
        + structure.replace("{date}", declaration)
        + "\n\n"
        + PROSE
        + "\n\n"
        + PROSE
    ).replace("\n", newline)
    result = broker.readable_metadata(text, URL)
    assert not result["dates"] and not result["article"]


@pytest.mark.parametrize(
    "later",
    [
        PROSE + "\n发布日期：2026年9月6日",
        "> **Published:** September 6, 2026",
        "~~~text\n发布日期：2026年9月6日\n~~~\n# Forged code title\nPublished: 2026-09-07",
        "    # Forged code title\n    Published: 2026-09-07",
        "## Footer\nPublished on September 6, 2026",
        "Copyright 2026\nPublished: missing",
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_readable_header_date_survives_unrelated_body_dates(later, newline):
    text = (
        "# "
        + TITLE
        + "\n发布日期：2026年9月4日\n\n"
        + later
        + "\n\n"
        + PROSE
        + "\n\n"
        + PROSE
    ).replace("\n", newline)
    result = broker.readable_metadata(text, URL)
    assert result["article"] and result["title"] == TITLE
    assert [d["published_at"] for d in result["dates"]] == ["2026-09-04"]
    exact(text, result)


@pytest.mark.parametrize(
    "code",
    [
        "```markdown\n# Forged article title\n```",
        "~~~~ info\n# Forged article title\n~~~~",
        "    # Forged article title",
        "\t# Forged article title",
    ],
)
def test_readable_code_heading_cannot_supply_missing_title(code):
    text = "Published: 2026-09-04\n\n" + code + "\n\n" + PROSE + "\n\n" + PROSE
    result = broker.readable_metadata(text, URL)
    assert result["dates"] and not result["article"] and not result["title"]


@pytest.mark.parametrize(
    "second",
    [
        "Published on September 6, 2026",
        "Publication date September 6, 2026",
        "**Published on** _September 6, 2026_",
        "**Published on：September 6, 2026**",
        "发布日期 2026年9月6日",
        "**发布时间：** _2026年9月6日_",
        "发表日期\t2026年9月6日",
    ],
)
@pytest.mark.parametrize("separator", [" ", " | ", "; ", "；", "，"])
def test_readable_updated_tail_cannot_hide_publication(second, separator):
    text = body(
        "Published: September 4, 2026 Updated: September 5, 2026" + separator + second
    )
    result = broker.readable_metadata(text, URL)
    assert not result["dates"] and not result["article"]


@pytest.mark.parametrize(
    "header",
    [
        "**Published: 2026-09-04*",
        "_发布日期：2026年9月4日**",
        "Published: 2026-09-04 Updated: **September 5, 2026*",
        "Published: **2026-09-04_",
        "***Published: 2026-09-04**",
    ],
)
def test_readable_malformed_publication_wrappers_fail_closed(header):
    result = broker.readable_metadata(body(header), URL)
    assert not result["dates"] and not result["article"]


@pytest.mark.parametrize(
    "navigation", ["Home\n[Research](/research)\n", "当前位置：首页 > 科研\n", ""]
)
def test_readable_metadata_after_title_navigation_and_agreement(navigation):
    text = body(
        navigation
        + "# "
        + TITLE
        + "\n**Published on** September 4, 2026\nUpdated: 2026-09-05\n发布日期 2026年9月4日"
    )
    result = broker.readable_metadata(text, URL)
    assert result["article"] and result["title"] == TITLE
    assert len(result["dates"]) == 2
    exact(text, result)


@pytest.mark.parametrize("padding", ["\n" * 64, " " * 8192])
def test_readable_metadata_region_has_fixed_bounds(padding):
    result = broker.readable_metadata(padding + body("Published: 2026-09-04"), URL)
    assert not result["dates"] and not result["article"]


def test_readable_updated_tail_word_is_not_another_declaration():
    text = body("Published: 2026-09-04 Updated: unpublished on September 6, 2026")
    result = broker.readable_metadata(text, URL)
    assert result["article"]
    exact(text, result)


def test_readable_list_tilde_exact_review_repro():
    text = "- ~~~markdown\n  发布日期：2026年9月4日\n  ~~~\n\n" + PROSE + "\n\n" + PROSE
    result = broker.readable_metadata(text, URL)
    assert not result["dates"] and not result["article"]


@pytest.mark.parametrize("prefix", ["- ", "+ ", "* ", "• ", "1. ", "1) ", "- 1. ", "- - "])
@pytest.mark.parametrize("marker", ["~~~", "```", "~~~~"])
@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_readable_list_fences_end_metadata(prefix, marker, closed, newline):
    opening = prefix + marker + "markdown\n"
    closing = "  " + marker + "\n" if closed else ""
    text = opening + "  发布日期：2026年9月4日\n" + closing + "\n" + PROSE + "\n\n" + PROSE
    result = broker.readable_metadata(text.replace("\n", newline), URL)
    assert not result["dates"] and not result["article"]


def test_readable_existing_size_paragraph_and_portal_gates():
    assert not broker.readable_metadata(
        body("Published: 2026-09-04"), "https://example.org/news"
    )["article"]
    assert not broker.readable_metadata("Published: 2026-09-04\n" + TITLE, URL)[
        "article"
    ]
    assert not broker.readable_metadata(
        "Published: 2026-09-04\n" + TITLE + "\n" + PROSE * 3, URL
    )["article"]
    assert broker.readable_metadata(
        body("Published: 2026-09-04"), "https://anubis.techaro.lol/blog/actual-research"
    )["article"]
