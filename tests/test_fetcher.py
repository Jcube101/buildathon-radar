import json
import os
from datetime import datetime, timedelta

import pytest

from buildathon_radar import fetcher

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# event_start / event_end are legitimately None when no date is available;
# every other key in the normalised contract must never be None.
DATE_FIELDS_ALLOWED_NONE = {"event_start", "event_end"}


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


def _raise(*args, **kwargs):
    raise Exception("boom")


def _assert_no_unexpected_nones(item):
    for k, v in item.items():
        if k in DATE_FIELDS_ALLOWED_NONE:
            continue
        assert v is not None, f"{k} unexpectedly None"


class TestDevpostNormalise:
    def test_real_fixture_item(self):
        data = load_fixture("devpost_sample.json")
        item = data["hackathons"][0]
        n = fetcher.normalise_devpost(item)
        assert n["source"] == "Devpost"
        assert n["url"].startswith("https://")
        assert isinstance(n["themes"], list)
        _assert_no_unexpected_nones(n)

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
        assert n["event_start"] is None
        assert n["event_end"] is None

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

    def test_event_start_end_populated_when_dates_parseable(self):
        item = {"submission_period_dates": "May 19 - Aug 17, 2026"}
        n = fetcher.normalise_devpost(item)
        assert n["event_start"] == "2026-05-19"
        assert n["event_end"] == "2026-08-17"

    def test_event_start_end_null_when_dates_unparseable(self):
        item = {"submission_period_dates": "garbage string"}
        n = fetcher.normalise_devpost(item)
        assert n["event_start"] is None
        assert n["event_end"] is None


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


class TestDevpostDateRangeParse:
    @pytest.mark.parametrize(
        "raw,expected_start,expected_end",
        [
            ("May 19 - Aug 17, 2026", "2026-05-19", "2026-08-17"),
            ("Jul 18 - 19, 2026", "2026-07-18", "2026-07-19"),
            ("", None, None),
            ("garbage string", None, None),
        ],
    )
    def test_parse_range(self, raw, expected_start, expected_end):
        start, end = fetcher._parse_devpost_date_range(raw)
        assert start == expected_start
        assert end == expected_end


class TestDevfolioNormalise:
    def test_real_fixture_item(self):
        data = load_fixture("devfolio_sample.json")
        src = data["hits"]["hits"][0]["_source"]
        n = fetcher.normalise_devfolio(src)
        assert n["source"] == "Devfolio"
        assert n["url"].startswith("https://") and n["url"].endswith(".devfolio.co/")
        _assert_no_unexpected_nones(n)

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
        assert n["event_start"] is None
        assert n["event_end"] is None

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

    def test_event_start_end_populated_from_iso_dates(self):
        src = {"slug": "x", "starts_at": "2026-07-18T03:30:00+00:00", "ends_at": "2026-07-18T15:00:00+00:00"}
        n = fetcher.normalise_devfolio(src)
        assert n["event_start"] == "2026-07-18"
        assert n["event_end"] == "2026-07-18"

    def test_event_start_end_null_without_dates(self):
        src = {"slug": "x"}
        n = fetcher.normalise_devfolio(src)
        assert n["event_start"] is None
        assert n["event_end"] is None


class TestNormalizeTitle:
    def test_strips_parenthetical_suffix(self):
        a = fetcher._normalize_title(
            "Agentic Commerce Hackathon (Build agents that act, shop, book, renew and pay.)"
        )
        b = fetcher._normalize_title("Agentic Commerce Hackathon")
        assert a == b == "agentic commerce hackathon"

    def test_strips_dash_introduced_trailing_text(self):
        a = fetcher._normalize_title("CockroachDB x AWS Hackathon - Build with Agentic Memory")
        b = fetcher._normalize_title("CockroachDB x AWS Hackathon")
        assert a == b

    def test_lowercases_and_strips_punctuation(self):
        assert fetcher._normalize_title("Foo! Bar? #1") == "foo bar 1"

    def test_empty_title(self):
        assert fetcher._normalize_title("") == ""
        assert fetcher._normalize_title(None) == ""


