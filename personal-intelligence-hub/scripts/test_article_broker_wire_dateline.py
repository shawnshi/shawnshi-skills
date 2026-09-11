"""Wire/press-release publication rules: conservative positive and negative coverage.

Synthetic retained text only; no network, no fetch receipts, no frozen run writes.
"""

import hashlib

import article_broker as broker


def paragraph(repeats=3):
    return (
        "Retained readable paragraph used only to satisfy the structural article "
        "requirements of the bounded evidence parser. "
    ) * repeats


def document(*blocks):
    return "\n\n".join(blocks) + "\n"


def dates(text, url="https://example.org/news/press-release"):
    return broker.readable_metadata(text, url)["dates"]


def test_wire_dateline_dash_form_place_zone():
    text = document(
        "**Hamina, Kajaani, Muhos, Vaala, FINLAND — Sept. 9, 2026 —** Example Corp today "
        "announced plans to invest at least 13 billion in digital infrastructure over the "
        "next two years, deepening its long-term commitment to the region.",
        paragraph(),
        paragraph(),
    )
    found = dates(text)
    assert [(entry["published_at"], entry["parser_rule"], entry["raw"]) for entry in found] == [
        ("2026-09-09", "wire-dateline/1", "Sept. 9, 2026")
    ]


def test_wire_dateline_day_first_and_trailing_dash():
    text = document(
        "**BRUSSELS – 10 September 2026**– Example Foundation, one of the largest open "
        "source foundations, today announced the availability of a free toolkit to help "
        "small organisations prepare for upcoming obligations.",
        paragraph(),
        paragraph(),
    )
    found = dates(text)
    assert [(entry["published_at"], entry["parser_rule"], entry["raw"]) for entry in found] == [
        ("2026-09-10", "wire-dateline/1", "10 September 2026")
    ]


def test_wire_dateline_space_separator_with_trailing_dash():
    text = document(
        "**Cambridge, USA and Paris, France September 9, 2026** – Example Care, a global "
        "leader in remote monitoring, has secured a funding round led by a European growth "
        "fund alongside a long-standing investment partner.",
        paragraph(),
        paragraph(),
    )
    found = dates(text)
    assert [entry["published_at"] for entry in found] == ["2026-09-09"]


def test_wire_dateline_wire_parenthetical_double_dash():
    text = document(
        "CAMBRIDGE, Mass. and PARIS, Sept. 09, 2026 (GLOBE NEWSWIRE) -- Example Care, a "
        "global leader in AI-driven cardiac remote monitoring, has secured a funding round "
        "led by a European growth capital firm.",
        paragraph(),
        paragraph(),
    )
    found = dates(text)
    assert [(entry["published_at"], entry["raw"]) for entry in found] == [
        ("2026-09-09", "Sept. 09, 2026")
    ]


def test_wire_label_press_release_header():
    text = document(
        "PRESS RELEASE September 9, 2026",
        "Example Inc today introduced a new foldable device with a larger inner display and "
        "an updated assistant that runs partly on-device for privacy.",
        paragraph(),
        paragraph(),
    )
    found = dates(text)
    assert [(entry["published_at"], entry["parser_rule"], entry["raw"]) for entry in found] == [
        ("2026-09-09", "wire-label/1", "September 9, 2026")
    ]


