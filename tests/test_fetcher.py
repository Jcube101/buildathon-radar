import json
import os
from datetime import datetime, timedelta

import pytest

from buildathon_radar import fetcher

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


def _raise(*args, **kwargs):
    raise Exception("boom")


class TestDevpostNormalise:
    def test_real_fixture_item(self):
        data = load_fixture("devpost_sample.json")
        item = data["hackathons"][0]
        n = fetcher.normalise_devpost(item)
        assert n["source"] == "Devpost"
        assert n["url"].startswith("https://")
        assert isinstance(n["themes"], list)
        for v in n.values():
            assert v is not None

    def test_missing_fields_fallback(self):
        n = fetcher.normalise_devpost({})
        assert n["title"] == "Unknown"
        assert n["url"] == ""
        assert n["host"] == "Unknown"
        assert n["published"] == "Unknown"
        assert n["location"] == "Unknown"
        assert n["mode"] == "in-person"
        assert n["prize"] == ""
        assert n["themes"] == []

    def test_prize_html_stripped(self):
        item = {"prize_amount": "$<span data-currency-value>2,000,000</span>"}
        n = fetcher.normalise_devpost(item)
        assert n["prize"] == "$2,000,000"

    def test_online_mode_detection(self):
        item = {"displayed_location": {"location": "Online"}}
        n = fetcher.normalise_devpost(item)
        assert n["mode"] == "online"

    def test_in_person_mode_detection(self):
        item = {"displayed_location": {"location": "Bengaluru, India"}}
        n = fetcher.normalise_devpost(item)
        assert n["mode"] == "in-person"


class TestDevpostDateParse:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("May 19 - Aug 17, 2026", "2026-05-19"),
            ("Jul 18 - 19, 2026", "2026-07-18"),
            ("", "Unknown"),
            ("garbage string", "Unknown"),
            ("Just one segment, 2026", "Unknown"),
        ],
    )
    def test_parse(self, raw, expected):
        assert fetcher._parse_devpost_date(raw) == expected


class TestDevfolioNormalise:
    def test_real_fixture_item(self):
        data = load_fixture("devfolio_sample.json")
        src = data["hits"]["hits"][0]["_source"]
        n = fetcher.normalise_devfolio(src)
        assert n["source"] == "Devfolio"
        assert n["url"].startswith("https://") and n["url"].endswith(".devfolio.co/")
        for v in n.values():
            assert v is not None

    def test_missing_fields_fallback(self):
        n = fetcher.normalise_devfolio({})
        assert n["title"] == "Unknown"
        assert n["url"] == ""
        assert n["host"] == "Unknown"
        assert n["published"] == "Unknown"
        assert n["location"] == "Unknown"
        assert n["mode"] == "in-person"
        assert n["prize"] == ""
        assert n["themes"] == []

    def test_online_true(self):
        src = {"is_online": True, "slug": "test-hack"}
        n = fetcher.normalise_devfolio(src)
        assert n["mode"] == "online"
        assert n["location"] == "Online"

    def test_city_country_location(self):
        src = {"city": "Bengaluru", "country": "India", "slug": "x"}
        n = fetcher.normalise_devfolio(src)
        assert n["location"] == "Bengaluru, India"

    def test_host_fallback_to_sponsor(self):
        src = {"sponsor_tiers": [{"sponsors": [{"name": "Kaggle"}]}]}
        n = fetcher.normalise_devfolio(src)
        assert n["host"] == "Kaggle"

    def test_url_construction(self):
        src = {"slug": "my-hack"}
        n = fetcher.normalise_devfolio(src)
        assert n["url"] == "https://my-hack.devfolio.co/"


class TestCache:
    def test_load_cache_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert fetcher.load_cache() == {}

    def test_load_cache_corrupt_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cache.json").write_text("not json{{{")
        assert fetcher.load_cache() == {}

    def test_load_cache_legacy_format_migrates(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cache.json").write_text(
            json.dumps({"urls": ["https://a.com"], "last_updated": "x"})
        )
        cache = fetcher.load_cache()
        today = datetime.now().strftime("%Y-%m-%d")
        assert cache == {"https://a.com": today}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher.save_cache({"https://a.com": "2026-01-01"})
        assert fetcher.load_cache() == {"https://a.com": "2026-01-01"}


class TestFetchEventsTTL:
    def _make_item(self, url):
        return {
            "source": "Devpost",
            "title": "T",
            "url": url,
            "summary": "s",
            "published": "2026-01-01",
            "location": "Online",
            "mode": "online",
            "host": "H",
            "dates": "d",
            "prize": "",
            "themes": [],
        }

    def test_fresh_cache_hit_suppressed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://example.com/event"
        today = datetime.now().strftime("%Y-%m-%d")
        (tmp_path / "cache.json").write_text(json.dumps({url: today}))
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([self._make_item(url)], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=False)
        assert items == []
        assert health["Devpost"]["count"] == 0

    def test_stale_cache_entry_resurfaces(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://example.com/event"
        stale_date = (
            datetime.now() - timedelta(days=fetcher.CACHE_TTL_DAYS + 5)
        ).strftime("%Y-%m-%d")
        (tmp_path / "cache.json").write_text(json.dumps({url: stale_date}))
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([self._make_item(url)], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=False)
        assert len(items) == 1
        assert health["Devpost"]["count"] == 1

    def test_dry_run_skips_cache_read_and_write(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://example.com/event"
        today = datetime.now().strftime("%Y-%m-%d")
        (tmp_path / "cache.json").write_text(json.dumps({url: today}))
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([self._make_item(url)], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        assert len(items) == 1
        with open(tmp_path / "cache.json") as f:
            data = json.load(f)
        assert data == {url: today}

    def test_source_failure_isolated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": _raise},
                {
                    "name": "Devfolio",
                    "fetch": lambda: ([self._make_item("https://ok.com")], None),
                },
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        assert len(items) == 1
        assert health["Devfolio"]["count"] == 1
        assert health["Devpost"]["error"] == "boom"
