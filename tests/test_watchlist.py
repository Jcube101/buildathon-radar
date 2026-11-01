import os
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from buildathon_radar import agent, fetcher
from buildathon_radar.ai_companies import AI_COMPANIES

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

ELEVENLABS = next(c for c in AI_COMPANIES if c["name"] == "ElevenLabs")
RUNWAY = next(c for c in AI_COMPANIES if c["name"] == "Runway")


def _rss_fixture():
    now = datetime.now(timezone.utc)
    with open(os.path.join(FIXTURES_DIR, "watchlist_bing_news_sample.xml")) as f:
        text = f.read()
    return (
        text.replace("{RECENT}", format_datetime(now - timedelta(days=1)))
        .replace("{OLD}", format_datetime(now - timedelta(days=20)))
    )


class FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def _no_topic_queries(monkeypatch):
    monkeypatch.setattr(fetcher, "WATCHLIST_TOPIC_QUERIES", [])


def _patch_get(monkeypatch, handler):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers})
        return handler(len(calls))

    monkeypatch.setattr(fetcher.requests, "get", fake_get)
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
    return calls


class TestCompanyList:
    def test_has_100_unique_companies(self):
        names = [c["name"] for c in AI_COMPANIES]
        assert len(names) == 100
        assert len(set(names)) == 100

    def test_every_company_has_required_fields(self):
        for c in AI_COMPANIES:
            assert c["aliases"] and all(isinstance(a, str) and a for a in c["aliases"])
            assert c["category"]
            assert isinstance(c["record"], str)
            assert isinstance(c["venues"], list)


class TestQueryAndLinks:
    def test_query_uses_primary_alias_only_and_adds_contest_terms(self):
        q = fetcher._watchlist_query([ELEVENLABS])
        assert q.startswith('("ElevenLabs")')
        assert '"Eleven Labs"' not in q
        assert "hackathon" in q and "contest" in q

    def test_one_company_per_query_by_default(self):
        assert fetcher.WATCHLIST_BATCH_SIZE == 1

    def test_headline_company_beats_blurb_company(self):
        google = next(c for c in AI_COMPANIES if c["name"] == "Google")
        meta = next(c for c in AI_COMPANIES if c["name"] == "Meta")
        title = "Rise Networks, INEC, Meta, others launch #AI4Elections hackathon"
        text = f"{title} Supported by Google and others."
        assert fetcher._match_company(text, AI_COMPANIES, title=title) is meta
        assert fetcher._match_company(text, [google, meta]) is google

    def test_batches_cover_all_companies(self):
        batches = fetcher._watchlist_batches(AI_COMPANIES, fetcher.WATCHLIST_BATCH_SIZE)
        assert sum(len(b) for b in batches) == 100
        assert all(len(b) <= fetcher.WATCHLIST_BATCH_SIZE for b in batches)

    def test_unwraps_bing_redirect_and_strips_tracking(self):
        link = (
            "http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=x"
            "&url=https%3a%2f%2fwww.example.com%2fpost%3futm_source%3drss%26id%3d42&c=1"
        )
        assert fetcher._unwrap_news_link(link) == "https://www.example.com/post?id=42"

    def test_plain_link_passes_through(self):
        assert fetcher._unwrap_news_link("https://elevenlabs.io/blog/x") == "https://elevenlabs.io/blog/x"

    def test_alias_match_is_whole_word(self):
        assert fetcher._match_company("The ElevenLabs contest", [ELEVENLABS]) is ELEVENLABS
        assert fetcher._match_company("NotElevenLabsX contest", [ELEVENLABS]) is None


