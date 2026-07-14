# V2-TRACKER-PLAN.md

Build plan for v2 Units A and B of buildathon-radar: the tracker service
(FastAPI + SQLite, exposed at `radar.job-joseph.com`) and the email-button plus
participation-log layer in the digest. Written 2026-07-14 by an architecture
session; to be executed by a later Claude (Sonnet) session, partly unattended.

Scope guard: this plan builds ROADMAP.md sections 2.2 (Track/Applied actions)
and 2.3 (participation log) on a new SQLite tracker store. Sections 2.4
(lifecycle/outcomes), 2.5 (calendar), and 2.6 (entity resolution) are NOT build
targets. The schema below is shaped so 2.4 lands later with zero migration, and
the one place a 2.5 calendar trigger would later attach is marked. Do not build
either.

Recon for this plan was done live on jobpi on 2026-07-14: the cloudflared
config, the sudoers state, the listening ports, the systemd units, and the
digest template were all inspected, not assumed. Findings are marked "verified"
throughout.

---

## 1. Architecture overview

Two independent processes share one SQLite file:

- **The weekly digest run** (`main.py`, unchanged `Type=oneshot` user timer,
  Sundays 17:00 IST). It gains two duties: after the guard validates picks on a
  non-dry run, it upserts every emailed pick into the tracker store as state
  `seen` (with denormalized metadata), and at render time it reads the store's
  tracked and applied rows to build the reminder and participation-log sections.
- **The tracker service** (new, `Type=simple` systemd user service). A small
  FastAPI app on `127.0.0.1:8015`, exposed publicly as
  `https://radar.job-joseph.com` through the existing `pi-home` Cloudflare
  Tunnel. It handles exactly the clicks from the email buttons: looks up the
  event, transitions its state, returns a small confirmation page.

```
                         WEEKLY (Sunday 17:00 IST, oneshot timer)
  fetcher -> agent -> guard -> [upsert picks as 'seen'] -> digest -> deliver
                                       |                      ^
                                       v                      | reads tracked/
                                  tracker.db  <---------------+ applied rows
                                  (SQLite, WAL)
                                       ^
                                       | state transition (seen->tracked/applied)
                                       |
                         ALWAYS-ON (Type=simple user service)
                    FastAPI app, uvicorn on 127.0.0.1:8015
                                       ^
                                       | http://localhost:8015
                             cloudflared tunnel (pi-home)
                                       ^
                                       | https://radar.job-joseph.com
                                       |
   Gmail on phone: user taps [Track] or [Applied] button in the digest email
```

Click-to-state flow, end to end:

```
1. Digest email contains:  https://radar.job-joseph.com/track?event_id=E&t=TOKEN
2. User taps the link. Cloudflare routes it through the pi-home tunnel to
   localhost:8015.
3. FastAPI verifies TOKEN (HMAC of "track:E" with TRACKER_SECRET, see §4).
4. It looks up E in tracker.db.
   - unknown        -> 404 page, no write
   - bad token      -> 403 page, no write
   - state upgrade  -> UPDATE row (state, tracked_at/applied_at, updated_at),
                       INSERT into action_log, 200 confirmation page
   - already there  -> no state write, INSERT into action_log (noop), 200
                       "already tracked/applied" page
5. Next Sunday's digest run reads tracker.db and renders the tracked-reminder
   and participation-log sections from those rows.
```

Design principles carried over from v1, restated because they bind this build:

- **Code renders from data; Claude touches none of it.** The tracker sections
  of the digest are rendered by `digest.py` from SQLite rows. The agent and
  guard never see tracker state.
- **The store outlives the cache.** `cache.json` records age out by design;
  tracker rows persist forever. That is why event metadata is denormalized into
  the tracker row (§2) instead of joined back to the cache.
- **One shared key.** The tracker store is keyed on the same composite
  `event_id` that `fetcher.py` derives (`derive_event_id`: normalized host +
  normalized title + start date). A tracked event ties back to its cache record
  by that id with no translation layer.
- **`--dry-run` touches no state.** Dry runs neither write nor read tracker.db,
  exactly as they already skip `cache.json`.

New/changed files:

```
buildathon_radar/
    tracker_store.py     NEW  schema init, upsert, state transitions, queries,
                              HMAC token sign/verify (shared by both processes)
    tracker_service.py   NEW  FastAPI app: /, /track, /applied
    fetcher.py           EDIT attach "event_id" to each returned item dict
    digest.py            EDIT button row per card; tracked-reminder and
                              participation-log sections in the HTML digest
main.py                  EDIT upsert picks + pass tracker rows to the renderer
                              (send-path adjacent: pause/flag rule applies, §9)
scheduler/systemd/
    buildathon-tracker.service  NEW  user unit (Type=simple)
    README.md            EDIT install/verify notes for the new unit
tracker.db               NEW  runtime state, gitignored (plus -wal/-shm)
tests/
    test_tracker_store.py    NEW
    test_tracker_service.py  NEW
    test_digest.py           EDIT button + log rendering tests
requirements.txt         EDIT add fastapi, uvicorn, httpx (httpx is required
                              by FastAPI's TestClient, test-time only)
.env / .env.example      EDIT new TRACKER_SECRET (user adds the real one, §11)
```

---

## 2. The SQLite schema

One database file, `tracker.db`, at the repo root next to `cache.json`
(gitignored; both processes run with `WorkingDirectory=` the repo root, so a
relative path resolves identically for both). Opened with WAL mode and a busy
timeout so the always-on service and the weekly script can interleave safely:

```sql
PRAGMA journal_mode = WAL;       -- set once at init; persistent
PRAGMA busy_timeout = 5000;      -- set per connection
```

