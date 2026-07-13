import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from buildathon_radar import agent


def fake_response(text):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def make_item(url="https://example.com/e1", title="Test Event"):
    return {
        "source": "Devpost",
        "title": title,
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


VALID_JSON = json.dumps(
    {
        "picks": [
            {
                "url": "https://example.com/e1",
                "title": "Test Event",
                "tier": "must_see",
                "score": 87,
                "scoring": {"theme": 33, "geo": 28, "host": 19, "signal": 7},
                "why": "Highly relevant.",
            }
        ],
        "skipped_count": 3,
        "week_note": "A solid week.",
    }
)


class TestEmptyInput:
    def test_empty_items_never_calls_client(self):
        with patch.object(agent.client.messages, "create") as mock_create:
            result = agent.run_agent([])
        mock_create.assert_not_called()
        assert result == {
            "picks": [],
            "skipped_count": 0,
            "week_note": "No new events found this week.",
        }


class TestThinkingBlockHandling:
    def test_skips_leading_thinking_block_without_text_attr(self):
        thinking_block = SimpleNamespace(type="thinking", thinking="reasoning...")
        text_block = SimpleNamespace(type="text", text=VALID_JSON)
        response = SimpleNamespace(content=[thinking_block, text_block])
        with patch.object(agent.client.messages, "create", return_value=response):
            result = agent.run_agent([make_item()])
        assert len(result["picks"]) == 1

    def test_raises_if_no_block_has_text(self):
        thinking_block = SimpleNamespace(type="thinking", thinking="reasoning...")
        response = SimpleNamespace(content=[thinking_block])
        with patch.object(agent.client.messages, "create", return_value=response):
            with pytest.raises(RuntimeError, match="no text block"):
                agent.run_agent([make_item()])


class TestJSONParsing:
    def test_clean_json_parses(self):
        with patch.object(
            agent.client.messages, "create", return_value=fake_response(VALID_JSON)
        ) as mock_create:
            result = agent.run_agent([make_item()])
        mock_create.assert_called_once()
        assert len(result["picks"]) == 1
        assert result["picks"][0]["url"] == "https://example.com/e1"
        assert result["skipped_count"] == 3
        assert result["week_note"] == "A solid week."

    def test_fenced_json_parses(self):
        fenced = f"```json\n{VALID_JSON}\n```"
        with patch.object(
            agent.client.messages, "create", return_value=fake_response(fenced)
        ):
            result = agent.run_agent([make_item()])
        assert len(result["picks"]) == 1

    def test_prose_wrapped_json_parses_via_brace_extraction(self):
        wrapped = f"Sure, here is the JSON you asked for:\n{VALID_JSON}\nLet me know if you need anything else."
        with patch.object(
            agent.client.messages, "create", return_value=fake_response(wrapped)
        ):
            result = agent.run_agent([make_item()])
        assert len(result["picks"]) == 1

    def test_garbage_retries_once_then_raises(self):
        with patch.object(
            agent.client.messages,
            "create",
            return_value=fake_response("not json at all, just words"),
        ) as mock_create:
            with pytest.raises(RuntimeError, match="unparseable"):
                agent.run_agent([make_item()])
        assert mock_create.call_count == 2

    def test_retry_recovers_with_valid_json_on_second_call(self):
        with patch.object(
            agent.client.messages,
            "create",
            side_effect=[fake_response("garbage"), fake_response(VALID_JSON)],
        ) as mock_create:
            result = agent.run_agent([make_item()])
        assert mock_create.call_count == 2
        assert len(result["picks"]) == 1


class TestPickValidation:
    def test_malformed_pick_dropped(self):
        bad_json = json.dumps(
            {
                "picks": [
                    {"url": "https://example.com/e1", "title": "T", "tier": "must_see", "score": 80, "why": "ok"},
                    {"url": "https://example.com/e2", "title": "Missing tier", "score": 60, "why": "bad"},
                    {"url": "", "title": "Empty url", "tier": "radar", "score": 40, "why": "bad"},
                    {"title": "No url key", "tier": "radar", "score": 40, "why": "bad"},
                ],
                "skipped_count": 0,
                "week_note": "note",
            }
        )
        with patch.object(
            agent.client.messages, "create", return_value=fake_response(bad_json)
        ):
            result = agent.run_agent([make_item()])
        assert len(result["picks"]) == 1
        assert result["picks"][0]["url"] == "https://example.com/e1"

    def test_invalid_tier_value_dropped(self):
        bad_json = json.dumps(
            {
                "picks": [
                    {"url": "https://example.com/e1", "title": "T", "tier": "super_hot", "score": 99, "why": "bad tier"},
                ],
                "skipped_count": 0,
                "week_note": "note",
            }
        )
        with patch.object(
            agent.client.messages, "create", return_value=fake_response(bad_json)
        ):
            result = agent.run_agent([make_item()])
        assert result["picks"] == []

    def test_non_int_score_dropped(self):
        bad_json = json.dumps(
            {
                "picks": [
                    {"url": "https://example.com/e1", "title": "T", "tier": "radar", "score": "high", "why": "bad score"},
                ],
                "skipped_count": 0,
                "week_note": "note",
            }
        )
        with patch.object(
            agent.client.messages, "create", return_value=fake_response(bad_json)
        ):
            result = agent.run_agent([make_item()])
        assert result["picks"] == []

    def test_missing_week_note_and_skipped_count_default(self):
        minimal_json = json.dumps({"picks": []})
        with patch.object(
            agent.client.messages, "create", return_value=fake_response(minimal_json)
        ):
            result = agent.run_agent([make_item()])
        assert result["skipped_count"] == 0
        assert result["week_note"] == ""