def test_wire_date_without_wire_terminator_is_refused():
    text = document(
        "Important News September 9, 2026",
        "Example Inc today introduced a product that should not grant a publication date "
        "merely because a short capitalised line precedes it.",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_wire_rule_does_not_scan_first_body_line():
    text = document(
        paragraph(),
        "**Hamina, FINLAND — Sept. 9, 2026 —** Example Corp today announced an investment "
        "that must not be read as a publication date once prose has already started.",
        paragraph(),
    )
    assert dates(text) == []


def test_explicit_label_takes_precedence_over_wire_declaration():
    text = document(
        "Published September 10, 2026",
        "**Hamina, FINLAND — Sept. 9, 2026 —** Example Corp today announced an investment "
        "described after an explicit publication label.",
        paragraph(),
        paragraph(),
    )
    found = dates(text)
    assert [(entry["published_at"], entry["parser_rule"]) for entry in found] == [
        ("2026-09-10", "published-label/1")
    ]


def test_conflicting_wire_declarations_drop_all_dates():
    text = document(
        "**Hamina, FINLAND — Sept. 9, 2026 —** Example Corp today announced an investment "
        "followed by a second, inconsistent dateline in the same header region.",
        "**Brussels, Belgium — 10 September 2026** – Example Foundation today announced a "
        "second dateline that conflicts with the first one.",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_navigation_residue_never_becomes_the_title():
    text = document(
        "opens in new window",
        "Example Foundation releases free compliance toolkit",
        paragraph(),
        paragraph(),
    )
    metadata = broker.readable_metadata(text, "https://example.org/news/toolkit")
    assert metadata["title"] == "Example Foundation releases free compliance toolkit"
    assert metadata["dates"] == []


def test_emphasis_damaged_wire_line_is_skipped_not_repaired():
    text = document(
        "**Hamina, FINLAND — Sept. 9, 2026 — Example Corp today announced an unterminated "
        "emphasis run that must not be repaired into a publication date.",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_wire_dateline_recovers_eligible_article_with_valid_title():
    text = document(
        "Example deepens commitment to sustainable digital infrastructure",
        "**Hamina, Kajaani, Muhos, Vaala, FINLAND — Sept. 9, 2026 —** Example Corp today "
        "announced plans to invest at least 13 billion in digital infrastructure over the "
        "next two years, deepening its long-term commitment to the country and to Europe.",
        paragraph(),
        paragraph(),
    )
    metadata = broker.readable_metadata(text, "https://example.org/news/infrastructure")
    assert metadata["article"] is True
    assert metadata["title"] == "Example deepens commitment to sustainable digital infrastructure"
    assert [entry["published_at"] for entry in metadata["dates"]] == ["2026-09-09"]


def test_wire_rules_do_not_apply_to_arxiv_identity_branch():
    text = document(
        "PRESS RELEASE September 9, 2026",
        paragraph(),
        paragraph(),
    )
    metadata = broker.readable_metadata(text, "https://arxiv.org/abs/2609.07754")
    assert metadata["dates"] == []
    assert metadata["article"] is False


# --- Independent-review regression cases -------------------------------------


def test_primary_date_conflict_never_falls_back_to_wire_date():
    text = document(
        "Published September 9, 2026",
        "Published September 10, 2026",
        "PRESS RELEASE September 11, 2026",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_single_primary_declarations_are_accepted_independently():
    for value in ("September 9, 2026", "September 10, 2026", "September 11, 2026"):
        text = document(
            f"Published {value}",
            paragraph(),
            paragraph(),
        )
        found = dates(text)
        assert [entry["raw"] for entry in found] == [value], value


def test_body_prose_date_is_never_a_wire_declaration():
    text = document(
        "We met on September 9, 2026 — this describes an earlier meeting.",
        "Published September 10, 2026",
        paragraph(),
        paragraph(),
    )
    # The prose line must terminate the bounded header, so the later label is out of scope.
    assert dates(text) == []


def test_update_prefix_is_never_a_wire_dateline():
    text = document(
        "Updated September 10, 2026 — corrected spelling.",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_five_digit_year_run_on_is_refused():
    text = document(
        "PARIS — September 9, 20260",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_wire_label_tail_hiding_second_declaration_is_refused():
    text = document(
        "PRESS RELEASE September 9, 2026 | Updated: September 10, 2026; Published: September 11, 2026",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_news_and_media_release_headers_are_supported():
    for prefix in ("NEWS RELEASE", "MEDIA RELEASE"):
        text = document(
            f"{prefix} September 9, 2026",
            paragraph(),
            paragraph(),
        )
        found = dates(text)
        assert [entry["published_at"] for entry in found] == ["2026-09-09"], prefix
        assert found[0]["parser_rule"] == "wire-label/1"


def test_ordinal_day_first_form_supported():
    text = document(
        "**BRUSSELS – 10th September 2026**– Example Foundation announced a toolkit for "
        "small organisations preparing for upcoming obligations.",
        paragraph(),
        paragraph(),
    )
    assert [entry["published_at"] for entry in dates(text)] == ["2026-09-10"]


def test_invalid_calendar_day_is_refused():
    text = document(
        "**Hamina, FINLAND — February 30, 2026 —** Example Corp announced an investment "
        "whose declared day does not exist in the calendar.",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_date_spans_slice_the_original_text_exactly():
    text = document(
        "**Hamina, Kajaani, FINLAND — Sept. 9, 2026 —** Example Corp announced a funding "
        "round covering several regions over the coming two years.",
        paragraph(),
        paragraph(),
    )
    found = dates(text)
    assert len(found) == 1
    entry = found[0]
    assert text[entry["start"] : entry["end"]] == entry["raw"] == "Sept. 9, 2026"
    assert entry["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_wire_shape_without_terminator_is_not_a_wire_declaration():
    # Direct classification assertions that isolate the terminator rule: an uppercase place,
    # a valid calendar date and a comma/space separator would otherwise qualify.
    assert broker._readable_wire_declaration("PARIS, September 9, 2026") is None
    assert broker._readable_wire_declaration("PARIS September 9, 2026") is None
    assert broker._readable_wire_declaration(
        "PARIS — September 9, 2026"
    ) is not None  # same shape with a wire terminator is accepted
    assert broker._readable_wire_declaration("Important News September 9, 2026") is None
    text = document(
        "Example Corp statement September 9, 2026",
        "Published September 10, 2026",
        paragraph(),
        paragraph(),
    )
    # The unterminated line is a literal title, not a wire declaration: only the explicit
    # label grants a date, and the ambiguous wire date is never promoted.
    found = dates(text)
    assert [(entry["published_at"], entry["parser_rule"]) for entry in found] == [
        ("2026-09-10", "published-label/1")
    ]


def test_hyphenated_update_status_cannot_head_a_dateline():
    assert broker._readable_wire_declaration(
        "Last-Updated PARIS — September 10, 2026 — corrected spelling."
    ) is None
    text = document(
        "Example report title",
        "Last-Updated PARIS — September 10, 2026 — corrected spelling.",
        paragraph(),
        paragraph(),
    )
    assert dates(text) == []


def test_dateline_remainder_with_supported_wire_label_is_refused():
    for remainder in (
        "PRESS RELEASE September 11, 2026",
        "NEWS RELEASE September 11, 2026",
        "MEDIA RELEASE September 11, 2026",
        "Published September 11, 2026",
        "Publication\tdate: September 11, 2026",
        "Updated. September 11, 2026",
        "Last updated: September 11, 2026",
        "发布时间：2026-09-11",
        # Real headers spell these labels in upper case; the guard must not be case-sensitive.
        "PUBLISHED: September 11, 2026",
        "Published On 11 September 2026",
        "UPDATED: September 11, 2026",
        "MODIFIED ON: September 11, 2026",
        "LAST UPDATED: September 11, 2026",
        "News Release September 11, 2026",
    ):
        line = f"PARIS — September 9, 2026 — {remainder}"
        assert broker._readable_wire_declaration(line) is None, remainder
        assert dates(document(line, paragraph(), paragraph())) == [], remainder


def test_label_tail_case_variants_are_refused():
    for tail in (
        "| UPDATED: September 11, 2026",
        "| Updated: September 11, 2026",
        "| PUBLISHED: September 11, 2026",
        "| Publication Date: September 11, 2026",
    ):
        line = f"PRESS RELEASE September 9, 2026 {tail}"
        assert broker._readable_wire_declaration(line) is None, tail
        assert dates(document(line, paragraph(), paragraph())) == [], tail


def test_terminated_dateline_with_metadata_only_remainder_is_kept():
    # A supported label without a date must not trigger the contradiction guard.
    assert broker._readable_wire_declaration(
        "PARIS — September 9, 2026 — the findings were published in a journal last year."
    ) is not None
    assert broker._readable_wire_declaration(
        "PARIS — September 9, 2026 — Author: Example News Desk"
    ) is not None


def test_updated_with_period_cannot_head_a_dateline_or_extend_the_header():
    assert broker._readable_wire_declaration(
        "Updated. PARIS — September 10, 2026 — corrected spelling."
    ) is None
    text = document(
        "Example report title",
        "Updated. PARIS — September 10, 2026 — corrected spelling.",
        "Published September 11, 2026",
        paragraph(),
        paragraph(),
    )
    # The punctuated update sentence is prose: the later Published label stays out of scope.
    assert dates(text) == []


def test_dateline_tail_contradiction_is_refused():
    assert broker._readable_wire_declaration(
        "PARIS — September 9, 2026 — Updated: September 10, 2026; Published: September 11, 2026"
    ) is None
    assert broker._readable_wire_declaration(
        "PARIS — September 9, 2026 — note. Published September 11, 2026"
    ) is None
    # A dateline whose remainder is ordinary prose, including the word 'published', is kept.
    assert broker._readable_wire_declaration(
        "PARIS — September 9, 2026 — the findings were published in a journal last year."
    ) is not None


def test_each_wire_declaration_is_accepted_independently():
    for line, expected in (
        ("**Hamina, FINLAND — Sept. 9, 2026 —** Example Corp announced an investment over "
         "the coming two years.", "2026-09-09"),
        ("**Brussels, BELGIUM — 10 September 2026** – Example Foundation announced a "
         "toolkit for small organisations.", "2026-09-10"),
    ):
        text = document(line, paragraph(), paragraph())
        found = dates(text)
        assert [entry["published_at"] for entry in found] == [expected], line