```sql
CREATE TABLE IF NOT EXISTS events (
    -- identity (serves A/B now)
    event_id     TEXT PRIMARY KEY,          -- fetcher.derive_event_id output; same key as cache.json
    -- denormalized event metadata (serves A/B now; snapshot at first upsert,
    -- refreshed on later upserts, never authored by Claude)
    title        TEXT NOT NULL,             -- display title for confirmation pages and log rows
    url          TEXT NOT NULL,             -- canonical event link for the log's title column
    host         TEXT,                      -- organiser, for future display; nullable
    source       TEXT,                      -- "Devpost" | "Devfolio" | future sources
    event_start  TEXT,                      -- "YYYY-MM-DD" or NULL (mirrors cache semantics)
    event_end    TEXT,                      -- "YYYY-MM-DD" or NULL
    -- participation state machine (state serves A/B now; 'over' + outcome are 2.4)
    state        TEXT NOT NULL DEFAULT 'seen'
                 CHECK (state IN ('seen','tracked','applied','over')),
    outcome      TEXT
                 CHECK (outcome IS NULL OR outcome IN
                        ('did_not_participate','participated','won')),
    -- timestamps, ISO 8601 with +05:30 offset (first_seen/updated_at serve A/B
    -- now; tracked_at/applied_at serve A/B now; over_at is 2.4)
    first_seen   TEXT NOT NULL,             -- when the digest run first upserted it
    tracked_at   TEXT,                      -- when Track was first clicked
    applied_at   TEXT,                      -- when Applied was first clicked
    over_at      TEXT,                      -- 2.4 placeholder: when the event resolved to 'over'
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    -- append-only audit of every endpoint hit; serves debugging now and 2.4's
    -- dashboard later. Never rendered into the digest.
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL,             -- as requested, even if unknown
    action       TEXT NOT NULL,             -- 'track' | 'applied'
    result       TEXT NOT NULL,             -- 'ok' | 'noop' | 'unknown_event' | 'bad_token'
    occurred_at  TEXT NOT NULL              -- ISO 8601 +05:30
);

CREATE INDEX IF NOT EXISTS idx_events_state ON events(state);
```

Column-by-column purpose is annotated inline above. Which columns serve what:

| Columns | Serves |
|---|---|
| `event_id`, `title`, `url`, `host`, `source`, `event_start`, `event_end`, `state` (values `seen`/`tracked`/`applied`), `first_seen`, `tracked_at`, `applied_at`, `updated_at` | Units A and B, now |
| `state` value `'over'`, `outcome`, `over_at` | 2.4 placeholders. Already legal in the CHECK constraints, so 2.4 adds behaviour, not columns. No ALTER TABLE will ever be needed for lifecycle/outcomes. |
| `action_log` table | Debugging now; 2.4 dashboard raw material later |

**State machine and transition rule.** States are ranked
`seen(0) < tracked(1) < applied(2) < over(3)`. A click transitions the row only
upward: `/track` on a `seen` row moves it to `tracked`; `/applied` on a `seen`
or `tracked` row moves it to `applied`; `/track` on an `applied` row is a noop
(the confirmation page says so; nothing downgrades). `over` is never written by
Unit A/B code; it exists in the CHECK so 2.4's date-driven sweep can use it
without a migration. `tracked_at`/`applied_at` are set on the first successful
transition into that state and never overwritten.

**Who writes rows.** Only the weekly digest run INSERTs into `events` (one
upsert per validated, emailed pick, on non-dry runs, state `seen`). The FastAPI
service only UPDATEs existing rows and INSERTs into `action_log`. Consequence:
every button in every email points at a row that exists by construction, and an
`event_id` the service cannot find is genuinely foreign (an old email predating
the tracker, or a forged/mangled link) and gets the graceful 404 page.

The upsert refreshes metadata without touching participation state:

```sql
INSERT INTO events (event_id, title, url, host, source, event_start, event_end,
                    state, first_seen, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, 'seen', ?, ?)
ON CONFLICT(event_id) DO UPDATE SET
    title       = excluded.title,
    url         = excluded.url,
    host        = excluded.host,
    source      = excluded.source,
    event_start = COALESCE(excluded.event_start, events.event_start),
    event_end   = COALESCE(excluded.event_end,   events.event_end),
    updated_at  = excluded.updated_at;
-- state, outcome, and the *_at action timestamps are deliberately absent from
-- the UPDATE list: a re-seen event never loses its tracked/applied state.
```

**Why denormalize title/url/host/dates into the row.** Three reasons. First,
persistence: `cache.json` entries lapse and could in principle be pruned;
tracked and applied events must render in the participation log for as long as
they are relevant, so the log cannot depend on a cache lookup. Second,
isolation: the always-on service should not parse or lock `cache.json`, whose
format belongs to the fetcher and has already migrated twice. Third, integrity:
the denormalized values are the same guard-matched source-item fields the email
itself was rendered from, so the confirmation page and the log obey the same
"no fact from Claude" rule as the digest. The cost is a few hundred bytes per
row at 5 to 12 rows per week, which is nothing. `event_id` remains the join key
back to the cache record if any future feature wants the full record while it
still exists.

**Volume and retention.** Every emailed pick lands as a `seen` row, roughly 5
to 12 per week, ~500 rows per year. No pruning is needed or designed. The
`seen` rows are not dead weight: they are exactly the 2.4 lifecycle's starting
population and give the future dashboard its full history.

**Queries the digest run uses (Unit B):**

```sql
-- participation log: applied, not yet past its end date
SELECT * FROM events
WHERE state = 'applied'
  AND (event_end IS NULL OR event_end >= :today)
ORDER BY COALESCE(event_start, '9999-12-31');

-- tracked reminders: tracked, not yet lapsed
SELECT * FROM events
WHERE state = 'tracked'
  AND (COALESCE(event_end, event_start) IS NULL
       OR COALESCE(event_end, event_start) >= :today)
ORDER BY COALESCE(event_start, '9999-12-31');
```

