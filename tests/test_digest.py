from buildathon_radar.digest import build_digest


def make_item(url, title="Source Title", **overrides):
    item = {
        "source": "Devpost",
        "title": title,
        "url": url,
        "summary": "s",
        "published": "2026-01-01",
        "location": "Bengaluru, India",
        "mode": "in-person",
        "host": "Some Host",
        "dates": "Jul 18, 2026",
        "prize": "$1,000",
        "themes": ["Machine Learning/AI"],
    }
    item.update(overrides)
    return item


def make_pick(item, tier="must_see", score=80, why="matters", claude_title="Claude's Guess"):
    return {
        "url": item["url"],
        "title": claude_title,
        "tier": tier,
        "score": score,
        "scoring": {},
        "why": why,
        "item": item,
    }


class TestCardFactsFromSourceItem:
    def test_title_comes_from_source_item_not_claude(self):
        item = make_item("https://a.com/1", title="Real Devpost Title")
        pick = make_pick(item, claude_title="Something Claude Made Up")
        digest = build_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "note")
        assert "Real Devpost Title" in digest
        assert "Something Claude Made Up" not in digest

    def test_host_location_dates_prize_from_item(self):
        item = make_item("https://a.com/1", host="IEEE", location="Bengaluru, India", dates="Jul 18, 2026", prize="Overall Prize")
        pick = make_pick(item)
        digest = build_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert "IEEE" in digest
        assert "Bengaluru, India" in digest
        assert "Jul 18, 2026" in digest
        assert "Overall Prize" in digest


class TestSectionOrderingAndSort:
    def test_sections_appear_in_tier_order(self):
        item1 = make_item("https://a.com/1")
        item2 = make_item("https://b.com/2")
        item3 = make_item("https://c.com/3")
        picks = [
            make_pick(item1, tier="radar", score=40),
            make_pick(item2, tier="must_see", score=90),
            make_pick(item3, tier="worth_a_look", score=60),
        ]
        digest = build_digest(picks, [], {"Devpost": {"count": 3, "error": None}}, "")
        must_pos = digest.find("Must-see")
        worth_pos = digest.find("Worth a look")
        radar_pos = digest.find("On the radar")
        assert must_pos < worth_pos < radar_pos

    def test_within_section_sorted_by_score_descending(self):
        item1 = make_item("https://a.com/1", title="Low Score Event")
        item2 = make_item("https://b.com/2", title="High Score Event")
        picks = [
            make_pick(item1, tier="must_see", score=71),
            make_pick(item2, tier="must_see", score=95),
        ]
        digest = build_digest(picks, [], {"Devpost": {"count": 2, "error": None}}, "")
        assert digest.find("High Score Event") < digest.find("Low Score Event")

    def test_empty_tier_section_omitted(self):
        item1 = make_item("https://a.com/1")
        picks = [make_pick(item1, tier="must_see", score=90)]
        digest = build_digest(picks, [], {"Devpost": {"count": 1, "error": None}}, "")
        assert "Worth a look" not in digest
        assert "On the radar" not in digest


class TestQuietWeekAndDegradation:
    def test_zero_picks_all_healthy_quiet_week(self):
        health = {"Devpost": {"count": 0, "error": None}, "Devfolio": {"count": 0, "error": None}}
        digest = build_digest([], [], health, "")
        assert "Quiet week" in digest

    def test_zero_picks_all_sources_failed(self):
        health = {
            "Devpost": {"count": 0, "error": "Connection timeout"},
            "Devfolio": {"count": 0, "error": "HTTP 503"},
        }
        digest = build_digest([], [], health, "")
        assert "All sources failed" in digest

    def test_failed_source_footer_flagged(self):
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        health = {
            "Devpost": {"count": 1, "error": None},
            "Devfolio": {"count": 0, "error": "Connection timeout"},
        }
        digest = build_digest(picks, [], health, "")
        assert "FAILED (Connection timeout)" in digest
        assert "⚠️" in digest

    def test_zero_result_healthy_source_flagged(self):
        health = {"Devpost": {"count": 0, "error": None}, "Devfolio": {"count": 5, "error": None}}
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        digest = build_digest(picks, [], health, "")
        assert "Devpost: 0 new events ⚠️" in digest

    def test_healthy_source_never_silently_dropped_from_footer(self):
        health = {"Devpost": {"count": 3, "error": None}, "Devfolio": {"count": 7, "error": None}}
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        digest = build_digest(picks, [], health, "")
        assert "Devpost: 3 new events" in digest
        assert "Devfolio: 7 new events" in digest


class TestIntegrityLine:
    def test_no_integrity_line_when_no_drops(self):
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        digest = build_digest(picks, [], {"Devpost": {"count": 1, "error": None}}, "")
        assert "Integrity guard" not in digest

    def test_integrity_line_renders_when_drops_exist(self):
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        dropped = [{"url": "https://fake.com/x", "title": "Fake", "tier": "must_see", "score": 99, "why": "invented"}]
        digest = build_digest(picks, dropped, {"Devpost": {"count": 1, "error": None}}, "")
        assert "Integrity guard:** 1 pick(s) dropped" in digest
