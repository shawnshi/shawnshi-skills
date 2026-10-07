"""Native readable publication headers; no network or frozen-run writes."""

import hashlib

import article_broker as broker
import pytest

OPENAI = "https://openai.com/index/devday-2026-recap/"
BODY = "A source paragraph reports a product announcement and explains its scope. " * 8


def page(header):
    return header + "\n\n" + BODY


def metadata(header, url=OPENAI):
    return broker.readable_metadata(page(header), url)


def test_known_publisher_date_header_has_literal_hash_bound_proof():
    header = "# DevDay 2026 Recap\n\n**Date:** September 29, 2026  \n**Category:** Company, Product"
    text = page(header)
    dates = broker.readable_metadata(text, OPENAI)["dates"]
    assert len(dates) == 1
    proof = dates[0]
    assert proof["published_at"] == "2026-09-29"
    assert proof["parser_rule"] == "openai-article-header-date/1"
    assert text[proof["start"] : proof["end"]] == proof["raw"] == "September 29, 2026"
    assert proof["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("url", ["https://example.org/news/test", "https://openai.com.evil.example/index/test/", "https://openai.com/events/test/", "https://openai.com/index/"])
def test_generic_date_not_promoted_for_other_pages(url):
    assert metadata("# Product announcement\nDate: September 29, 2026\nCategory: Product", url)["dates"] == []


@pytest.mark.parametrize("header", [
    "# Product announcement\nDate: September 29, 2026",
    "# Product announcement\nDate: September 29, 2026\nPublished: October 1, 2026",
    "Date: September 29, 2026\n# Product announcement\nPublished: October 1, 2026",
    "# Product announcement\nDate: September 29, 2026\nCategory: Event\nPublished: October 1, 2026",
    "Date: September 29, 2026\nCategory: Product",
    "# Product announcement\nDate: September 29, 2026\nCategory: Event",
    "# Product announcement\nDate: September 29, 2026\nCategory: Product\nPublished: October 1, 2026",
    "# Product announcement\nDate: September 31, 2026\nCategory: Product",
    "# Product announcement\nDate: September 29, 2026 will be the launch\nCategory: Product",
    "# Product announcement\n```\nDate: September 29, 2026\nCategory: Product\n```",
    "# Product announcement\n> Date: September 29, 2026\nCategory: Product",
    "# Product announcement\nA sentence starts the article body.\nDate: September 29, 2026\nCategory: Product",
])
def test_publisher_header_refuses_missing_context_prose_conflicts_and_structure(header):
    assert metadata(header)["dates"] == []


@pytest.mark.parametrize("date", ["September 1st, 2026", "September 2nd, 2026", "September 3rd, 2026", "September 11th, 2026", "September 12th, 2026", "September 13th, 2026", "September 21st, 2026", "September 22nd, 2026", "September 23rd, 2026", "September 29th, 2026", "SEPTEMBER 29TH, 2026"])
def test_leading_ordinal_date_keeps_literal_offsets(date):
    text = page(date + "\n\n# A product announcement")
    dates = broker.readable_metadata(text, "https://devblogs.microsoft.com/visualstudio/update/")["dates"]
    assert len(dates) == 1
    assert dates[0]["parser_rule"] == "leading-dateline/1"
    assert text[dates[0]["start"] : dates[0]["end"]] == dates[0]["raw"] == date
    assert dates[0]["published_at"].startswith("2026-09-")


@pytest.mark.parametrize("date", ["September 11st, 2026", "September 12nd, 2026", "September 13rd, 2026", "September 21th, 2026", "September 29st, 2026", "September 31st, 2026"])
def test_bad_ordinals_or_impossible_calendar_dates_fail_closed(date):
    assert metadata(date + "\n\n# A product announcement", "https://example.org/news/item")["dates"] == []


def test_ordinal_date_in_article_quote_is_not_publication():
    assert metadata("# Product announcement\nA statement ends the metadata header.\nSeptember 29th, 2026")["dates"] == []