These are view-level date filters only. No code in Units A/B mutates state to
`over`; a past-dated applied event simply stops rendering (2.4 will later make
the state change explicit and ask for an outcome).

---

## 3. The FastAPI service design

`buildathon_radar/tracker_service.py`, run by uvicorn:
`venv/bin/uvicorn buildathon_radar.tracker_service:app --host 127.0.0.1 --port 8015`.

Port **8015** (verified free on 2026-07-14; 8013 and 8014 are already listening
and are in the tunnel config even though PORTS.md has drifted and stops at
8012. The executor updates PORTS.md in dev-meta as part of Phase 8).

Bind to `127.0.0.1` only. The tunnel is the sole external path, matching every
other service on this Pi.

### Routes

| Route | Purpose | Writes |
|---|---|---|
| `GET /` | Health/landing page: "Buildathon Radar tracker is running." Used to verify the tunnel and as the target for stray visits to the bare subdomain. | none |
| `GET /track?event_id=...&t=...` | Transition to `tracked` | `events` UPDATE + `action_log` INSERT |
| `GET /applied?event_id=...&t=...` | Transition to `applied` | `events` UPDATE + `action_log` INSERT |

GET is deliberate and locked: the only client is a clicked link in a static
email. The endpoints are idempotent (re-clicking never changes state a second
time or errors), which is the property that makes state-changing GET acceptable
here.

### Request handling, per endpoint

```
parse event_id and t from query string
if t missing or HMAC-invalid for (action, event_id):
    log (action, event_id, 'bad_token'); return 403 page
row = SELECT * FROM events WHERE event_id = ?
if row is None:
    log (action, event_id, 'unknown_event'); return 404 page
if rank(row.state) >= rank(requested_state):
    log (action, event_id, 'noop'); return 200 "already" page
UPDATE events SET state=?, {tracked_at|applied_at}=now, updated_at=now
    WHERE event_id=?
log (action, event_id, 'ok'); return 200 confirmation page
-- (2.5 note: a future calendar trigger attaches exactly here, after a
--  successful 'ok' transition: POST event details to an n8n webhook that
--  creates the Google Calendar entry. OAuth lives in n8n, not here. Do not
--  build it; leave a one-line comment at this point in the code.)
```

SQLite access: open a fresh `sqlite3` connection per request (cheap, sidesteps
thread-affinity issues under uvicorn), `busy_timeout=5000`, WAL already set on
the file. All store operations live in `tracker_store.py`; the FastAPI module
contains no SQL, mirroring how `digest.py` contains no SMTP.

Config: `TRACKER_SECRET` read via `python-dotenv` at import, same pattern as
`deliver.py`. If it is missing at startup, the app should fail fast with a
clear message (a service that cannot verify tokens must not run open).

### The confirmation page

One shared renderer, `_page(title, lines, accent)`, returning a complete
self-contained HTML document: no external assets, no JavaScript, inline CSS
only, system font stack, the project's teal palette (`#0d9488` on `#f6f4ef`),
`<meta name="viewport">` so it reads well on the phone where it will always be
opened. Roughly:

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Buildathon Radar</title></head>
<body style="margin:0; padding:0; background-color:#f6f4ef;">
  <!-- single centered card, max-width 480px -->
  <!-- big status line, event title, dates, a link back to the event page -->