class TestFetchWatchlist:
    def test_filters_and_normalises_fixture(self, monkeypatch):
        rss = _rss_fixture()
        calls = _patch_get(monkeypatch, lambda n: FakeResp(rss))
        items, error = fetcher.fetch_watchlist(companies=[ELEVENLABS, RUNWAY])

        assert error is None
        assert len(calls) == 2  # one query per company
        assert calls[0]["params"]["format"] == "rss"

        titles = [i["title"] for i in items]
        # Kept: two ElevenLabs articles (per-company cap), one open Runway contest.
        assert len(items) == 3
        assert "Runway AI opens Gen:48 short film challenge with a $50K prize pool" in titles
        assert sum(1 for i in items if i["host"] == "ElevenLabs") == fetcher.WATCHLIST_MAX_PER_COMPANY
        # Dropped: market-competition news, winners announcement, old article,
        # an article naming no watchlist company.
        assert not any("stiff competition" in t for t in titles)
        assert not any("winners announced" in t for t in titles)
        assert not any("Bengaluru" in t for t in titles)
        assert not any("raises" in t for t in titles)

    def test_item_matches_normalised_contract(self, monkeypatch):
        rss = _rss_fixture()
        _patch_get(monkeypatch, lambda n: FakeResp(rss))
        items, _ = fetcher.fetch_watchlist(companies=[ELEVENLABS])
        item = next(i for i in items if "catchiest" in i["title"])

        assert item["source"] == "Watchlist"
        assert item["url"] == "https://www.example-news.com/tech/elevenlabs-the-search-contest?id=42"
        assert item["host"] == "ElevenLabs"
        assert item["prize"] == "$100,000"
        assert item["mode"] == "unknown"
        assert item["dates"].startswith("Announced ")
        assert "AI company watchlist" in item["themes"]
        assert "ElevenCreative" in item["summary"]
        for key, value in item.items():
            if key not in ("event_start", "event_end"):
                assert value is not None, key

    def test_partial_failure_keeps_other_batches(self, monkeypatch):
        rss = _rss_fixture()
        monkeypatch.setattr(fetcher, "WATCHLIST_BATCH_SIZE", 1)

        def handler(n):
            if n == 1:
                raise RuntimeError("timeout")
            return FakeResp(rss)

        _patch_get(monkeypatch, handler)
        items, error = fetcher.fetch_watchlist(companies=[RUNWAY, ELEVENLABS])
        assert error is None
        assert items and all(i["host"] == "ElevenLabs" for i in items)

    def test_all_batches_failing_is_a_source_error(self, monkeypatch):
        monkeypatch.setattr(fetcher, "WATCHLIST_BATCH_SIZE", 1)

        def handler(n):
            raise RuntimeError("boom")

        _patch_get(monkeypatch, handler)
        items, error = fetcher.fetch_watchlist(companies=[RUNWAY, ELEVENLABS])
        assert items == []
        assert error == "boom"

    def test_malformed_xml_counts_as_batch_failure(self, monkeypatch):
        _patch_get(monkeypatch, lambda n: FakeResp("<html>not rss"))
        items, error = fetcher.fetch_watchlist(companies=[ELEVENLABS])
        assert items == []
        assert error

    def test_total_cap(self, monkeypatch):
        rss = _rss_fixture()
        monkeypatch.setattr(fetcher, "WATCHLIST_MAX_ITEMS", 1)
        _patch_get(monkeypatch, lambda n: FakeResp(rss))
        items, _ = fetcher.fetch_watchlist(companies=[ELEVENLABS, RUNWAY])
        assert len(items) == 1

    def test_registered_as_a_source(self):
        assert fetcher.ENABLE_WATCHLIST_SOURCE is True
        assert any(s["name"] == "Watchlist" for s in fetcher.SOURCES)


class TestContestSignal:
    # Headlines that passed the first live run (2026-11-01) and are not contests.
    @pytest.mark.parametrize("title,blurb", [
        ("IT hardware reseller lists GPUs from decommissioned Nvidia supercomputer on eBay for $60 million", "AMD and NVIDIA chips."),
        ("DeepSeek Unveils Super-Agent To Gain Edge Over Anthropic", "A challenge to US labs."),
        ("US Is Inquiring About Nvidia's Purchase Of Hugging Face, Sources Say", "Shares closed at $12.93 amid competition concerns."),
        ("Scale AI Faces Worker Privacy Backlash", "A new challenge for the company."),
        ("OpenAI doubles usage limits on Pro plans as competition with Anthropic heats up", ""),
        ("Meta Platforms stock outlook: AI hackathon keeps developers in focus", ""),
    ])
    def test_live_false_positives_rejected(self, title, blurb):
        assert not fetcher._is_contest_news(title, blurb)

    @pytest.mark.parametrize("title,blurb", [
        ("The Search: $100,000 for the world's catchiest ad", "ElevenLabs opens submissions; a global contest for AI-made ads."),
        ("Runway AI opens Gen:48 short film challenge", ""),
        ("Anthropic announces Built with Claude: Japan hackathon", ""),
    ])
    def test_real_contests_accepted(self, title, blurb):
        assert fetcher._is_contest_news(title, blurb)


class TestTopicQueries:
    def test_topic_query_matches_any_company(self, monkeypatch):
        monkeypatch.setattr(fetcher, "WATCHLIST_TOPIC_QUERIES", ['"AI contest"'])
        monkeypatch.setattr(fetcher, "WATCHLIST_BATCH_SIZE", 100)
        rss = _rss_fixture()
        calls = _patch_get(monkeypatch, lambda n: FakeResp(rss))
        stats = []
        items, error = fetcher.fetch_watchlist(companies=AI_COMPANIES, stats=stats)
        assert error is None
        # 17 company batches would be 1 at size 100, plus 1 topic query.
        assert [c["params"]["q"] for c in calls][-1] == '"AI contest"'
        assert len(stats) == 2
        assert stats[-1]["raw"] == 8
        assert any(r.startswith("not a contest") for r in stats[-1]["rejected"])
        assert {i["host"] for i in items} == {"ElevenLabs", "Runway"}


class TestRubric:
    def test_prompt_covers_creative_contests(self):
        assert "AI creative contests are in scope" in agent.SYSTEM_PROMPT
        assert "score theme fit 22 to 30" in agent.SYSTEM_PROMPT

    def test_prompt_explains_watchlist_items(self):
        assert 'source "Watchlist"' in agent.SYSTEM_PROMPT
        assert "already closed or announced its winners" in agent.SYSTEM_PROMPT
