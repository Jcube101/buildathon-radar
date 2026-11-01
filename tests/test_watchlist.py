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
    def test_query_quotes_every_alias_and_adds_contest_terms(self):
        q = fetcher._watchlist_query([ELEVENLABS, RUNWAY])
        for alias in ELEVENLABS["aliases"] + RUNWAY["aliases"]:
            assert f'"{alias}"' in q
        assert "hackathon" in q and "contest" in q

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
        assert len(calls) == 1
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


class TestRubric:
    def test_prompt_covers_creative_contests(self):
        assert "AI creative contests are in scope" in agent.SYSTEM_PROMPT
        assert "score theme fit 22 to 30" in agent.SYSTEM_PROMPT

    def test_prompt_explains_watchlist_items(self):
        assert 'source "Watchlist"' in agent.SYSTEM_PROMPT
        assert "already closed or announced its winners" in agent.SYSTEM_PROMPT
