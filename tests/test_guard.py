from buildathon_radar.guard import validate_picks


def make_item(url, **overrides):
    item = {
        "source": "Devpost",
        "title": "Some Event",
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
    item.update(overrides)
    return item


class TestValidatePicks:
    def test_exact_url_match_kept_and_enriched(self):
        items = [make_item("https://example.com/e1")]
        picks = [{"url": "https://example.com/e1", "title": "Some Event", "tier": "must_see", "score": 80, "why": "great"}]
        valid, dropped = validate_picks(picks, items)
        assert len(valid) == 1
        assert dropped == []
        assert valid[0]["item"] == items[0]

    def test_fabricated_url_dropped(self):
        items = [make_item("https://example.com/e1")]
        picks = [{"url": "https://not-real.com/fake", "title": "Fake Event", "tier": "must_see", "score": 99, "why": "invented"}]
        valid, dropped = validate_picks(picks, items)
        assert valid == []
        assert len(dropped) == 1
        assert dropped[0]["url"] == "https://not-real.com/fake"

    def test_trailing_slash_variant_matched(self):
        items = [make_item("https://example.com/e1/")]
        picks = [{"url": "https://example.com/e1", "title": "Some Event", "tier": "radar", "score": 40, "why": "ok"}]
        valid, dropped = validate_picks(picks, items)
        assert len(valid) == 1
        assert dropped == []

    def test_trailing_slash_variant_matched_reverse(self):
        items = [make_item("https://example.com/e1")]
        picks = [{"url": "https://example.com/e1/", "title": "Some Event", "tier": "radar", "score": 40, "why": "ok"}]
        valid, dropped = validate_picks(picks, items)
        assert len(valid) == 1
        assert dropped == []

    def test_mixed_valid_and_invalid(self):
        items = [make_item("https://a.com/1"), make_item("https://b.com/2")]
        picks = [
            {"url": "https://a.com/1", "title": "A", "tier": "must_see", "score": 90, "why": "real"},
            {"url": "https://fake.com/x", "title": "Fake", "tier": "must_see", "score": 95, "why": "invented"},
        ]
        valid, dropped = validate_picks(picks, items)
        assert len(valid) == 1
        assert len(dropped) == 1
        assert valid[0]["url"] == "https://a.com/1"

    def test_no_substring_or_domain_fuzziness(self):
        items = [make_item("https://example.com/real-event")]
        picks = [{"url": "https://example.com/real-event-but-different", "title": "T", "tier": "radar", "score": 40, "why": "x"}]
        valid, dropped = validate_picks(picks, items)
        assert valid == []
        assert len(dropped) == 1
