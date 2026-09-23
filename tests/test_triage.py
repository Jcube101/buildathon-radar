import sqlite3
from datetime import date

import pytest

from buildathon_radar import triage


def make_item(**overrides):
    item = {
        "source": "Devpost",
        "title": "AI Agents Hackathon",
        "url": "https://example.com/e1",
        "summary": "Build AI agents",
        "published": "2026-09-01",
        "location": "Bengaluru, India",
        "mode": "in-person",
        "host": "Acme Labs",
        "dates": "Oct 1 - Oct 15, 2026",
        "prize": "$25,000 in prizes",
        "themes": ["Machine Learning/AI"],
        "event_start": "2026-10-01",
        "event_end": "2026-10-15",
    }
    item.update(overrides)
    return item


class FakeChoice:
    type = "choice"

    def __init__(self, choice, confidence=0.9):
        self.choice = choice
        self.confidence = confidence


class FakeScore:
    type = "score"

    def __init__(self, score, confidence=0.9):
        self.score = score
        self.confidence = confidence


class FakeNoul:
    type = "noul"

    def __init__(self, noul):
        self.noul = noul


class FakeResponse:
    def __init__(self, answers, model="jev-1.13.0"):
        self.answers = answers
        self.model = model


class FakeClient:
    """Stands in for TypeSafeClient. No network call is ever made in tests."""

    def __init__(self, response=None, raises=None):
        self.response = response
        self.raises = raises
        self.calls = []

    def system_one(self, state, questions, **kwargs):
        self.calls.append((state, questions))
        if self.raises:
            raise self.raises
        return self.response


def response_with(fit, category="ai_agents_llm", remote=0.9, prize=0.95):
    answers = {
        "category": FakeChoice(category),
        "fit_score": FakeScore(fit),
        "is_remote": FakeNoul(remote),
        "has_real_prize": FakeNoul(prize),
    }
    return FakeResponse(answers)


class TestModelPinning:
    def test_model_is_pinned_not_latest(self):
        # A floating alias would let triage behaviour shift without a commit.
        assert triage.JEV_MODEL == "jev-1.13.0"
        assert "latest" not in triage.JEV_MODEL


def response_with_category(category, confidence, fit=1.5):
    return FakeResponse(
        {
            "category": FakeChoice(category, confidence=confidence),
            "fit_score": FakeScore(fit),
            "is_remote": FakeNoul(0.5),
            "has_real_prize": FakeNoul(0.5),
        }
    )


class TestGate:
    def test_confident_student_college_drops(self):
        # Mirrors exclusion 1 in agent.py, which rejects these outright.
        client = FakeClient(response_with_category("student_college", 0.92))
        v = triage.triage_item(client, make_item())
        assert v["passed"] is False
        assert "student_college" in v["reason"]

    def test_student_college_below_confidence_floor_is_kept(self):
        client = FakeClient(response_with_category("student_college", 0.55))
        v = triage.triage_item(client, make_item())
        assert v["passed"] is True
        assert "0.55" in v["reason"]

    def test_confidence_exactly_at_floor_drops(self):
        client = FakeClient(
            response_with_category("student_college", triage.MIN_DROP_CONFIDENCE)
        )
        assert triage.triage_item(client, make_item())["passed"] is False

    @pytest.mark.parametrize(
        "category",
        [
            "ai_agents_llm",
            "ai_other",
            "general_swe",
            "fintech",
            "hardware_iot",
            "community_social",
            "other",
        ],
    )
    def test_non_student_categories_all_pass(self, category):
        client = FakeClient(response_with_category(category, 0.99))
        assert triage.triage_item(client, make_item())["passed"] is True

    def test_low_fit_score_alone_never_drops(self):
        # fit_score is logged for calibration, never gated on. A 0.1 here
        # would have been dropped under the old threshold gate.
        client = FakeClient(response_with(0.1, category="community_social"))
        v = triage.triage_item(client, make_item())
        assert v["passed"] is True
        assert v["fit_score"] == 0.1

    def test_high_fit_score_does_not_rescue_student_college(self):
        client = FakeClient(response_with_category("student_college", 0.95, fit=3.0))
        assert triage.triage_item(client, make_item())["passed"] is False

    def test_prize_and_remote_never_gate(self):
        client = FakeClient(response_with(3.0, remote=0.01, prize=0.01))
        assert triage.triage_item(client, make_item())["passed"] is True

    def test_only_student_college_is_configured_to_drop(self):
        assert triage.DROP_CATEGORIES == {"student_college"}
        assert triage.DROP_CATEGORIES <= set(triage.CATEGORY_CRITERIA)