</body></html>
```

Page catalogue (every case explicit so the executor builds them all):

| Case | HTTP | Content |
|---|---|---|
| Tracked OK | 200 | "📌 Tracked" headline; event title; "Starts {event_start}" if known; "This event will reappear in your Sunday digest as a reminder until it starts."; link "Open event page" to the stored `url`. |
| Applied OK | 200 | "🎯 Applied" headline; event title; "It's now in your participation log at the bottom of every digest."; event-page link. |
| Already in state (noop) | 200 | "Already tracked" / "Already applied" headline; event title; "Marked on {tracked_at/applied_at date}. Nothing was changed."; event-page link. A `/track` click on an already-applied event says "Already applied. Applied outranks Track, so nothing was downgraded." |
| Unknown event_id | 404 | "Unknown event" headline; "This link may be from a digest sent before tracking existed, or the event was never in a digest. Nothing was recorded." No event link (there is no stored row to trust). |
| Missing/invalid token | 403 | "Invalid link" headline; "This link is missing its signature or the signature does not match. Nothing was recorded." |
| Malformed request (no event_id) | 400 | Same visual shell, "Malformed link." |

Every page is self-explanatory with zero context: the recipient may open one
weeks after the email arrived. All dynamic strings are HTML-escaped with the
same discipline as `digest._esc` (title and url come from stored data, but
escape anyway).

### Error handling beyond pages

- Any unexpected exception: FastAPI's default 500 is acceptable; uvicorn logs
  to the journal (`journalctl --user -u buildathon-tracker.service`).
- SQLite locked beyond busy_timeout: surfaces as a 500; acceptable at this
  traffic level (one human, a few clicks a week, plus one writer on Sundays).
- The service never sends email and never calls Claude. It has no reason to.

---

## 4. The security decision: signed links, not open endpoints

**Recommendation: sign every button link with an HMAC token. Do not rely on
event_id unguessability.**

Reasoning:

- The event_id space is not unguessable. It is a readable slug built from
  public data (`google-deepmind-bangalore-hackathon-2026-08-01` shape:
  normalized host + title + date), and `derive_event_id` is published in this
  repo, which is public (the derivation is fully reproducible by anyone from
  the public Devpost/Devfolio listings). Leaving the endpoints open means
  anyone who knows the project exists can forge Track/Applied writes and
  pollute the participation log. The impact is only a corrupted personal log,
  but the whole point of Unit B is that the log is trustworthy.
- The cheap fix is genuinely cheap: `t = HMAC-SHA256(TRACKER_SECRET,
  f"{action}:{event_id}")`, hex, truncated to 20 chars, appended to the link by
  `digest.py` at render time and verified by the service with `hmac.compare_digest`.
  Stdlib only, one secret in `.env`, one sign function and one verify function
  in `tracker_store.py`, shared by both processes. Binding the action into the
  MAC means a Track link cannot be replayed as an Applied link.
- Tokens are deliberately not time-limited. A digest email is acted on days or
  weeks later; expiry would break the primary use case for no real gain.
- Residual accepted risk, stated so it is not rediscovered later: anyone who
  possesses a full signed URL (an email scanner that follows links, a forwarded
  email) can trigger that one action for that one event. Idempotency caps the
  damage at a single spurious state upgrade, visible in `action_log` and in the
  next digest, and correctable later by 2.4's dashboard (or today by a one-line
  sqlite3 UPDATE). Gmail-to-self delivery makes scanner prefetch unlikely in
  practice. This is proportionate for a personal tool; do not build more.

Secret handling: `TRACKER_SECRET` is added to `.env` by the USER before the
build (§11), because CONTRIBUTING.md marks secrets as a pause/flag zone for the
executor. The executor adds the placeholder line to `.env.example` only.

---

## 5. Cloudflare subdomain setup

Verified on 2026-07-14: tunnel `pi-home` (UUID
`41ef69c7-77c9-449c-9c0b-5cfb09a18dae`), authoritative config at
`~/.cloudflared/config.yml` (user-owned, editable without sudo), synced copy
consumed by the system `cloudflared` service at `/etc/cloudflared/config.yml`.
Fourteen hostnames exist; the catch-all `http_status:404` rule is last. Backup
copies (`config.yml.bak*`) show the established convention of backing up before
editing.

Steps (executor, Phase 7):

1. Back up, no sudo needed:

```bash
cp ~/.cloudflared/config.yml ~/.cloudflared/config.yml.bak.$(date +%Y%m%d-%H%M%S)
```

2. Edit `~/.cloudflared/config.yml`: insert this ingress rule **before** the
   final catch-all line (`- service: http_status:404`), matching the file's
   existing two-line-per-host formatting:

```yaml
  - hostname: radar.job-joseph.com
    service: http://localhost:8015
```

3. Create the DNS route (runs as jcube, no sudo; uses `~/.cloudflared/cert.pem`,
   which exists and has been used for every prior subdomain):

```bash
cloudflared tunnel route dns pi-home radar.job-joseph.com
```

4. Sync and restart (both commands are already passwordless sudo on this
   machine, verified in §7):

```bash
sudo cp /home/jcube/.cloudflared/config.yml /etc/cloudflared/config.yml
sudo systemctl restart cloudflared
sudo systemctl status cloudflared
```

5. Wait ~30 seconds, then verify from the Pi:

```bash
curl -s https://radar.job-joseph.com/          # health page HTML
```

**Prod-safety notes for the executor, read before Phase 7:**

- Restarting `cloudflared` briefly interrupts every tunnel-backed subdomain on
  this Pi, including `pi.job-joseph.com` (SSH over the tunnel). If this session
  itself is connected through that tunnel, the connection may drop for a few
  seconds; cloudflared restarts in seconds and reconnects on its own. Perform
  the edit, cp, and restart as separate commands (never a chained one-liner
  that could half-apply), and verify `sudo systemctl status cloudflared` shows
  `active (running)` afterward.
- If the edit turns out malformed, restore the backup, re-sync, restart. That
  is the entire rollback.
- 502 from `radar.job-joseph.com` after this means the tunnel is fine and the
  tracker service is not listening on 8015; fix the service, not the tunnel.

---

## 6. The systemd service: user service, not system service

**Recommendation: a `systemctl --user` service, `buildathon-tracker.service`.**

Justification:

- This project's hard convention is "no sudo is used anywhere in this project"
  (CLAUDE.md); the digest timer is already a user unit and lingering is already
  enabled for jcube (verified: the digest timer fires headless today). A user
  service runs at boot without a login session under exactly the same
  mechanism.
- The tunnel reaches the service over localhost TCP; cloudflared does not care
  which systemd manager owns the listener.
- Choosing a user service collapses the executor's sudo needs for systemctl to
  zero. The only sudo left in the whole build is the cloudflared sync/restart
  pair (§7), which recon shows is already granted.
- The pi-service-migration skill's default is a system service, but that
  default exists for projects without the user-service convention. This repo
  has the convention, and its scheduler README documents it. Consistency wins.

The unit file, committed at `scheduler/systemd/buildathon-tracker.service`:

```ini
[Unit]
Description=Buildathon Radar tracker service (Track/Applied click endpoints)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/jcube/projects/buildathon-radar
ExecStart=/home/jcube/projects/buildathon-radar/venv/bin/uvicorn buildathon_radar.tracker_service:app --host 127.0.0.1 --port 8015
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Notes: absolute venv uvicorn path (scheduled units inherit no venv);
`WorkingDirectory` at the repo root so `.env` and `tracker.db` resolve; user
target `default.target`, not `multi-user.target`; `Restart=on-failure` because
this is a long-running service, unlike the oneshot digest. There is no
`Persistent=true` footgun here; that is a timer directive and this unit has no
timer.

Install (executor, Phase 6, no sudo):

```bash
cp scheduler/systemd/buildathon-tracker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now buildathon-tracker.service
systemctl --user status buildathon-tracker.service
curl -s http://127.0.0.1:8015/
```