class TestDeriveEventId:
    def test_same_id_for_title_variants(self):
        item_a = {
            "title": "Agentic Commerce Hackathon (Build agents that act, shop, book, renew and pay.)",
            "host": "OpenAI",
            "event_start": "2026-08-01",
        }
        item_b = {"title": "Agentic Commerce Hackathon", "host": "OpenAI", "event_start": "2026-08-01"}
        assert fetcher.derive_event_id(item_a) == fetcher.derive_event_id(item_b)

    def test_differs_by_host(self):
        item_a = {"title": "Foo Hackathon", "host": "Acme", "event_start": "2026-08-01"}
        item_b = {"title": "Foo Hackathon", "host": "Zeta", "event_start": "2026-08-01"}
        assert fetcher.derive_event_id(item_a) != fetcher.derive_event_id(item_b)

    def test_differs_by_start_date(self):
        item_a = {"title": "Foo Hackathon", "host": "Acme", "event_start": "2026-08-01"}
        item_b = {"title": "Foo Hackathon", "host": "Acme", "event_start": "2026-09-01"}
        assert fetcher.derive_event_id(item_a) != fetcher.derive_event_id(item_b)

    def test_falls_back_to_host_and_title_without_date(self):
        item = {"title": "Foo Hackathon", "host": "Acme", "event_start": None}
        event_id = fetcher.derive_event_id(item)
        assert event_id is not None
        assert "2026" not in event_id

    def test_none_when_no_host_or_title(self):
        assert fetcher.derive_event_id({}) is None


