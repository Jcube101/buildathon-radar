from buildathon_radar.digest import build_digest, build_html_digest


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


class TestHtmlDigestGmailCompatibility:
    def test_table_based_no_flex_or_grid(self):
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        html = build_html_digest(picks, [], {"Devpost": {"count": 1, "error": None}}, "note")
        assert "<table" in html
        assert "display:flex" not in html
        assert "display: flex" not in html
        assert "display:grid" not in html

    def test_no_style_block_and_no_external_assets(self):
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        html = build_html_digest(picks, [], {"Devpost": {"count": 1, "error": None}}, "note")
        assert "<style" not in html
        assert "<script" not in html
        assert "<link" not in html
        assert "fonts.googleapis" not in html

    def test_system_font_stack_present(self):
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        html = build_html_digest(picks, [], {"Devpost": {"count": 1, "error": None}}, "note")
        assert "-apple-system, Roboto, 'Helvetica Neue', Arial, sans-serif" in html

    def test_all_cells_have_explicit_background_color(self):
        item = make_item("https://a.com/1")
        picks = [make_pick(item)]
        html = build_html_digest(picks, [], {"Devpost": {"count": 1, "error": None}}, "note")
        import re
        for td in re.findall(r"<td[^>]*style=\"([^\"]*)\"", html):
            assert "background-color" in td


class TestHtmlDigestTealTheme:
    def test_masthead_teal_and_title(self):
        html = build_html_digest([], [], {"Devpost": {"count": 0, "error": None}}, "")
        assert "#0f4c4c" in html
        assert "Buildathon Radar" in html

    def test_page_background(self):
        html = build_html_digest([], [], {"Devpost": {"count": 0, "error": None}}, "")
        assert "#f6f4ef" in html

    def test_tier_stripe_colors(self):
        item1 = make_item("https://a.com/1")
        item2 = make_item("https://b.com/2")
        item3 = make_item("https://c.com/3")
        picks = [
            make_pick(item1, tier="must_see", score=90),
            make_pick(item2, tier="worth_a_look", score=60),
            make_pick(item3, tier="radar", score=40),
        ]
        html = build_html_digest(picks, [], {"Devpost": {"count": 3, "error": None}}, "")
        assert "#0d9488" in html  # must_see stripe (and score badge)
        assert "#5b8a8a" in html  # worth_a_look stripe
        assert "#8fa6a6" in html  # radar stripe

    def test_date_range_subtitle_rendered(self):
        html = build_html_digest([], [], {"Devpost": {"count": 0, "error": None}}, "", "Jul 1 - 7, 2026")
        assert "Jul 1 - 7, 2026" in html


class TestHtmlDigestCardStructure:
    def test_card_facts_from_source_item_not_claude(self):
        item = make_item("https://a.com/1", title="Real Devpost Title")
        pick = make_pick(item, claude_title="Something Claude Made Up")
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert "Real Devpost Title" in html
        assert "Something Claude Made Up" not in html

    def test_score_badge_and_source_present(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item, score=87)
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert ">87<" in html
        assert "via Devpost" in html

    def test_why_row_present_with_tint_when_why_given(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item, why="Matters a lot.")
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert "Matters a lot." in html
        assert "#eaf3f1" in html

    def test_why_row_absent_when_no_why(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item, why="")
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert "#eaf3f1" not in html

    def test_dynamic_content_is_html_escaped(self):
        item = make_item("https://a.com/1", title="<script>alert(1)</script> & Co", host="A & B Corp")
        pick = make_pick(item)
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "A &amp; B Corp" in html


class TestHtmlDigestFooterAndDegradation:
    def test_source_health_footer_present(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item)
        health = {"Devpost": {"count": 3, "error": None}, "Devfolio": {"count": 7, "error": None}}
        html = build_html_digest([pick], [], health, "")
        assert "Devpost: 3 new events" in html
        assert "Devfolio: 7 new events" in html

    def test_failed_source_shown_in_footer(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item)
        health = {"Devpost": {"count": 1, "error": None}, "Devfolio": {"count": 0, "error": "Connection timeout"}}
        html = build_html_digest([pick], [], health, "")
        assert "FAILED (Connection timeout)" in html

    def test_integrity_line_present_when_dropped(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item)
        dropped = [{"url": "https://fake.com/x", "title": "Fake", "tier": "must_see", "score": 99, "why": "invented"}]
        html = build_html_digest([pick], dropped, {"Devpost": {"count": 1, "error": None}}, "")
        assert "Integrity guard: 1 pick(s) dropped" in html

    def test_quiet_week_body_when_no_picks(self):
        html = build_html_digest([], [], {"Devpost": {"count": 0, "error": None}, "Devfolio": {"count": 0, "error": None}}, "")
        assert "Quiet week" in html

    def test_intro_week_note_preserved(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item)
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "A strong week.")
        assert "A strong week." in html


class TestHtmlDigestMobileWrapping:
    def test_outer_container_is_fluid_not_fixed_width(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item)
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert 'width="600"' not in html
        assert "width:600px; max-width:600px" not in html  # old fixed-width style
        assert 'width="100%"' in html
        assert "width:100%; max-width:600px" in html

    def test_viewport_meta_present(self):
        html = build_html_digest([], [], {"Devpost": {"count": 0, "error": None}}, "")
        assert 'name="viewport"' in html
        assert "width=device-width" in html

    def test_title_meta_dates_why_have_word_break(self):
        item = make_item(
            "https://a.com/1",
            title="Averylongunbrokenhackathontitlewithnospacesatallwhatsoever",
            prize="Most Startup-Ready Product, Best Agentic Payments Product, Best Project, Second Place, Third Place",
        )
        pick = make_pick(item, why="A fairly long why line that could also run wide on a narrow phone screen if unconstrained.")
        html = build_html_digest([pick], [], {"Devpost": {"count": 1, "error": None}}, "")
        assert html.count("word-break:break-word") >= 5
        assert html.count("overflow-wrap:break-word") >= 5

    def test_footer_health_line_has_word_break(self):
        item = make_item("https://a.com/1")
        pick = make_pick(item)
        health = {"Devpost": {"count": 1, "error": None}, "Devfolio": {"count": 0, "error": "Connection timeout while fetching a very long error message"}}
        html = build_html_digest([pick], [], health, "")
        footer_section = html[html.rfind("Source health"):]
        assert "word-break:break-word" in footer_section