Logs: `journalctl --user -u buildathon-tracker.service`.

---

## 7. Sudo scope

Because §6 chose a user service, the executor needs sudo for exactly two
operations, both in Phase 7:

| # | Command | Why |
|---|---|---|
| 1 | `/usr/bin/cp /home/jcube/.cloudflared/config.yml /etc/cloudflared/config.yml` | Sync the edited tunnel config to where the system cloudflared service reads it |
| 2 | `/usr/bin/systemctl restart cloudflared` | Make cloudflared load the new ingress rule |

(`sudo systemctl status cloudflared` is also used for verification and is
likewise already granted.)

**Verified 2026-07-14 (`sudo -l` on jobpi): all of these rules already exist**,
left in place by earlier deployments (the `pi-services` and
`journey-visualiser-deploy` drop-ins in `/etc/sudoers.d/`). Both the
`/bin/cp` and `/usr/bin/cp` spellings of rule 1 are present, and
`/usr/bin/systemctl restart cloudflared` and `status cloudflared` are present.
`sudo`'s `secure_path` resolves bare `cp` to `/usr/bin/cp` and bare `systemctl`
to `/usr/bin/systemctl`, so the plain commands in §5 match the existing rules
as-is.

**Therefore the expected user action is verification only.** Run this before
the build; it must print at least one `cp ... cloudflared` rule and one
`systemctl restart cloudflared` rule:

```bash
sudo -l | grep -i cloudflared
```

**Contingency block, only if the verification above prints nothing** (for
example if the old drop-ins have been cleaned up by then). This is the one
step that inherently needs the real sudo password, which is exactly why the
user does it and not the executor. One rule per line, exact commands, applied
via `sudo tee`, validated before use:

```bash
sudo tee /etc/sudoers.d/buildathon-tracker-deploy > /dev/null <<'EOF'
jcube ALL=(ALL) NOPASSWD: /usr/bin/cp /home/jcube/.cloudflared/config.yml /etc/cloudflared/config.yml
jcube ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart cloudflared
jcube ALL=(ALL) NOPASSWD: /usr/bin/systemctl status cloudflared
EOF
sudo chmod 0440 /etc/sudoers.d/buildathon-tracker-deploy
sudo visudo -c
```

Instructions to the Sonnet executor, binding:

- Assume passwordless sudo for the two cloudflared commands is already in
  place. Confirm it non-interactively in Phase 0 with
  `sudo -n cp /home/jcube/.cloudflared/config.yml /etc/cloudflared/config.yml --help >/dev/null 2>&1 || sudo -ln | grep -i cloudflared`
  (or simply `sudo -ln | grep -i cloudflared`). If the rules are absent, STOP
  and flag for the user; do not attempt to create sudoers files, do not prompt
  for a password, do not widen scope.
- No other command in this build may use sudo. Every systemctl call for the
  tracker unit is `systemctl --user`.

---

## 8. Email buttons and the participation log (Unit B)

All HTML lives in `digest.py` and follows the template's established hard
rules, verified against the current code: table-based layout, `role="presentation"`,
every CSS property inline, `FONT_STACK` system fonts, explicit
`background-color` on every `<td>`, fluid `width="100%"` tables with
`max-width`, `WRAP` (word-break) on every text cell, no JavaScript, no external
assets, all dynamic text through `_esc`.

### Prerequisite plumbing: event_id must reach the renderer

`fetch_events` currently derives `event_id` internally and does not put it on
the item dict. Change: attach `"event_id": event_id` to every item it returns
(a 14th key next to `event_start`/`event_end`). The agent's stanza serializer
reads named keys only, so the extra key is invisible to the prompt; the guard
passes the whole item through on a match, so `pick["item"]["event_id"]` is
available to `digest.py` and to `main.py`'s upsert with no other changes.
Dry runs derive ids deterministically from the same inputs, so buttons render
identically in dry-run output.

Link construction, in one helper in `digest.py` (base URL as a module constant
`TRACKER_BASE = "https://radar.job-joseph.com"`):

```python
def _action_url(action, event_id):
    token = tracker_store.sign_action(action, event_id)  # HMAC, §4
    return f"{TRACKER_BASE}/{action}?event_id={quote(event_id)}&t={token}"
```

If `TRACKER_SECRET` is unset (for example a fresh checkout), the helper
returns None and the card renders without buttons rather than with unsigned
dead links; the digest must never fail to build because the tracker layer is
unconfigured.

### The buttons: bulletproof-button technique

Gmail strips `<button>` and ignores `<style>`; the email-safe button is a
padded `<td>` with an explicit background color containing a fat-tap-target
`<a>` styled `display:inline-block`. The color IS the td, the link fills it.
One new row inside the existing card inner table, after the score/source row
(and after the why row when present), so the card reads title, meta, dates,
score, why, actions:

```html
<tr>
<td style="background-color:{CARD_BG}; padding:12px 0 0 0;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0">
<tr>
<td style="background-color:{SCORE_BADGE_BG};">
<a href="{track_url}" style="display:inline-block; padding:9px 16px; font-family:{FONT_STACK}; font-size:13px; font-weight:bold; color:#ffffff; text-decoration:none;">&#128204; Track</a>
</td>
<td style="background-color:{CARD_BG}; width:10px; font-size:0; line-height:0;">&nbsp;</td>
<td style="background-color:{CARD_BG}; border:1px solid {SCORE_BADGE_BG};">
<a href="{applied_url}" style="display:inline-block; padding:8px 15px; font-family:{FONT_STACK}; font-size:13px; font-weight:bold; color:{SCORE_BADGE_BG}; text-decoration:none;">&#127919; Applied</a>
</td>
</tr>
</table>
</td>
</tr>
```

