"""Orchestration tests for main.py (issue #1).

main.py is a script with top-level code, so each test runs it with
runpy.run_path and catches its sys.exit. The real fetch_events, save_cache
and digest builders run against a tmp_path cache.json; only the slow or
outward-facing pieces (sources, Jev triage, Claude, the tracker database and
both email sends) are replaced, so no test touches the network, the real
tracker.db, or anyone's inbox.
"""

import json
import runpy
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from buildathon_radar import fetcher, tracker_store

MAIN_PY = str(Path(__file__).resolve().parent.parent / "main.py")

OLD_RECORD = {
    "event_id": "old-event",
    "urls": ["https://example.com/old"],
    "first_seen": "2026-01-01",
    "last_shown": "2026-01-01",
    "status": "seen",
    "resurfaced": False,
    "event_start": None,
    "event_end": None,
}

NEW_ITEM = {
    "source": "Devpost",
    "title": "New Hackathon",
    "url": "https://new.devpost.com/",
    "summary": "s",
    "published": "Unknown",
    "location": "Online",
    "mode": "online",
    "host": "Acme",
    "dates": "d",
    "prize": "",
    "themes": [],
    "event_start": None,
    "event_end": None,
}

EMPTY_RESULT = {"picks": [], "skipped_count": 0, "week_note": "quiet week"}


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A tmp_path holding an existing cache.json, with one fake source that
    returns one brand-new event."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cache.json").write_text(json.dumps({"old-event": OLD_RECORD}))
    monkeypatch.setattr(
        fetcher, "SOURCES", [{"name": "Devpost", "fetch": lambda: ([dict(NEW_ITEM)], None)}]
    )
    return tmp_path


def run_main(monkeypatch, *, dry_run=False, agent=None, sent=True):
    """Runs main.py once. Returns (exit_code, mocks)."""
    monkeypatch.setattr(sys, "argv", ["main.py"] + (["--dry-run"] if dry_run else []))
    run_agent = MagicMock(return_value=EMPTY_RESULT) if agent is None else agent
    send_digest = MagicMock(return_value=sent)
    send_failure_email = MagicMock()
    with patch("buildathon_radar.triage.triage_items", lambda items: (items, [])), patch(
        "buildathon_radar.agent.run_agent", run_agent
    ), patch.object(
        tracker_store, "connect", side_effect=RuntimeError("no tracker db in tests")
    ), patch(
        "buildathon_radar.deliver.send_digest", send_digest
    ), patch(
        "buildathon_radar.deliver.send_failure_email", send_failure_email
    ):
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(MAIN_PY, run_name="__main__")
    mocks = {
        "run_agent": run_agent,
        "send_digest": send_digest,
        "send_failure_email": send_failure_email,
    }
    return exit_info.value.code, mocks


def read_cache(workdir):
    return json.loads((workdir / "cache.json").read_text())


class TestCacheSavedOnlyAfterDelivery:
    def test_successful_send_saves_old_and_new_records(self, workdir, monkeypatch):
        code, mocks = run_main(monkeypatch)
        assert code == 0
        mocks["send_digest"].assert_called_once()
        saved = read_cache(workdir)
        assert saved["old-event"] == OLD_RECORD
        assert len(saved) == 2  # the new event's record was added

    def test_failed_send_leaves_cache_untouched_and_exits_nonzero(self, workdir, monkeypatch):
        before = (workdir / "cache.json").read_text()
        code, mocks = run_main(monkeypatch, sent=False)
        assert code == 1
        assert (workdir / "cache.json").read_text() == before
        mocks["send_failure_email"].assert_called_once()
        assert "digest email not sent" in mocks["send_failure_email"].call_args[0][0]

    def test_agent_crash_leaves_cache_untouched(self, workdir, monkeypatch):
        before = (workdir / "cache.json").read_text()
        agent = MagicMock(side_effect=RuntimeError("agent returned unparseable output twice"))
        code, mocks = run_main(monkeypatch, agent=agent)
        assert code == 1
        assert (workdir / "cache.json").read_text() == before
        mocks["send_digest"].assert_not_called()
        mocks["send_failure_email"].assert_called_once()

    def test_next_run_after_a_failure_retries_the_same_events(self, workdir, monkeypatch):
        """The scenario from issue #1: one week fails after fetching, and the
        following run must still see that week's events as new."""
        agent = MagicMock(side_effect=RuntimeError("Claude API overloaded"))
        code, _ = run_main(monkeypatch, agent=agent)
        assert code == 1

        code, mocks = run_main(monkeypatch)
        assert code == 0
        retried = mocks["run_agent"].call_args[0][0]
        assert [i["url"] for i in retried] == [NEW_ITEM["url"]]


class TestDryRun:
    def test_dry_run_never_saves_or_sends(self, workdir, monkeypatch):
        before = (workdir / "cache.json").read_text()
        code, mocks = run_main(monkeypatch, dry_run=True)
        assert code == 0
        assert (workdir / "cache.json").read_text() == before
        mocks["send_digest"].assert_not_called()

    def test_dry_run_creates_no_cache_file(self, workdir, monkeypatch):
        (workdir / "cache.json").unlink()
        code, _ = run_main(monkeypatch, dry_run=True)
        assert code == 0
        assert not (workdir / "cache.json").exists()

    def test_dry_run_crash_sends_no_failure_email(self, workdir, monkeypatch):
        agent = MagicMock(side_effect=RuntimeError("boom"))
        code, mocks = run_main(monkeypatch, dry_run=True, agent=agent)
        assert code == 1
        mocks["send_failure_email"].assert_not_called()
