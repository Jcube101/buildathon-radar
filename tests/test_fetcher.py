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


class TestEventIdPassthrough:
    """The v2 tracker keys off the same event_id fetch_events derives
    internally for the cache, so every returned item must carry it."""

    def _make_item(self, url, **overrides):
        item = {
            "source": "Devpost",
            "title": "Some Hackathon",
            "url": url,
            "summary": "s",
            "published": "2026-01-01",
            "location": "Online",
            "mode": "online",
            "host": "Acme",
            "dates": "d",
            "prize": "",
            "themes": [],
            "event_start": "2026-08-01",
            "event_end": None,
        }
        item.update(overrides)
        return item

    def test_brand_new_item_carries_event_id_matching_derive_event_id(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://acme.devpost.com/"
        item = self._make_item(url)
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([item], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        assert len(items) == 1
        assert items[0]["event_id"]
        assert items[0]["event_id"] == fetcher.derive_event_id(item)

    def test_resurfaced_item_carries_the_same_event_id_as_the_cache_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://acme.devpost.com/"
        near_start = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        event_id = "acme foo-hackathon"
        record = {
            "event_id": event_id,
            "urls": [url],
            "first_seen": (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
            "last_shown": (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
            "status": "seen",
            "resurfaced": False,
            "event_start": near_start,
            "event_end": None,
        }
        (tmp_path / "cache.json").write_text(json.dumps({event_id: record}))
        item = self._make_item(url, event_start=near_start)
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([item], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=False)
        assert len(items) == 1
        assert items[0]["event_id"] == event_id

    def test_legacy_fallback_id_used_when_no_host_or_title(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://example.com/no-metadata-event"
        item = self._make_item(url, title="", host="")
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([item], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        assert len(items) == 1
        assert items[0]["event_id"] == fetcher._legacy_event_id(url)


class TestUrlCanonicalize:
    def test_lu_ma_host_folds_to_luma_com(self):
        assert fetcher._canonicalize_url("https://lu.ma/abc123") == "https://luma.com/abc123"

    def test_luma_com_unchanged(self):
        assert fetcher._canonicalize_url("https://luma.com/abc123") == "https://luma.com/abc123"

    def test_http_upgraded_to_https(self):
        assert fetcher._canonicalize_url("http://example.devpost.com/") == "https://example.devpost.com/"

    def test_whitespace_stripped(self):
        assert fetcher._canonicalize_url("  https://a.com/x  ") == "https://a.com/x"

    def test_empty_and_none_passthrough(self):
        assert fetcher._canonicalize_url("") == ""
        assert fetcher._canonicalize_url(None) is None

    def test_non_luma_domain_unaffected(self):
        assert fetcher._canonicalize_url("https://example.devpost.com/") == "https://example.devpost.com/"


class TestNormaliseLuma:
    def _entry(self, name):
        data = load_fixture("luma_place_sample.json")
        for e in data["entries"]:
            if e["event"]["name"] == name:
                return e
        raise AssertionError(f"fixture entry not found: {name}")

    def test_real_fixture_item_india_builds_with_claude(self):
        entry = self._entry("India Builds with Claude - Razorpay | Anthropic | Peak XV")
        n = fetcher.normalise_luma(entry)
        assert n["source"] == "Luma"
        assert n["url"] == "https://luma.com/8v8l5x5g"
        assert n["mode"] == "in-person"
        assert n["location"] == "Bengaluru, India"
        _assert_no_unexpected_nones(n)

    def test_host_falls_back_to_first_named_host_when_calendar_is_personal(self):
        entry = self._entry("India Builds with Claude - Razorpay | Anthropic | Peak XV")
        n = fetcher.normalise_luma(entry)
        assert n["host"] == "Vineet Agarwal"

    def test_host_uses_calendar_name_when_not_personal(self):
        entry = self._entry("Docusign Developers Meetup")
        n = fetcher.normalise_luma(entry)
        assert n["host"] == "Docusign Developers"

    def test_host_unknown_when_no_calendar_or_hosts(self):
        entry = {"event": {"name": "T", "url": "x"}, "calendar": {}, "hosts": []}
        n = fetcher.normalise_luma(entry)
        assert n["host"] == "Unknown"

    def test_url_construction_from_slug(self):
        entry = {"event": {"name": "T", "url": "myslug"}, "calendar": {}, "hosts": []}
        n = fetcher.normalise_luma(entry)
        assert n["url"] == "https://luma.com/myslug"

    def test_missing_fields_fallback(self):
        n = fetcher.normalise_luma({})
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

    def test_online_mode_detection(self):
        entry = {"event": {"name": "T", "url": "x", "location_type": "online"}, "calendar": {}, "hosts": []}
        n = fetcher.normalise_luma(entry)
        assert n["mode"] == "online"
        assert n["location"] == "Online"

    def test_utc_to_ist_date_conversion(self):
        entry = {
            "event": {
                "name": "T",
                "url": "x",
                "start_at": "2026-07-16T12:30:00.000Z",
                "end_at": "2026-07-16T15:30:00.000Z",
            },
            "calendar": {},
            "hosts": [],
        }
        n = fetcher.normalise_luma(entry)
        # 12:30 UTC -> 18:00 IST, same calendar day
        assert n["event_start"] == "2026-07-16"
        assert n["event_end"] == "2026-07-16"

    def test_late_utc_time_crosses_ist_day_boundary(self):
        entry = {
            "event": {
                "name": "T",
                "url": "x",
                "start_at": "2026-07-16T19:00:00.000Z",  # 00:30 IST next day
            },
            "calendar": {},
            "hosts": [],
        }
        n = fetcher.normalise_luma(entry)
        assert n["event_start"] == "2026-07-17"


class TestFetchLuma:
    def test_dedupes_by_api_id_across_pages(self, monkeypatch):
        entry = {
            "event": {"api_id": "evt-1", "name": "T", "url": "x", "visibility": "public"},
            "calendar": {},
            "hosts": [],
        }
        page1 = {"entries": [entry], "has_more": True, "next_cursor": "c1"}
        page2 = {"entries": [entry], "has_more": False, "next_cursor": None}
        responses = iter([page1, page2])

        class FakeResp:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        def fake_get(url, params=None, headers=None, timeout=None):
            return FakeResp(next(responses))

        monkeypatch.setattr(fetcher.requests, "get", fake_get)
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        items, error = fetcher.fetch_luma()
        assert error is None
        assert len(items) == 1

    def test_skips_non_public_visibility(self, monkeypatch):
        public_entry = {
            "event": {"api_id": "evt-1", "name": "Public", "url": "a", "visibility": "public"},
            "calendar": {}, "hosts": [],
        }
        private_entry = {
            "event": {"api_id": "evt-2", "name": "Private", "url": "b", "visibility": "private"},
            "calendar": {}, "hosts": [],
        }

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"entries": [public_entry, private_entry], "has_more": False, "next_cursor": None}

        monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: FakeResp())
        items, error = fetcher.fetch_luma()
        assert error is None
        assert len(items) == 1
        assert items[0]["title"] == "Public"

    def test_per_item_error_skipped(self, monkeypatch):
        good = {"event": {"api_id": "evt-1", "name": "Good", "url": "a", "visibility": "public"}, "calendar": {}, "hosts": []}
        bad = {"event": {"api_id": "evt-2", "visibility": "public"}, "calendar": None, "hosts": None}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"entries": [good, bad], "has_more": False, "next_cursor": None}

        monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: FakeResp())

        real_normalise = fetcher.normalise_luma

        def spy_normalise(entry):
            if entry is bad:
                raise Exception("boom")
            return real_normalise(entry)

        monkeypatch.setattr(fetcher, "normalise_luma", spy_normalise)
        items, error = fetcher.fetch_luma()
        assert error is None
        assert len(items) == 1
        assert items[0]["title"] == "Good"

    def test_request_failure_returns_error_shape(self, monkeypatch):
        monkeypatch.setattr(fetcher.requests, "get", _raise)
        items, error = fetcher.fetch_luma()
        assert items == []
        assert error == "boom"

    def test_stops_after_five_pages_even_if_has_more(self, monkeypatch):
        call_count = {"n": 0}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                call_count["n"] += 1
                return {
                    "entries": [{
                        "event": {"api_id": f"evt-{call_count['n']}", "name": "T", "url": "x", "visibility": "public"},
                        "calendar": {}, "hosts": [],
                    }],
                    "has_more": True,
                    "next_cursor": f"cursor-{call_count['n']}",
                }

        monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: FakeResp())
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        items, error = fetcher.fetch_luma()
        assert error is None
        assert call_count["n"] == 5


class TestCvPrefilter:
    def test_featured_fetch_tag_always_passes(self):
        assert fetcher._cv_passes_prefilter({"_cv_featured_fetch": True, "location": "Other"})

    def test_cv_event_flag_passes(self):
        assert fetcher._cv_passes_prefilter({"CVEvent": True, "location": "Other"})

    def test_hackathon_type_passes(self):
        assert fetcher._cv_passes_prefilter({"type": "HACKATHON", "location": "Other"})
        assert fetcher._cv_passes_prefilter({"type": "hackathon", "location": "Other"})

    def test_india_location_passes(self):
        assert fetcher._cv_passes_prefilter({"location": "Bengaluru, India"})
        assert fetcher._cv_passes_prefilter({"location": "Mumbai, India"})

    def test_remote_passes(self):
        assert fetcher._cv_passes_prefilter({"location": "Remote"})

    def test_generic_us_conference_dropped(self):
        assert not fetcher._cv_passes_prefilter({"location": "San Francisco, CA", "type": None})

    def test_real_fixture_entries(self):
        data = load_fixture("cv_approved_sample.json")
        by_name = {e["name"]: e for e in data["events"]}
        assert fetcher._cv_passes_prefilter(by_name["Encode Hackathon and Conference"])
        assert not fetcher._cv_passes_prefilter(by_name["AI Builders Berlin"])


class TestCvInWindow:
    TODAY = "2026-07-15"
    HORIZON = "2026-09-13"

    def test_future_within_window_kept(self):
        assert fetcher._cv_in_window({"startDateTime": "2026-08-01 00:00:00"}, self.TODAY, self.HORIZON)

    def test_beyond_horizon_dropped(self):
        assert not fetcher._cv_in_window({"startDateTime": "2028-01-01 00:00:00"}, self.TODAY, self.HORIZON)

    def test_no_start_date_dropped(self):
        assert not fetcher._cv_in_window({"startDateTime": ""}, self.TODAY, self.HORIZON)

    def test_started_but_still_ongoing_kept(self):
        entry = {"startDateTime": "2026-07-01 00:00:00", "endDateTime": "2026-07-20 00:00:00"}
        assert fetcher._cv_in_window(entry, self.TODAY, self.HORIZON)

    def test_already_ended_dropped(self):
        entry = {"startDateTime": "2026-07-01 00:00:00", "endDateTime": "2026-07-10 00:00:00"}
        assert not fetcher._cv_in_window(entry, self.TODAY, self.HORIZON)


class TestNormaliseCerebralValley:
    def test_real_fixture_hackathon(self):
        data = load_fixture("cv_approved_sample.json")
        entry = next(e for e in data["events"] if e["name"] == "Encode Hackathon and Conference")
        n = fetcher.normalise_cerebralvalley(entry)
        assert n["source"] == "Cerebral Valley"
        assert n["url"] == "https://luma.com/encode-london-2026"  # canonicalized from lu.ma if applicable
        assert n["themes"] == ["Hackathon"]
        assert n["host"] == "Unknown"
        _assert_no_unexpected_nones(n)

    def test_lu_ma_url_canonicalized(self):
        data = load_fixture("cv_approved_sample.json")
        entry = next(e for e in data["events"] if e["name"] == "AI Builders Berlin")
        n = fetcher.normalise_cerebralvalley(entry)
        assert n["url"] == "https://luma.com/berlin-oct20"

    def test_featured_tag_adds_theme(self):
        entry = {"name": "T", "url": "https://a.com", "_cv_featured_fetch": True}
        n = fetcher.normalise_cerebralvalley(entry)
        assert "Cerebral Valley Featured" in n["themes"]

    def test_remote_maps_to_online(self):
        entry = {"name": "T", "url": "https://a.com", "location": "Remote"}
        n = fetcher.normalise_cerebralvalley(entry)
        assert n["location"] == "Online"
        assert n["mode"] == "online"

    def test_missing_fields_fallback(self):
        n = fetcher.normalise_cerebralvalley({})
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

    def test_summary_falls_back_to_description_then_title(self):
        entry = {"name": "T", "url": "https://a.com", "description": "Long form text."}
        n = fetcher.normalise_cerebralvalley(entry)
        assert n["summary"] == "Long form text."
        entry2 = {"name": "T", "url": "https://a.com"}
        n2 = fetcher.normalise_cerebralvalley(entry2)
        assert n2["summary"] == "T"

    def test_date_parts_extracted_from_naive_datetime_strings(self):
        entry = {
            "name": "T", "url": "https://a.com",
            "startDateTime": "2026-08-01 18:00:00", "endDateTime": "2026-08-02 02:00:00",
        }
        n = fetcher.normalise_cerebralvalley(entry)
        assert n["event_start"] == "2026-08-01"
        assert n["event_end"] == "2026-08-02"
        assert n["dates"] == "Aug 01, 2026 to Aug 02, 2026"


class TestFetchCerebralValley:
    def _fake_responses(self, featured, count, pages):
        """pages: list of event-lists returned in order for successive
        approved-window requests."""
        calls = {"n": 0}
        page_iter = iter(pages)

        class FakeResp:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        def fake_get(url, params=None, headers=None, timeout=None):
            if params.get("featured"):
                return FakeResp({"events": featured})
            if params.get("limit") == 1:
                return FakeResp({"totalCount": count})
            return FakeResp({"events": next(page_iter)})

        return fake_get

    def test_featured_and_hackathon_kept_conference_dropped(self, monkeypatch):
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        page = [
            {"id": "1", "name": "Featured-window Hackathon", "url": "https://a.com/1",
             "type": "HACKATHON", "location": "London, UK", "startDateTime": f"{future} 00:00:00"},
            {"id": "2", "name": "Generic US Conference", "url": "https://a.com/2",
             "type": None, "location": "San Francisco, CA", "startDateTime": f"{future} 00:00:00"},
        ]
        fake_get = self._fake_responses(featured=[], count=100, pages=[page])
        monkeypatch.setattr(fetcher.requests, "get", fake_get)
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        items, error = fetcher.fetch_cerebralvalley()
        assert error is None
        titles = [i["title"] for i in items]
        assert "Featured-window Hackathon" in titles
        assert "Generic US Conference" not in titles

    def test_featured_events_always_included(self, monkeypatch):
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        featured = [{"id": "f1", "name": "Featured Thing", "url": "https://a.com/f1",
                     "location": "San Francisco, CA", "startDateTime": f"{future} 00:00:00"}]
        fake_get = self._fake_responses(featured=featured, count=100, pages=[[]])
        monkeypatch.setattr(fetcher.requests, "get", fake_get)
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        items, error = fetcher.fetch_cerebralvalley()
        assert error is None
        assert any(i["title"] == "Featured Thing" for i in items)
        assert any("Cerebral Valley Featured" in i["themes"] for i in items)

    def test_empty_url_skipped(self, monkeypatch):
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        page = [{"id": "1", "name": "No URL Hackathon", "url": "",
                 "type": "HACKATHON", "location": "London, UK", "startDateTime": f"{future} 00:00:00"}]
        fake_get = self._fake_responses(featured=[], count=100, pages=[page])
        monkeypatch.setattr(fetcher.requests, "get", fake_get)
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        items, error = fetcher.fetch_cerebralvalley()
        assert error is None
        assert items == []

    def test_dedupes_by_id(self, monkeypatch):
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        entry = {"id": "dup", "name": "Dup Hackathon", "url": "https://a.com/dup",
                  "type": "HACKATHON", "location": "London, UK", "startDateTime": f"{future} 00:00:00"}
        featured = [entry]
        page = [entry]
        fake_get = self._fake_responses(featured=featured, count=100, pages=[page])
        monkeypatch.setattr(fetcher.requests, "get", fake_get)
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        items, error = fetcher.fetch_cerebralvalley()
        assert error is None
        assert len(items) == 1

    def test_request_failure_returns_error_shape(self, monkeypatch):
        monkeypatch.setattr(fetcher.requests, "get", _raise)
        items, error = fetcher.fetch_cerebralvalley()
        assert items == []
        assert error == "boom"

    def test_tail_paging_stops_when_page_crosses_into_past(self, monkeypatch):
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        past = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        future_page = [{"id": "1", "name": "Future Hackathon", "url": "https://a.com/1",
                        "type": "HACKATHON", "location": "London, UK", "startDateTime": f"{future} 00:00:00"}]
        past_page = [{"id": "2", "name": "Past Hackathon", "url": "https://a.com/2",
                     "type": "HACKATHON", "location": "London, UK", "startDateTime": f"{past} 00:00:00"}]
        # totalCount=200 with page limit 100 -> first page at offset=100 (future),
        # second page at offset=0 (past); paging should stop after crossing into the past
        fake_get = self._fake_responses(featured=[], count=200, pages=[future_page, past_page])
        monkeypatch.setattr(fetcher.requests, "get", fake_get)
        monkeypatch.setattr(fetcher.time, "sleep", lambda s: None)
        items, error = fetcher.fetch_cerebralvalley()
        assert error is None
        titles = [i["title"] for i in items]
        assert "Future Hackathon" in titles
        assert "Past Hackathon" not in titles  # outside the upcoming window, filtered by _cv_in_window


class TestExactTitleMerge:
    """Minimal cross-source collision handling (ROADMAP.md 2.6). Both
    scenarios below are reconstructed from real events observed live during
    the sourcing recon on 2026-07-15 (docs/V2-SOURCING-PLAN.md section 3)."""

    def _item(self, source, title, url, host, event_start, **overrides):
        item = {
            "source": source,
            "title": title,
            "url": url,
            "summary": "s",
            "published": event_start or "Unknown",
            "location": "Online",
            "mode": "online",
            "host": host,
            "dates": "d",
            "prize": "",
            "themes": [],
            "event_start": event_start,
            "event_end": None,
        }
        item.update(overrides)
        return item

    def test_gemini_xprize_scenario_merges_to_one_item(self, tmp_path, monkeypatch):
        """Real recon finding: "Build with Gemini XPRIZE" appeared on Devpost
        (event_start 2026-05-19, host XPRIZE) and Cerebral Valley
        (event_start 2026-08-17, no host), exactly 90 days apart, the
        boundary of TITLE_MERGE_WINDOW_DAYS. Devpost runs first in SOURCES,
        so its item is the one that should survive; the second occurrence
        must not double the digest."""
        monkeypatch.chdir(tmp_path)
        devpost_item = self._item(
            "Devpost", "Build with Gemini XPRIZE", "https://xprize.devpost.com/",
            "XPRIZE", "2026-05-19",
        )
        cv_item = self._item(
            "Cerebral Valley", "Build with Gemini XPRIZE", "https://cerebralvalley.ai/e/xprize",
            "Unknown", "2026-08-17",
        )
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([devpost_item], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
                {"name": "Cerebral Valley", "fetch": lambda: ([cv_item], None)},
                {"name": "Luma", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=False)
        assert len(items) == 1
        assert items[0]["source"] == "Devpost"  # earlier-priority source wins

        with open(tmp_path / "cache.json") as f:
            saved = json.load(f)
        assert len(saved) == 1  # one record, not two
        record = next(iter(saved.values()))
        assert set(record["urls"]) == {
            "https://xprize.devpost.com/",
            "https://cerebralvalley.ai/e/xprize",
        }

    def test_ai_4_earth_vs_ai_internship_near_miss_stays_two_items(self, tmp_path, monkeypatch):
        """Real recon finding: these two events share 67% of their
        normalized words and fall on the same date, but are genuinely
        different events. Exact-title-only matching (no fuzzy scoring) must
        keep them separate."""
        monkeypatch.chdir(tmp_path)
        item_a = self._item(
            "Devpost", "GatewayGS & The AEI Initiative: AI 4 Earth Hackathon",
            "https://a.devpost.com/", "GatewayGS", "2026-07-25",
        )
        item_b = self._item(
            "Luma", "AI Internship Hackathon", "https://luma.com/xyz",
            "AI House", "2026-07-25",
        )
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([item_a], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
                {"name": "Luma", "fetch": lambda: ([item_b], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        assert len(items) == 2

    def test_cv_link_to_luma_url_collapses_via_canonicalized_url_index(self, tmp_path, monkeypatch):
        luma_item = fetcher.normalise_luma({
            "event": {"api_id": "evt-1", "name": "Shared Event", "url": "abc123"},
            "calendar": {}, "hosts": [],
        })
        cv_item = fetcher.normalise_cerebralvalley({
            "id": "cv-1", "name": "Shared Event", "url": "https://lu.ma/abc123",
        })
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
                {"name": "Cerebral Valley", "fetch": lambda: ([cv_item], None)},
                {"name": "Luma", "fetch": lambda: ([luma_item], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        assert len(items) == 1

    def test_legacy_cache_record_without_norm_title_still_loads_and_functions(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        url = "https://acme.devpost.com/"
        legacy_record = {
            "event_id": "acme-foo-hackathon-2026-08-01",
            "urls": [url],
            "first_seen": "2026-06-01",
            "last_shown": "2026-06-01",
            "status": "seen",
            "resurfaced": False,
            "event_start": "2026-08-01",
            "event_end": None,
            # no norm_title key, simulating a pre-Phase-4 cache record
        }
        (tmp_path / "cache.json").write_text(json.dumps({legacy_record["event_id"]: legacy_record}))
        item = self._item("Devpost", "Foo Hackathon", url, "Acme", "2026-08-01")
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([item], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=False)  # must not raise
        with open(tmp_path / "cache.json") as f:
            saved = json.load(f)
        record = saved[legacy_record["event_id"]]
        assert record["norm_title"] == "foo hackathon"  # acquired on this touch

    def test_same_run_duplicate_within_resurface_window_shows_once(self, tmp_path, monkeypatch):
        """Guards the same-run edge case _should_show alone cannot detect:
        two sources discover the same title for the first time, ever, and
        its date happens to fall inside the resurface window. Without the
        ids_shown_this_run guard, the second source's occurrence would also
        pass _should_show (since the brand-new record has resurfaced=False),
        producing a same-digest duplicate."""
        monkeypatch.chdir(tmp_path)
        near_start = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        item_a = self._item("Devpost", "Same Event", "https://a.devpost.com/", "Acme", near_start)
        item_b = self._item("Luma", "Same Event", "https://luma.com/same", "Acme", near_start)
        monkeypatch.setattr(
            fetcher,
            "SOURCES",
            [
                {"name": "Devpost", "fetch": lambda: ([item_a], None)},
                {"name": "Devfolio", "fetch": lambda: ([], None)},
                {"name": "Luma", "fetch": lambda: ([item_b], None)},
            ],
        )
        items, health = fetcher.fetch_events(dry_run=True)
        assert len(items) == 1


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