Design decisions inside those constraints: Track is the filled primary button
(teal `#0d9488`, the existing score-badge color, so the palette stays coherent);
Applied is the outlined secondary (1px teal border on the card background, 1px
less padding so both buttons sit at equal height); a fixed 10px spacer cell
with explicit background separates them; the inner button table is NOT
width-100%, so the buttons hug their content and the pair fits any viewport
without wrapping (two short labels total well under 200px). Emoji as text
glyphs, consistent with the tier headers. Square corners: `border-radius` is
omitted because the existing template uses none anywhere; consistency over
decoration.

The plain-text markdown part (`build_digest`) is unchanged: buttons are an
HTML-part affordance. The plain part remains the readable fallback and the
console output, and cluttering it with long signed URLs would hurt both.

### The participation log (and tracked reminders)

Rendered at the bottom of the HTML digest, after the last tier section and
before the health footer. `main.py` passes two lists of tracker rows
(`tracked_events`, `applied_events`, from the §2 queries) into
`build_html_digest` as new keyword arguments defaulting to empty lists, so
every existing call site and test keeps working.

Two small sections sharing one visual language (a header row styled like the
existing tier headers, then a single card-like table):

**📌 Tracked** (renders only when non-empty): one compact row per tracked
event: linked title, then start date. This is what makes the Track button mean
something; per ROADMAP 2.2, a tracked event keeps reappearing as a standing
reminder, independent of the cache's resurface logic, until its dates pass.
These are reminder lines rendered from the store, not re-scored cards; Claude
never sees them again.

**🗂️ Participation log** (always renders): the 2.3 table. Three columns:

| Event | Starts | Ends |
|---|---|---|
| linked title (word-break) | `event_start` formatted `%b %d, %Y`, else "TBD" | `event_end` likewise, else "TBD" |

Email-safe construction: an outer full-width card table on `CARD_BG` inside
the usual `PAGE_BG` padding cell (same shell as event cards); a header row of
three `<td>`s, explicit `background-color:{WHY_TINT_BG}`, bold 12px; data rows
at 13px with `{WRAP}` on the title cell and `white-space:nowrap` on the two
date cells; column widths 50% / 25% / 25% via `width` attributes on the header
cells. The fluid-width and word-break conventions from the mobile-wrapping fix
apply to the title cell, and dates are short enough to never wrap.

**Empty state** (no applied events yet): the section header still renders,
followed by a single full-width cell instead of the table:

```
Nothing here yet. Tap "Applied" on an event card after you register, and it
will appear here with its dates until the event ends.
```

(13px, italic, muted `#6b7b7b`, on `CARD_BG`.) Always rendering the section
keeps the feature discoverable in every digest and teaches the buttons'
purpose; the one-line cost is trivial. The Tracked section, by contrast, is
omitted when empty because it is a reminder strip, not a ledger, and an empty
reminder says nothing.

Dry runs pass empty lists (no store read), so a dry-run digest shows the
buttons plus the participation log's empty state, which is itself a useful
render check.

### main.py wiring (send-path adjacent; see Phase 5 pause rule)

```python
valid_picks, dropped_picks = validate_picks(...)
# NEW, non-dry only:
#   conn = tracker_store.connect()
#   tracker_store.upsert_seen(conn, [p["item"] for p in valid_picks])
#   tracked_events = tracker_store.get_tracked_open(conn, today)
#   applied_events = tracker_store.get_applied_open(conn, today)
# dry run: tracked_events = applied_events = []
...
html_digest = build_html_digest(..., tracked_events=tracked_events,
                                applied_events=applied_events)
```

Failure containment: the tracker read/upsert block is wrapped in its own
try/except that logs a warning and falls back to empty lists. A broken
tracker.db must never stop the Sunday email; that invariant outranks the new
feature.

---

## 9. Build plan: ordered, verifiable phases

Global rules for the executor:

- Phases strictly in order; each ends with its verification green.
- Per CONTRIBUTING.md: commit and push verified non-breaking work at each
  phase boundary. PAUSE AND FLAG for human review, instead of pushing, any
  change touching the send/delivery path, the scheduler/timer, or secrets.
  Phase 5 (main.py) is send-path adjacent and Phase 6 (new unit) is
  scheduler-adjacent; both are marked below. The Sunday email failing,
  misfiring, or double-sending is the definition of breaking prod.
- No live Claude calls except the single `--dry-run` in Phase 8. Never invoke
  `send_digest` with a real message. Never run `main.py` without `--dry-run`.
- Never touch `buildathon-radar.timer` or `buildathon-radar.service` (the
  digest units). This build adds a sibling unit; it does not modify the timer.
- All tests mock nothing external except as stated in §10; SQLite in tests is
  real, on `tmp_path`.
- Sudo: only the two cloudflared commands, only in Phase 7, assumed already
  passwordless (§7). Everything else is sudo-free.

**Phase 0: preconditions (read-only).**
Confirm `sudo -ln | grep -i cloudflared` shows the cp and restart rules;
confirm `grep -c TRACKER_SECRET .env` is 1; confirm port 8015 is free
(`ss -tln | grep 8015` empty); confirm `systemctl --user is-active
buildathon-tracker.service` reports inactive/not-found (no half-built prior
state). If any check fails, stop and flag; do not improvise around a missing
precondition.
*Verify:* all four checks pass. Nothing to commit.

