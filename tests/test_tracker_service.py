import pytest
from fastapi.testclient import TestClient

from buildathon_radar import tracker_service, tracker_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "tracker.db")
    monkeypatch.setattr(tracker_service, "DB_PATH", db_path)
    conn = tracker_store.connect(db_path)
    tracker_store.upsert_seen(conn, [
        {
            "event_id": "e1",
            "title": "Build with Gemma",
            "url": "https://build-with-gemma.devfolio.co/",
            "host": "IEEE",
            "source": "Devfolio",
            "event_start": "2026-08-01",
            "event_end": "2026-08-02",
        }
    ])
    conn.close()
    return TestClient(tracker_service.app)


def sign(action, event_id):
    return tracker_store.sign_action(action, event_id)


class TestHealth:
    def test_root_health_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "running" in resp.text.lower()
        assert "e1" not in resp.text  # no event data on the health page


class TestTrackEndpoint:
    def test_valid_click_writes_state_and_returns_200(self, client, tmp_path):
        token = sign("track", "e1")
        resp = client.get(f"/track?event_id=e1&t={token}")
        assert resp.status_code == 200
        assert "Build with Gemma" in resp.text
        assert "Tracked" in resp.text

        conn = tracker_store.connect(str(tmp_path / "tracker.db"))
        row = conn.execute("SELECT * FROM events WHERE event_id='e1'").fetchone()
        assert row["state"] == "tracked"
        assert row["tracked_at"] is not None
        log = conn.execute("SELECT * FROM action_log WHERE event_id='e1'").fetchall()
        assert len(log) == 1
        assert log[0]["result"] == "ok"

    def test_repeat_click_is_noop_page_and_only_logs(self, client, tmp_path):
        token = sign("track", "e1")
        client.get(f"/track?event_id=e1&t={token}")
        resp = client.get(f"/track?event_id=e1&t={token}")
        assert resp.status_code == 200
        assert "Already tracked" in resp.text

        conn = tracker_store.connect(str(tmp_path / "tracker.db"))
        log = conn.execute("SELECT * FROM action_log WHERE event_id='e1'").fetchall()
        assert len(log) == 2
        assert log[1]["result"] == "noop"

    def test_unknown_event_id_returns_404(self, client):
        token = sign("track", "does-not-exist")
        resp = client.get(f"/track?event_id=does-not-exist&t={token}")
        assert resp.status_code == 404
        assert "Unknown event" in resp.text

    def test_bad_token_returns_403_with_no_db_write(self, client, tmp_path):
        resp = client.get("/track?event_id=e1&t=wrongtoken000000000")
        assert resp.status_code == 403
        assert "Invalid link" in resp.text

        conn = tracker_store.connect(str(tmp_path / "tracker.db"))
        row = conn.execute("SELECT * FROM events WHERE event_id='e1'").fetchone()
        assert row["state"] == "seen"  # untouched
        log = conn.execute("SELECT * FROM action_log WHERE event_id='e1'").fetchall()
        assert len(log) == 1
        assert log[0]["result"] == "bad_token"

    def test_missing_token_returns_403(self, client):
        resp = client.get("/track?event_id=e1")
        assert resp.status_code == 403

    def test_missing_event_id_returns_400(self, client):
        resp = client.get("/track")
        assert resp.status_code == 400
        assert "Malformed" in resp.text

    def test_track_click_shows_event_start_date(self, client):
        token = sign("track", "e1")
        resp = client.get(f"/track?event_id=e1&t={token}")
        assert "Aug 01, 2026" in resp.text


class TestAppliedEndpoint:
    def test_valid_applied_click(self, client, tmp_path):
        token = sign("applied", "e1")
        resp = client.get(f"/applied?event_id=e1&t={token}")
        assert resp.status_code == 200
        assert "Applied" in resp.text
        assert "Build with Gemma" in resp.text

        conn = tracker_store.connect(str(tmp_path / "tracker.db"))
        row = conn.execute("SELECT * FROM events WHERE event_id='e1'").fetchone()
        assert row["state"] == "applied"

    def test_track_after_applied_is_noop_no_downgrade(self, client, tmp_path):
        applied_token = sign("applied", "e1")
        client.get(f"/applied?event_id=e1&t={applied_token}")

        track_token = sign("track", "e1")
        resp = client.get(f"/track?event_id=e1&t={track_token}")
        assert resp.status_code == 200
        assert "Already applied" in resp.text
        assert "outranks" in resp.text.lower()

        conn = tracker_store.connect(str(tmp_path / "tracker.db"))
        row = conn.execute("SELECT * FROM events WHERE event_id='e1'").fetchone()
        assert row["state"] == "applied"  # not downgraded to tracked

    def test_cross_action_token_rejected(self, client):
        track_token = sign("track", "e1")
        resp = client.get(f"/applied?event_id=e1&t={track_token}")
        assert resp.status_code == 403


class TestPagesAreEscaped:
    def test_title_html_escaped_in_confirmation_page(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "tracker.db")
        monkeypatch.setattr(tracker_service, "DB_PATH", db_path)
        conn = tracker_store.connect(db_path)
        tracker_store.upsert_seen(conn, [
            {
                "event_id": "e2",
                "title": "<script>alert(1)</script> & Co",
                "url": "https://example.com/",
                "host": "H",
                "source": "Devpost",
                "event_start": None,
                "event_end": None,
            }
        ])
        conn.close()
        client = TestClient(tracker_service.app)
        token = sign("track", "e2")
        resp = client.get(f"/track?event_id=e2&t={token}")
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text