class TestCache:
    def test_load_cache_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert fetcher.load_cache() == {}

    def test_load_cache_corrupt_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cache.json").write_text("not json{{{")
        assert fetcher.load_cache() == {}

    def test_load_cache_oldest_urls_list_format_migrates(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cache.json").write_text(
            json.dumps({"urls": ["https://a.com"], "last_updated": "x"})
        )
        cache = fetcher.load_cache()
        today = datetime.now().strftime("%Y-%m-%d")
        assert len(cache) == 1
        record = next(iter(cache.values()))
        assert record["urls"] == ["https://a.com"]
        assert record["first_seen"] == today
        assert record["last_shown"] == today
        assert record["status"] == "seen"
        assert record["resurfaced"] is False
        assert record["event_start"] is None
        assert record["event_end"] is None

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        record = {
            "event_id": "acme-foo-hack-2026-01-01",
            "urls": ["https://a.com"],
            "first_seen": "2026-01-01",
            "last_shown": "2026-01-01",
            "status": "seen",
            "resurfaced": False,
            "event_start": "2026-01-01",
            "event_end": "2026-01-02",
        }
        fetcher.save_cache({"acme-foo-hack-2026-01-01": record})
        assert fetcher.load_cache() == {"acme-foo-hack-2026-01-01": record}


class TestCacheMigrationFromFlatFormat:
    def test_flat_url_date_cache_migrates_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        flat = {
            "https://a.com/event-1/": "2026-06-01",
            "https://b.com/event-2/": "2026-06-15",
        }
        (tmp_path / "cache.json").write_text(json.dumps(flat))

        migrated = fetcher.load_cache()

        assert len(migrated) == 2
        all_urls = set()
        for record in migrated.values():
            all_urls.update(record["urls"])
            assert record["status"] == "seen"
            assert record["resurfaced"] is False
            assert record["event_start"] is None
            assert record["event_end"] is None
            assert "event_id" in record

        assert all_urls == set(flat.keys())

        by_url = {u: r for r in migrated.values() for u in r["urls"]}
        assert by_url["https://a.com/event-1/"]["first_seen"] == "2026-06-01"
        assert by_url["https://b.com/event-2/"]["first_seen"] == "2026-06-15"

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        flat = {"https://a.com/event-1/": "2026-06-01"}
        (tmp_path / "cache.json").write_text(json.dumps(flat))

        first_pass = fetcher.load_cache()
        fetcher.save_cache(first_pass)

        second_pass = fetcher.load_cache()
        assert second_pass == first_pass

    def test_no_urls_lost_across_migration(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        flat = {f"https://x{i}.devpost.com/": "2026-01-01" for i in range(20)}
        (tmp_path / "cache.json").write_text(json.dumps(flat))

        migrated = fetcher.load_cache()
        all_urls = set()
        for record in migrated.values():
            all_urls.update(record["urls"])
        assert all_urls == set(flat.keys())


class TestFetchEventsBasics:
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
            "event_start": None,
            "event_end": None,
        }

    def test_dry_run_skips_cache_read_and_write(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://example.com/event"
        today = datetime.now().strftime("%Y-%m-%d")
        record = {
            "event_id": "legacy-example-com-event",
            "urls": [url],
            "first_seen": today,
            "last_shown": today,
            "status": "seen",
            "resurfaced": False,
            "event_start": None,
            "event_end": None,
        }
        (tmp_path / "cache.json").write_text(json.dumps({record["event_id"]: record}))
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([self._make_item(url)], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        # cache not loaded -> item not suppressed despite being "cached" today
        assert len(items) == 1
        with open(tmp_path / "cache.json") as f:
            data = json.load(f)
        assert data == {record["event_id"]: record}  # untouched

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

    def test_brand_new_event_creates_record_and_is_shown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://example.com/event"
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
        with open(tmp_path / "cache.json") as f:
            saved = json.load(f)
        assert len(saved) == 1
        record = next(iter(saved.values()))
        assert record["urls"] == [url]
        assert record["status"] == "seen"
        assert record["resurfaced"] is False


class TestResurfaceLogic:
    """Date-aware resurface behaviour, replacing the old fixed-45-day-from-
    first-seen suppression: a future event stays hidden until it is within
    RESURFACE_WINDOW_DAYS of its own event_start, resurfaces exactly once
    inside that window, then stops for good once event_start has passed. A
    date-less event still falls back to the fixed CACHE_TTL_DAYS behaviour.
    """

    EVENT_ID = "acme-foo-hackathon"
    URL = "https://acme.devpost.com/"

    def _record(self, event_start=None, first_seen_days_ago=7, last_shown_days_ago=None, resurfaced=False, status="seen"):
        first_seen = (datetime.now() - timedelta(days=first_seen_days_ago)).strftime("%Y-%m-%d")
        delta = last_shown_days_ago if last_shown_days_ago is not None else first_seen_days_ago
        last_shown = (datetime.now() - timedelta(days=delta)).strftime("%Y-%m-%d")
        return {
            "event_id": self.EVENT_ID,
            "urls": [self.URL],
            "first_seen": first_seen,
            "last_shown": last_shown,
            "status": status,
            "resurfaced": resurfaced,
            "event_start": event_start,
            "event_end": None,
        }

    def _item(self, event_start=None):
        return {
            "source": "Devpost",
            "title": "Foo Hackathon",
            "url": self.URL,
            "summary": "s",
            "published": event_start or "Unknown",
            "location": "Online",
            "mode": "online",
            "host": "Acme",
            "dates": "d",
            "prize": "",
            "themes": [],
            "event_start": event_start,
            "event_end": None,
        }

    def _run(self, tmp_path, monkeypatch, record, item_event_start):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cache.json").write_text(json.dumps({record["event_id"]: record}))
        item = self._item(event_start=item_event_start)
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([item], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=False)
        with open(tmp_path / "cache.json") as f:
            saved = json.load(f)
        return items, saved[record["event_id"]]

    def test_future_event_suppressed_outside_resurface_window(self, tmp_path, monkeypatch):
        future_start = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        record = self._record(event_start=future_start, first_seen_days_ago=7)
        items, saved = self._run(tmp_path, monkeypatch, record, future_start)
        assert items == []
        assert saved["resurfaced"] is False

    def test_event_resurfaces_within_window_exactly_once(self, tmp_path, monkeypatch):
        near_start = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        record = self._record(event_start=near_start, first_seen_days_ago=20, resurfaced=False)
        items, saved = self._run(tmp_path, monkeypatch, record, near_start)
        assert len(items) == 1
        assert saved["resurfaced"] is True
        assert saved["status"] == "resurfaced"

    def test_event_does_not_resurface_twice(self, tmp_path, monkeypatch):
        near_start = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        record = self._record(event_start=near_start, first_seen_days_ago=20, resurfaced=True, status="resurfaced")
        items, saved = self._run(tmp_path, monkeypatch, record, near_start)
        assert items == []
        assert saved["resurfaced"] is True

    def test_event_stops_after_start_date_passes(self, tmp_path, monkeypatch):
        past_start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        record = self._record(event_start=past_start, first_seen_days_ago=20, resurfaced=True, status="resurfaced")
        items, saved = self._run(tmp_path, monkeypatch, record, past_start)
        assert items == []
        assert saved["status"] == "lapsed"

    def test_dateless_event_suppressed_within_45_day_fallback(self, tmp_path, monkeypatch):
        record = self._record(event_start=None, first_seen_days_ago=10, last_shown_days_ago=10)
        items, saved = self._run(tmp_path, monkeypatch, record, None)
        assert items == []

    def test_dateless_event_resurfaces_after_45_day_fallback(self, tmp_path, monkeypatch):
        record = self._record(event_start=None, first_seen_days_ago=50, last_shown_days_ago=50)
        items, saved = self._run(tmp_path, monkeypatch, record, None)
        assert len(items) == 1

    def test_newly_discovered_date_on_previously_dateless_record_is_adopted(self, tmp_path, monkeypatch):
        # Record was cached with no date; this run's fetch now carries one
        # (e.g. registration dates were published after first listing).
        record = self._record(event_start=None, first_seen_days_ago=7, last_shown_days_ago=7)
        newly_known_start = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        items, saved = self._run(tmp_path, monkeypatch, record, newly_known_start)
        assert saved["event_start"] == newly_known_start
        assert items == []  # 30 days out, outside the 14-day resurface window
