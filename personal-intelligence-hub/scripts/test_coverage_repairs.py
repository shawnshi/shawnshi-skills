"""Coverage regressions: language-aware bodies, bounded reading, honest failure types."""
from copy import deepcopy
from pathlib import Path
import json

import pytest
import article_broker as broker
import run_contract as rc
import supplement_agent as sa
import fetch_news
from lane_selection import select_supplement_bound_candidates
from run_daily import assess_supplement_gaps


def candidate(index, title, summary):
    return {"title": title, "summary": summary, "url": f"https://example.org/releases/{index}",
            "source": "Original", "provisional_domain": "technology"}

ROOT = Path(__file__).resolve().parents[1]
NHSA_URL = "https://www.nhsa.gov.cn/art/2026/10/19/art_14_23157.html"
WALLET = """视力保护色：

医保个人账户跨省共济全国落地

日期：2026-10-19 访问次数： 字号：大 中 小

近日，国家医保局将医保钱包迭代升级到2.0版，自2026年10月16日起，各省、自治区、直辖市及新疆生产建设兵团已全部上线运行。至此，医保个人账户资金跨省共济给近亲属已在全国全面落地。

操作更便捷。医保钱包2.0版支持国家医保服务平台APP及支付宝小程序、线下经办窗口等多渠道办理跨省共济业务。操作界面和响应速度得到进一步优化提升，参保群众足不出户，即可完成共济关系绑定、额度设置、查询等操作。
"""
NOTICE_URL = "https://www.nhsa.gov.cn/art/2026/10/20/art_109_23163.html"
NOTICE = """2026全国医保影像AI识图大赛决赛公告

日期：2026-10-20 访问次数： 字号：大 中 小

按照2026全国医保影像AI识图大赛总体工作安排，经初赛评审、专家复核及结果公示，产生决赛入围队伍。大赛决赛定于2026年10月22日至23日在广西壮族自治区南宁市举办。现将决赛有关事项公告如下：

一、决赛时间

2026年10月22日至23日。

二、决赛地点

广西壮族自治区南宁市青秀区桂花路8号。

三、决赛形式

决赛采用“现场推理+线下路演”形式开展，设现场推理测试、参赛团队陈述与专家问答三个环节。
"""

@pytest.mark.parametrize("body,url", [(WALLET, NHSA_URL), (NOTICE, NOTICE_URL)], ids=["wallet", "notice"])
def test_short_chinese_article_paragraphs_are_real_bodies(body, url):
    meta = broker.readable_metadata(body, url)
    assert meta["recognizable_body"] is True
    assert meta["article"] is True
    assert meta["dates"]
    assert broker.article_gate_reasons(body, url)["article"] is True

@pytest.mark.parametrize("suffix", ["", "\n\n" + "联系我们：举报电话：010-12345678。维护医保基金安全，人人有责！" * 6], ids=["navigation", "contact_footer"])
def test_contact_footer_and_repeated_navigation_do_not_supply_chinese_prose(suffix):
    body = "# 医保便民服务通知\nPublished: 2026-10-19\n\n" + "服务指南 业务办理 联系我们 政策文件 " * 12 + suffix
    assert broker.readable_metadata(body, NHSA_URL)["recognizable_body"] is False


def test_challenge_and_date_ownership_stay_closed():
    assert broker.readable_metadata("Verify you are human\n" + WALLET, NHSA_URL)["article"] is False
    wrong_day_url = NHSA_URL.replace("/10/19/", "/10/20/")
    assert broker.readable_metadata(WALLET, wrong_day_url)["dates"] == []
    assert broker.readable_metadata(WALLET, "https://www.nhsa.gov.cn/news")["article"] is False


def test_registered_tech_reading_budget_is_not_hardcoded_to_two():
    focus = json.loads((ROOT / "references/strategic_focus.json").read_text(encoding="utf8"))
    pool = {"items": [candidate(i, f"AI agent tool release {i}", "Original API agent release and usage limits.") for i in range(8)]}
    gap = {"lane": "TechRadar", "max_urls": 8, "verify_bound_candidates": True, "bound_reading_budget": 6}
    _, required = select_supplement_bound_candidates(pool, gap, focus, article_broker_version=3)
    assert len(required) == 6
    legacy = deepcopy(gap)
    legacy.pop("bound_reading_budget")
    assert len(select_supplement_bound_candidates(pool, legacy, focus, article_broker_version=3)[1]) == 2
    gap["max_urls"] = 4
    assert len(select_supplement_bound_candidates(pool, gap, focus, article_broker_version=3)[1]) == 4


def test_critical_health_gap_uses_existing_url_cap_not_extra_queries():
    focus = json.loads((ROOT / "references/strategic_focus.json").read_text(encoding="utf8"))
    pool = {"items": [], "metadata": {"coverage": {"source_success_rate": 0.9, "reasons": ["strategic coverage china_policy partial"]}}}
    manifest = {"mix_request": {"requested_ratio": {"technology": 0.6, "healthcare_digital": 0.4}}, "window": {"start": "2026-10-19", "end": "2026-10-21"}}
    gaps = assess_supplement_gaps(pool, manifest, focus, article_broker_version=3)
    health = next(g for g in gaps if g["lane"] == "HealthcareRadar")
    assert health["max_urls"] == 8
    assert health["max_queries"] == 2
    assert health["max_duration_seconds"] == 600
    assert health["bound_reading_budget"] < health["max_urls"]
    # No expansion for a healthy lane, nor beyond an explicitly narrower cap.
    pool["metadata"]["coverage"]["reasons"] = []
    assert next(g for g in assess_supplement_gaps(pool, manifest, focus) if g["lane"] == "HealthcareRadar")["max_urls"] == 4
    focus["coverage_policy"]["supplement_budget"]["max_urls_per_gap_cap"] = 4
    pool["metadata"]["coverage"]["reasons"] = ["strategic coverage china_policy partial"]
    assert next(g for g in assess_supplement_gaps(pool, manifest, focus) if g["lane"] == "HealthcareRadar")["max_urls"] == 4


@pytest.mark.parametrize("error,expected", [(TimeoutError(), "TimeoutError"), (OSError(), "OSError"), (RuntimeError("HTTP 403"), "HTTP 403")])
def test_source_errors_never_become_blank_status(error, expected):
    assert fetch_news._source_failure_status(error) == expected


def test_content_verification_is_not_reported_as_transport_failure():
    content = {"status": "blocked", "error_code": "NATIVE_CONTENT_NOT_VERIFIED"}
    transport = {"status": "blocked", "error_code": "HTTP_403"}
    assert sa._access_failure_kind([content]) == "content_verification"
    assert sa._access_failure_kind([content, transport]) == "source_access"
    assert sa._access_failure_kind([{"status": "verified"}]) is None
    assert rc.validate_supplement_failure_kind("content_verification", "degraded") == "content_verification"
    with pytest.raises(rc.RunContractError):
        rc.validate_supplement_failure_kind("content_verification", "completed")