**Phase 1: dependencies and store.**
`venv/bin/pip install fastapi uvicorn httpx`; add the three names to
`requirements.txt` (unpinned, matching house style). Append `tracker.db`,
`tracker.db-wal`, `tracker.db-shm` to the buildathon-radar block in
`.gitignore`. Implement `buildathon_radar/tracker_store.py`: `connect()` (WAL,
busy_timeout, schema init idempotent via CREATE IF NOT EXISTS), `upsert_seen`,
`apply_action` (the ranked transition + action_log write, returning a result
enum and the row), `get_tracked_open`, `get_applied_open`, `sign_action`,
`verify_action`. Tests in `tests/test_tracker_store.py` on `tmp_path`
databases: schema creates cleanly twice; upsert inserts then refreshes metadata
without touching state; every transition cell of the rank matrix (track on
seen, applied on seen, applied on tracked, track on applied noop, repeat-click
noop); date filters of both queries including NULL dates; sign/verify round
trip; verify rejects a tampered event_id, a cross-action token, and an empty
token.
*Verify:* `venv/bin/pytest` green. Commit and push ("safe" zone).

**Phase 2: the FastAPI service.**
Implement `buildathon_radar/tracker_service.py` per §3: three routes, the page
renderer, all six page cases, fail-fast on missing `TRACKER_SECRET`,
per-request connections, the 2.5 attach-point comment. Tests in
`tests/test_tracker_service.py` with `fastapi.testclient.TestClient` against a
`tmp_path` DB (point the store at it via its path argument; monkeypatch the
module constant if needed): valid track click writes state and log and returns
200 containing the event title; repeat click returns the "already" page and
writes only a log row; unknown id 404; bad token 403 with no DB write; missing
event_id 400; `/` health 200.
*Verify:* `venv/bin/pytest` green. Commit and push.

**Phase 3: fetcher event_id passthrough.**
Attach `event_id` to every item `fetch_events` returns (both the fresh-record
and the resurfaced paths). Extend `tests/test_fetcher.py`: every returned item
carries a non-empty `event_id`; the id equals `derive_event_id(item)` (or the
url-index/legacy fallback) so the emailed id always matches the cache key.
*Verify:* `venv/bin/pytest` green, and
`venv/bin/python -m buildathon_radar.fetcher` (live, read-only) shows items
with `event_id` populated. Commit and push.

**Phase 4: digest template (buttons + log sections).**
Implement §8 in `digest.py`: `_action_url` helper (None-safe without secret),
button row in `_html_card_row`, `tracked_events`/`applied_events` kwargs on
`build_html_digest`, the two sections with the empty state. Extend
`tests/test_digest.py`: card HTML contains both hrefs with the right base,
urlencoded event_id, and a token verifiable by `verify_action`; no button row
when the secret is unset; applied rows render title link and both dates; "TBD"
fallback for missing dates; empty-state copy when `applied_events` is empty;
Tracked section omitted when empty; plain-text `build_digest` output unchanged
byte-for-byte for the same inputs. Also render one full sample digest (fixture
picks + fake tracker rows + empty-state variant) to the session scratchpad and
eyeball the structure.
*Verify:* `venv/bin/pytest` green; sample HTML written and inspected. Commit
and push (CONTRIBUTING explicitly lists the digest template as safe).

**Phase 5: main.py wiring. SEND-PATH ADJACENT: commit locally, do NOT push;
pause and flag for human review.**
Add the §8 wiring block: non-dry upsert of validated picks, the two store
reads, the try/except containment, empty lists on dry runs. No change to
`send_digest` or its call.
*Verify:* `venv/bin/pytest` green, then `venv/bin/python main.py --dry-run`
exits 0 with a normal digest and no `tracker.db` created (dry run must not
touch the store). Flag: "main.py orchestrator changed; review before push."

**Phase 6: the service unit. Scheduler-adjacent but a NEW sibling unit; the
digest timer is untouched. Proceed, note it in the summary.**
Write `scheduler/systemd/buildathon-tracker.service` exactly per §6; update
`scheduler/systemd/README.md` with its install/verify/log commands; install and
enable per §6 (all `systemctl --user`, no sudo).
*Verify:* `systemctl --user status buildathon-tracker.service` active
(running); `curl -s http://127.0.0.1:8015/` returns the health page; a full
local round trip: build a signed URL with
`venv/bin/python -c "from buildathon_radar.tracker_store import ..."`, insert a
throwaway row the same way, `curl` the signed `/track` URL against
`127.0.0.1:8015`, confirm the 200 page and the DB state change, then curl again
and confirm the "already" page. Then delete the throwaway row. Confirm
`systemctl --user list-timers` still shows the digest timer untouched. Commit
and push the unit file and README.

**Phase 7: the tunnel. PROD-AFFECTING: the cloudflared restart briefly
interrupts every subdomain on this Pi. Execute steps §5 one at a time and
verify after each.**
Backup, ingress edit, DNS route, sudo cp, sudo restart, status check, per §5.
*Verify:* `curl -s https://radar.job-joseph.com/` returns the health page from
the public internet; repeat the Phase 6 signed round trip against the public
URL with a second throwaway row (insert, click, verify, clean up); spot-check
one existing subdomain (e.g. `curl -sI https://photorank.job-joseph.com` or
another from the config) still answers, proving the restart hurt nothing.
Nothing in the repo changes this phase except possibly notes; commit any doc
touch-ups.

**Phase 8: registry, docs, final gate.**
Update `~/projects/dev-meta/PORTS.md`: add `8015 buildathon-radar tracker
FastAPI backend, Pi, active`, and backfill the drifted 8013/8014 entries
(hunter and echo, visible in the tunnel config) so the registry matches
reality; commit and push dev-meta per its own convention. In this repo: update
`SPEC.md` (tracker architecture + schema summary), `CLAUDE.md` (structure,
commands for the new service), `ROADMAP.md` (mark 2.2/2.3 shipped),
`.env.example` (+`TRACKER_SECRET=` placeholder line and dependency comment).
*Final gate, all four:* `venv/bin/pytest` green;
`venv/bin/python main.py --dry-run` exits 0 (the build's one live Claude
call); `systemctl --user status buildathon-tracker.service` active;
`curl -s https://radar.job-joseph.com/` healthy. Commit and push docs.

