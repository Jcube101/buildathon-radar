from buildathon_radar import tracker_store


def make_item(event_id, **overrides):
    item = {
        "event_id": event_id,
        "title": "Some Hackathon",
        "url": "https://example.devpost.com/",
        "host": "Acme",
        "source": "Devpost",
        "event_start": "2026-08-01",
        "event_end": "2026-08-02",
    }
    item.update(overrides)
    return item


def db_path(tmp_path):
    return str(tmp_path / "tracker.db")


class TestSchemaInit:
    def test_schema_creates_cleanly_twice(self, tmp_path):
        path = db_path(tmp_path)
        conn1 = tracker_store.connect(path)
        conn1.close()
        conn2 = tracker_store.connect(path)  # must not raise on existing schema
        row = conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {r["name"] for r in row}
        assert "events" in names
        assert "action_log" in names
        conn2.close()

    def test_wal_mode_enabled(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"


class TestUpsertSeen:
    def test_insert_new_row(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        row = conn.execute("SELECT * FROM events WHERE event_id = ?", ("e1",)).fetchone()
        assert row is not None
        assert row["state"] == "seen"
        assert row["title"] == "Some Hackathon"
        assert row["event_start"] == "2026-08-01"

    def test_refresh_metadata_without_touching_state(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        tracker_store.apply_action(conn, "track", "e1")

        tracker_store.upsert_seen(conn, [make_item("e1", title="Updated Title")])
        row = conn.execute("SELECT * FROM events WHERE event_id = ?", ("e1",)).fetchone()
        assert row["title"] == "Updated Title"
        assert row["state"] == "tracked"  # not reset to 'seen'
        assert row["tracked_at"] is not None  # not cleared

    def test_null_event_start_end_not_overwritten_by_a_later_null(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1", event_start="2026-08-01", event_end="2026-08-02")])
        tracker_store.upsert_seen(conn, [make_item("e1", event_start=None, event_end=None)])
        row = conn.execute("SELECT * FROM events WHERE event_id = ?", ("e1",)).fetchone()
        assert row["event_start"] == "2026-08-01"
        assert row["event_end"] == "2026-08-02"

    def test_skips_items_without_event_id(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        item = make_item("e1")
        del item["event_id"]
        tracker_store.upsert_seen(conn, [item])
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 0


class TestStateTransitions:
    def test_track_on_seen_transitions_to_tracked(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        result, row = tracker_store.apply_action(conn, "track", "e1")
        assert result == "ok"
        assert row["state"] == "tracked"
        assert row["tracked_at"] is not None

    def test_applied_on_seen_transitions_to_applied(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        result, row = tracker_store.apply_action(conn, "applied", "e1")
        assert result == "ok"
        assert row["state"] == "applied"
        assert row["applied_at"] is not None

    def test_applied_on_tracked_transitions_to_applied(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        tracker_store.apply_action(conn, "track", "e1")
        result, row = tracker_store.apply_action(conn, "applied", "e1")
        assert result == "ok"
        assert row["state"] == "applied"
        assert row["tracked_at"] is not None  # earlier timestamp preserved
        assert row["applied_at"] is not None

    def test_track_on_applied_is_noop_no_downgrade(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        tracker_store.apply_action(conn, "applied", "e1")
        result, row = tracker_store.apply_action(conn, "track", "e1")
        assert result == "noop"
        assert row["state"] == "applied"  # unchanged

    def test_repeat_track_click_is_noop(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        tracker_store.apply_action(conn, "track", "e1")
        first_row = conn.execute("SELECT tracked_at FROM events WHERE event_id='e1'").fetchone()
        result, row = tracker_store.apply_action(conn, "track", "e1")
        assert result == "noop"
        assert row["tracked_at"] == first_row["tracked_at"]  # not overwritten

    def test_repeat_applied_click_is_noop(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        tracker_store.apply_action(conn, "applied", "e1")
        result, row = tracker_store.apply_action(conn, "applied", "e1")
        assert result == "noop"

    def test_action_on_unknown_event_id(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        result, row = tracker_store.apply_action(conn, "track", "does-not-exist")
        assert result == "unknown_event"
        assert row is None

    def test_every_call_logged_to_action_log(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        tracker_store.apply_action(conn, "track", "e1")
        tracker_store.apply_action(conn, "track", "e1")  # noop
        tracker_store.apply_action(conn, "applied", "unknown-id")  # unknown
        logs = conn.execute("SELECT * FROM action_log ORDER BY id").fetchall()
        results = [r["result"] for r in logs]
        assert results == ["ok", "noop", "unknown_event"]


class TestQueries:
    def test_tracked_open_excludes_lapsed(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [
            make_item("future", event_start="2026-09-01", event_end="2026-09-02"),
            make_item("past", event_start="2026-01-01", event_end="2026-01-02"),
        ])
        tracker_store.apply_action(conn, "track", "future")
        tracker_store.apply_action(conn, "track", "past")
        rows = tracker_store.get_tracked_open(conn, "2026-07-14")
        ids = [r["event_id"] for r in rows]
        assert "future" in ids
        assert "past" not in ids

    def test_tracked_open_includes_null_dates(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("dateless", event_start=None, event_end=None)])
        tracker_store.apply_action(conn, "track", "dateless")
        rows = tracker_store.get_tracked_open(conn, "2026-07-14")
        assert len(rows) == 1
        assert rows[0]["event_id"] == "dateless"

    def test_applied_open_excludes_past_end_date(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [
            make_item("future", event_start="2026-09-01", event_end="2026-09-02"),
            make_item("past", event_start="2026-01-01", event_end="2026-01-02"),
        ])
        tracker_store.apply_action(conn, "applied", "future")
        tracker_store.apply_action(conn, "applied", "past")
        rows = tracker_store.get_applied_open(conn, "2026-07-14")
        ids = [r["event_id"] for r in rows]
        assert "future" in ids
        assert "past" not in ids

    def test_applied_open_includes_null_end_date(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("dateless", event_start=None, event_end=None)])
        tracker_store.apply_action(conn, "applied", "dateless")
        rows = tracker_store.get_applied_open(conn, "2026-07-14")
        assert len(rows) == 1

    def test_queries_do_not_return_seen_or_over(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("just-seen")])
        assert tracker_store.get_tracked_open(conn, "2026-07-14") == []
        assert tracker_store.get_applied_open(conn, "2026-07-14") == []

    def test_ordering_by_event_start(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [
            make_item("later", event_start="2026-09-01", event_end="2026-09-02"),
            make_item("sooner", event_start="2026-08-01", event_end="2026-08-02"),
        ])
        tracker_store.apply_action(conn, "track", "later")
        tracker_store.apply_action(conn, "track", "sooner")
        rows = tracker_store.get_tracked_open(conn, "2026-07-14")
        assert [r["event_id"] for r in rows] == ["sooner", "later"]


class TestGetAllEvents:
    def test_empty_store_returns_empty_list(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        assert tracker_store.get_all_events(conn) == []

    def test_returns_every_state(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [
            make_item("e1"), make_item("e2"), make_item("e3"),
        ])
        tracker_store.apply_action(conn, "track", "e2")
        tracker_store.apply_action(conn, "applied", "e3")
        rows = tracker_store.get_all_events(conn)
        by_id = {r["event_id"]: r["state"] for r in rows}
        assert by_id == {"e1": "seen", "e2": "tracked", "e3": "applied"}

    def test_read_only_no_state_change(self, tmp_path):
        conn = tracker_store.connect(db_path(tmp_path))
        tracker_store.upsert_seen(conn, [make_item("e1")])
        tracker_store.apply_action(conn, "track", "e1")
        before = {r["event_id"]: dict(r) for r in tracker_store.get_all_events(conn)}
        tracker_store.get_all_events(conn)  # calling it again must not mutate anything
        after = {r["event_id"]: dict(r) for r in tracker_store.get_all_events(conn)}
        assert before == after


class TestSignVerify:
    def test_round_trip(self):
        token = tracker_store.sign_action("track", "e1", secret="s3cr3t")
        assert tracker_store.verify_action("track", "e1", token, secret="s3cr3t")

    def test_rejects_tampered_event_id(self):
        token = tracker_store.sign_action("track", "e1", secret="s3cr3t")
        assert not tracker_store.verify_action("track", "e2", token, secret="s3cr3t")

    def test_rejects_cross_action_token(self):
        token = tracker_store.sign_action("track", "e1", secret="s3cr3t")
        assert not tracker_store.verify_action("applied", "e1", token, secret="s3cr3t")

    def test_rejects_empty_token(self):
        assert not tracker_store.verify_action("track", "e1", "", secret="s3cr3t")
        assert not tracker_store.verify_action("track", "e1", None, secret="s3cr3t")

    def test_no_secret_returns_none_and_verify_fails(self):
        token = tracker_store.sign_action("track", "e1", secret="")
        assert token is None
        assert not tracker_store.verify_action("track", "e1", "anything", secret="")

    def test_wrong_secret_rejected(self):
        token = tracker_store.sign_action("track", "e1", secret="s3cr3t")
        assert not tracker_store.verify_action("track", "e1", token, secret="different")
