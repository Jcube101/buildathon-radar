# roadmap.md: done / not-done checklist

Built overnight by Claude Sonnet 5 against the architecture in `ROADMAP.md`
(the original planning document, left in the repo root untouched). This file
is the status checklist version; `ROADMAP.md` remains the historical record of
the design decisions and recon.

## Done

- [x] `venv/` with `anthropic`, `requests`, `python-dotenv`, `markdown`, `pytest`, all import-verified.
- [x] `.gitignore` extended for `cache.json`, `archive/`, `scheduler_log.txt`.
- [x] `fetcher.py`: Devpost (2 pages, themes filter, best-effort date parse) and
      Devfolio (both `application_open` and `upcoming` types, merged and
      deduped by uuid) fetchers, normalising into the 11-key item contract.
- [x] `cache.json` dedup with 45 day TTL, ported load/save helpers with corrupt
      file and legacy format fallbacks, `--dry-run` skips both read and write.
- [x] 24 fetcher/cache tests, all passing, no network calls in tests (fixtures
      captured from live responses).
- [x] `agent.py`: `claude-sonnet-5` call, four-block system prompt (persona,
      rubric, tiering and output contract, critical constraints), strict JSON
      output, three-stage parse ladder plus one retry, defensive pick
      validation, empty-input short circuit.
- [x] 12 agent tests, all mocking the Claude client, no live calls in the suite.
- [x] `guard.py`: exact plus trailing-slash-tolerant URL validation against the
      fetched item set, drop-and-continue on a miss.
- [x] `digest.py`: tier-sectioned markdown, quiet-week and all-failed bodies,
      always-present source health footer, integrity line when picks are dropped.
- [x] 24 guard and digest tests, all passing.
- [x] `deliver.py`: HTML render (blue accent, "Buildathon Radar" heading),
      local archive, Gmail SMTP send, plus a `send_failure_email` helper for
      the always-send invariant on a crash.
- [x] 9 deliver tests, all mocking SMTP. Live SMTP auth-only probe (login,
      no send) confirmed the Gmail app password in `.env` works.
- [x] `main.py`: four-stage orchestration, `--dry-run` flag, top-level fatal
      handler that attempts a failure email before a non-zero exit.
- [x] Live `--dry-run` verification: real fetch (69 Devpost + 21 Devfolio events),
      real Claude call, full digest printed, no cache or archive written.
- [x] systemd `buildathon-radar.service` and `.timer` installed via
      `systemctl --user` (no sudo), enabled, confirmed next run is the
      coming Sunday 17:00 IST.
- [x] Doc set: `README.md`, `spec.md`, `roadmap.md` (this file), `learnings.md`, `CLAUDE.md`.
- [x] Full test suite green, final `--dry-run` gate passed.

## Explicitly left for the user

- [ ] One live, non-dry `python main.py` run: the actual proof-of-life email.
      This is deliberate, not an oversight; see `README.md`.

## v2 backlog (not built, documented per the original roadmap)

- [ ] Cerebral Valley source.
- [ ] Luma source.
- [ ] Unstop as a third API source.
- [ ] Deadline-reminder mode.
- [ ] Per-event `.ics` calendar attachments.