**Left for the human (proof of life, after the next real Sunday run):** open
Sunday's digest on the phone, tap Track on one event and Applied on another,
confirm both confirmation pages render, and confirm the following week's
digest shows the tracked reminder and the populated participation log. The
executor cannot do this: it requires the real email on the real phone.

---

## 10. Testing approach

- **What is real in tests:** SQLite (a `tmp_path` file per test; WAL and the
  transition logic are exactly the code under test) and the FastAPI app (via
  `TestClient`, which runs it in-process without a port).
- **What is mocked/absent:** the Anthropic client (unchanged rule: always
  mocked, and Units A/B add no new Claude calls); SMTP (unchanged, never
  called); the network (no test touches Devpost/Devfolio/Cloudflare); the
  production `tracker.db` (tests must never open the repo-root file; the store
  takes its path as a parameter precisely so tests can point it elsewhere).
- **Coverage inventory:** store transitions and queries (Phase 1 list),
  endpoint behaviour incl. all page cases (Phase 2 list), event_id passthrough
  (Phase 3), button/log rendering incl. token verifiability and the unset-secret
  and empty-state paths (Phase 4), and the existing suites staying green
  throughout as the regression net.
- **The dry-run-equivalent proof for the service** (since `--dry-run` proves
  the digest, something must equivalently prove the service live): the Phase 6
  local loop, i.e. the enabled unit serving on 127.0.0.1:8015, a signed URL
  built with the real secret, a real click via curl, an observed SQLite state
  change, an observed idempotent second click, then cleanup of the throwaway
  row. Phase 7 repeats it once through the public URL. Together they prove
  unit file, env loading, token path, DB path, tunnel, and DNS, with zero
  emails sent.
- **The digest side's proof** stays `main.py --dry-run`, which after Phase 5
  additionally proves that a dry run leaves the store untouched.

---

## 11. Pre-run human checklist

Everything the user does before handing this plan to the Sonnet executor. Kept
minimal on purpose.

1. **Sudo scope: verify (expected: already granted).** Run:

   ```bash
   sudo -l | grep -i cloudflared
   ```

   Expect to see `cp /home/jcube/.cloudflared/config.yml /etc/cloudflared/config.yml`
   and `systemctl restart cloudflared` NOPASSWD rules (they exist as of
   2026-07-14, left by earlier deploys). **Only if that prints nothing**, apply
   the drop-in (this is your one real-sudo-password step):

   ```bash
   sudo tee /etc/sudoers.d/buildathon-tracker-deploy > /dev/null <<'EOF'
   jcube ALL=(ALL) NOPASSWD: /usr/bin/cp /home/jcube/.cloudflared/config.yml /etc/cloudflared/config.yml
   jcube ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart cloudflared
   jcube ALL=(ALL) NOPASSWD: /usr/bin/systemctl status cloudflared
   EOF
   sudo chmod 0440 /etc/sudoers.d/buildathon-tracker-deploy
   sudo visudo -c
   ```

2. **Create the signing secret** (keeps the executor away from `.env`, per
   CONTRIBUTING's secrets rule):

   ```bash
   cd ~/projects/buildathon-radar
   python3 -c "import secrets; print('TRACKER_SECRET=' + secrets.token_hex(32))" >> .env
   ```

3. **Cloudflare account sanity** (should just work; `cert.pem` exists and has
   minted every prior subdomain):

   ```bash
   cloudflared tunnel list        # should list pi-home without prompting login
   ```

   If it demands a login, run `cloudflared tunnel login` interactively before
   the build. DNS for the new subdomain is created by the executor via
   `cloudflared tunnel route dns` and is usually live within seconds on
   Cloudflare; no advance DNS work is needed, just tolerate the ~30 second
   wait noted in Phase 7.

4. **Answer the open questions in §12** and note any non-default answers at
   the top of this file for the executor.

5. Leave the Pi powered and online. Nothing else: no new accounts, no new
   keys, no package installs (the executor pip-installs into the existing
   venv itself).

---

## 12. Open questions for the user

Each has a stated default; the executor builds the default unless overridden
at the top of this file.

1. **Tracked-reminder section scope.** ROADMAP 2.2 defines Track as "bring this
   event back into next week's digest as a standing reminder", so this plan
   includes a small 📌 Tracked section rendered from the store (§8); without
   it, the Track button writes state nothing displays until 2.4. Strictly,
   though, the Unit B brief named only buttons and the participation log.
   Default: build the Tracked section as specified. Alternative: defer it and
   ship Track as state-capture only.

2. **Participation log empty state: always visible?** Default: the 🗂️ section
   renders in every digest, showing the one-line empty-state note until the
   first Applied click, for discoverability. Alternative: omit the section
   entirely until at least one applied event exists (quieter email).

3. **Buttons in the plain-text part.** Default: the plain-text/markdown part
   is unchanged (no signed URLs in it); buttons are HTML-only. Alternative:
   append bare track/applied URLs under each card in the plain part too, at
   the cost of long ugly links in the console output and text fallback.

4. **Token on the bare domain.** `GET /` is unauthenticated by design (a
   health/landing page with no data and no writes). Default: leave it open.
   Alternative: have it return 404 to be fully dark; this costs the easy
   tunnel health check.

Everything else this session could resolve, it resolved: SQLite schema shape
(§2), signed links (§4), port 8015 (§3), user service (§6), sudo scope already
granted (§7), button technique and log layout (§8), and phase order with
prod-affecting steps isolated (§9).