class TestFailOpen:
    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("rate limited"),
            TimeoutError("timed out"),
            ConnectionError("no route to host"),
            ValueError("bad request"),
        ],
    )
    def test_api_errors_pass_the_item_through(self, exc):
        client = FakeClient(raises=exc)
        v = triage.triage_item(client, make_item())
        assert v["passed"] is True
        assert v["fit_score"] is None
        assert "fail-open" in v["reason"]
        assert v["error"]

    def test_missing_client_passes_through(self):
        v = triage.triage_item(None, make_item())
        assert v["passed"] is True
        assert v["reason"] == "skipped: no client"

    def test_malformed_response_passes_through(self):
        client = FakeClient(FakeResponse({"category": FakeChoice("ai_agents_llm")}))
        v = triage.triage_item(client, make_item())
        assert v["passed"] is True
        assert "unreadable response" in v["reason"]

    def test_disabled_returns_items_unchanged(self):
        items = [make_item(), make_item(url="https://example.com/e2")]
        survivors, verdicts = triage.triage_items(items, enabled=False)
        assert survivors is items
        assert verdicts == []

    def test_no_api_key_returns_items_unchanged(self, monkeypatch):
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        items = [make_item()]
        survivors, verdicts = triage.triage_items(items, enabled=True)
        assert survivors == items
        assert verdicts == []


class TestQuestionConstruction:
    def test_prizeless_sources_are_not_asked_about_prizes(self):
        # normalise_luma and normalise_cerebralvalley hardcode prize "".
        # Asking, then gating, would have wiped out both sources.
        luma = make_item(source="Luma", prize="", themes=[])
        questions = triage._build_questions(luma)
        assert "has_real_prize" not in questions
        assert "fit_score" in questions
        assert "category" in questions

    def test_prize_question_asked_when_prize_text_present(self):
        assert "has_real_prize" in triage._build_questions(make_item())

    def test_still_open_is_never_asked(self):
        # Date math is done in code by _is_over, not by the model.
        assert "still_open" not in triage._build_questions(make_item())

    def test_fit_levels_are_four_ordered_levels(self):
        assert len(triage.FIT_LEVELS) == 4

    def test_state_uses_real_fetcher_field_names(self):
        state = triage._build_state(make_item())
        assert state["summary"] == "Build AI agents"
        assert state["themes"] == ["Machine Learning/AI"]
        assert "description" not in state
        assert "tags" not in state

    def test_prizeless_luma_item_still_survives_the_gate(self):
        # Regression guard: the original plan's has_real_prize gate would
        # have dropped every Luma and Cerebral Valley listing.
        luma = make_item(source="Luma", prize="", themes=[])
        client = FakeClient(
            FakeResponse(
                {
                    "category": FakeChoice("ai_agents_llm"),
                    "fit_score": FakeScore(2.8),
                    "is_remote": FakeNoul(0.2),
                }
            )
        )
        v = triage.triage_item(client, luma)
        assert v["passed"] is True
        assert v["has_real_prize"] is None


class TestIsOver:
    def test_past_event_is_over(self):
        assert triage._is_over(make_item(event_end="2020-01-01")) is True

    def test_future_event_is_not_over(self):
        assert triage._is_over(make_item(event_end="2099-01-01")) is False

    def test_unknown_date_is_not_over(self):
        assert triage._is_over(make_item(event_start=None, event_end="Unknown")) is False

    def test_unparseable_date_is_not_over(self):
        assert triage._is_over(make_item(event_start="soon", event_end="whenever")) is False

    def test_falls_back_to_event_start(self):
        item = make_item(event_start="2020-01-01", event_end=None)
        assert triage._is_over(item) is True

    def test_today_is_not_over(self):
        today = date.today().isoformat()
        assert triage._is_over(make_item(event_end=today)) is False


class TestTriageItems:
    def test_splits_survivors_and_logs_all(self, tmp_path, monkeypatch):
        db = str(tmp_path / "t.db")
        keep = make_item(url="https://example.com/keep")
        drop = make_item(url="https://example.com/drop")

        real_triage_item = triage.triage_item

        def fake_triage_item(client, item):
            category = "student_college" if "drop" in item["url"] else "ai_agents_llm"
            return real_triage_item(
                FakeClient(response_with_category(category, 0.95)), item
            )

        monkeypatch.setattr(triage, "_make_client", lambda: FakeClient(response_with(1)))
        monkeypatch.setattr(triage, "triage_item", fake_triage_item)

        survivors, verdicts = triage.triage_items(
            [keep, drop], enabled=True, db_path=db
        )
        assert [s["url"] for s in survivors] == ["https://example.com/keep"]
        assert len(verdicts) == 2

        rows = sqlite3.connect(db).execute(
            "SELECT url, passed, category FROM triage_log ORDER BY url"
        ).fetchall()
        assert rows == [
            ("https://example.com/drop", 0, "student_college"),
            ("https://example.com/keep", 1, "ai_agents_llm"),
        ]

    def test_empty_input_short_circuits(self):
        survivors, verdicts = triage.triage_items([], enabled=True)
        assert survivors == []
        assert verdicts == []


class TestLogging:
    def test_log_failure_does_not_raise(self, monkeypatch):
        v = triage._blank_verdict(make_item(), "fail-open: test")
        triage.log_verdicts([v], db_path="/nonexistent-dir/x.db")

    def test_failed_verdict_is_logged_with_error(self, tmp_path):
        db = str(tmp_path / "t.db")
        client = FakeClient(raises=RuntimeError("429 rate limited"))
        v = triage.triage_item(client, make_item())
        triage.log_verdicts([v], db_path=db)
        row = sqlite3.connect(db).execute(
            "SELECT passed, fit_score, error FROM triage_log"
        ).fetchone()
        assert row[0] == 1
        assert row[1] is None
        assert "429" in row[2]
