# SPEC.md: architecture and design

## Pipeline

```
systemd timer (Sun 17:00 IST)
        |
        v
main.py --> fetcher.py --> agent.py --> guard.py --> digest.py --> deliver.py
            Devpost API     claude-sonnet-5  URL          markdown     HTML render
            Devfolio API    scores + picks   validation   assembly     archive/
            normalise       as strict JSON   vs input     (code-owned) Gmail SMTP
            cache.json                       URL set
```

Claude only selects, scores, and explains. It never authors a fact that ends
up in the email. Every venue, date, host, and prize in the digest is rendered
from the original fetched data, joined back to Claude's pick by URL.

## Sources

### Devpost (primary, global)

`GET https://devpost.com/api/hackathons`

Query parameters used: `status[]=upcoming&status[]=open`, `themes[]=Machine Learning/AI`,
`per_page=40`, `page=1` and `page=2` (per_page caps at 40 server-side; two pages
cover the roughly 60 to 90 open/upcoming AI events typically live at once).

Response: `{"hackathons": [...], "meta": {"total_count": N, "per_page": 40}}`.
Each hackathon has no ISO date, only a human string like `"May 19 - Aug 17, 2026"`
in `submission_period_dates`, parsed best-effort into a `YYYY-MM-DD` start date
(falls back to `"Unknown"` on any parse failure). `prize_amount` contains raw
HTML and is stripped with a regex.

### Devfolio (India-focused)

`POST https://api.devfolio.co/api/search/hackathons`

Body: `{"type": "application_open", "from": 0, "size": 50}` and
`{"type": "upcoming", "from": 0, "size": 50}`, both fetched and merged
(deduplicated by `uuid`). No `q` search parameter works reliably (it returned 0
hits in testing), so all ~20 open events are fetched and Claude does the
theme filtering.

Response: an Elasticsearch envelope, `{"hits": {"total": {...}, "hits": [{"_source": {...}}]}}`.
The event URL is not returned directly; it is constructed as
`https://{slug}.devfolio.co/` and was verified live to resolve. Dates are ISO
8601 UTC and are converted to IST before taking the date part.

### Luma (Bengaluru meetups, showcases, and community hackathons)

`GET https://api.luma.com/discover/get-paginated-events?discover_place_api_id=discplace-G0tGUVYwl7T17Sb&pagination_limit=50`

An undocumented but public JSON API behind Luma's own discover pages, found
by inspecting the network calls `luma.com/bengaluru` makes (the same
undocumented-but-public standing as Devpost's list API). No auth, no key.
Paginates via `pagination_cursor` from the response's `next_cursor` while
`has_more` is true, capped at 5 pages as a runaway guard.

Response: `{"entries": [{"api_id": ..., "event": {...}, "calendar": {...},
"hosts": [...]}, ...], "has_more": bool, "next_cursor": str}`. The event's
own `start_at`/`end_at` are ISO 8601 UTC, converted to IST before taking the
date part, same as Devfolio. `geo_address_info.city_state` supplies
location; `location_type` distinguishes online from offline. There is no
prize field and no themes field on this feed, so `prize` is always `""` and
`themes` is always `[]`.

Host derivation is the one genuinely tricky part: Luma events are commonly
hosted under a personal calendar rather than an organisation's, so
`calendar.name` is `"Personal"` for many entries and useless as a host
label. `normalise_luma` falls back, in order: the calendar's own name when
it is not `"Personal"`, else the first name in the entry's `hosts` list,
else `"Unknown"`.

Caveat, scoped deliberately: Luma also has a `cat-ai` category feed
(`discover_category_api_id=cat-ai`) that returns AI-tagged events ranked by
the requesting IP's inferred location. From jobpi this happened to also be
Bengaluru-scoped, but that geography is undocumented and could shift
silently if Luma changes its ranking or the Pi's network path. This build
uses the Bengaluru place feed only, which is a deterministic city id, not
an IP inference; the `cat-ai` feed is documented in
`docs/V2-SOURCING-PLAN.md` as a future option, not wired in.

### Cerebral Valley (built, currently gated off, see Known limitations)

`GET https://api.cerebralvalley.ai/v1/public/event/pull?approved=true&limit=100&offset=N`
`GET https://api.cerebralvalley.ai/v1/public/event/pull?featured=true`

Another undocumented public JSON API, found by downloading
`cerebralvalley.ai/events`'s client-fetched JS bundles and tracing the
network call (the page's own server HTML carries no event data). No auth.
The site host's `robots.txt` disallows its own `/api/`, but this is a
different host, `api.cerebralvalley.ai`, which serves no robots file.

The endpoint has no server-side date or sort filter: `approved=true`
returns the entire event ledger (roughly 3900 events at time of writing),
sorted ascending by start date, oldest first, `limit` capped at 100
server-side. `fetch_cerebralvalley` therefore reads `totalCount` from a
cheap `limit=1` call, then pages backward from the tail
(`offset = totalCount - 100`, stepping back by 100) until a page's earliest
event falls before today, capped at 6 pages as a runaway guard. `featured`
returns a small hand-curated set (3 events when last checked) with no
paging needed.

Because the upcoming window is roughly 300 events, mostly generic
non-India conference listings, a structured field-only pre-filter runs
before normalising anything: an event is kept only if it came from the
`featured` call, carries `CVEvent: true`, has `type == "HACKATHON"`, or its
`location` mentions India/Bengaluru/Bangalore or is exactly `"Remote"`.
Measured effect: roughly 300 candidates down to 10 to 30 kept per run.
There is no organiser field in the payload, so `host` is always
`"Unknown"`; `descriptionSummary` (a pre-written short blurb) feeds
`summary` when present, falling back to `description`. A `featured` event
gets `"Cerebral Valley Featured"` appended to its `themes` list, a real
structured signal the Claude prompt credits as a modest host-prestige
boost (see The Claude filter, below).

### Rejected for v1: Unstop

`GET https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&per_page=10&oppstatus=open&searchTerm=ai`
works (verified), but the result set skews heavily toward college and
student-eligibility events, and Devfolio already covers the India tier with
richer structured fields. Left as a documented v2 option.

## Normalised item contract

```python
{
    "source":    "Devpost" | "Devfolio" | "Luma" | "Cerebral Valley",
    "title":     str,
    "url":       str,   # dedup key, guard key
    "summary":   str,   # trimmed to 500 chars
    "published": str,   # "YYYY-MM-DD" or "Unknown"
    "location":  str,
    "mode":      "in-person" | "online",
    "host":      str,
    "dates":     str,
    "prize":     str,
    "themes":    list[str],
}
```

No value is ever `None`. Missing data falls back to `"Unknown"` (title, host,
published, location), `""` (dates, prize), or `[]` (themes).

## The Claude filter

Model: `claude-sonnet-5`, `max_tokens=8000`, extended thinking explicitly
disabled (`thinking={"type": "disabled"}`). See `LEARNINGS.md` for why: with
thinking enabled, a batch of 90 events caused the model to spend its entire
token budget on internal reasoning and return zero text output.

Claude receives every fetched event as a plain-text stanza (source, title,
url, host, location, mode, dates, prize, themes, summary) and a system prompt
with four blocks: persona, a four-component scoring rubric (theme fit 0 to 35,
geography 0 to 30, host prestige 0 to 25, scale and signal 0 to 10), tiering
rules (must_see >= 70, worth_a_look 50 to 69, radar 35 to 49, excluded below
35, capped at 12 picks), and a critical-constraints block forbidding invention
and requiring every URL to be copied character for character from the input.

A deliberate rubric property: theme (35) + host (25) + signal (10) sums to 70
with zero geography points, so a prestigious global online event (a major AI
lab or well-known sponsor) can reach `must_see` purely on those three
components. Geography is a bonus for local relevance, not a gate that can bury
an otherwise excellent online event. This was a specific requirement from the
project owner, who has personally won a notable global online buildathon.

The system prompt also names Luma and Cerebral Valley as sources and tells
the model not to auto-demote a well-matched meetup or community showcase
just because it lacks the word "hackathon," and to treat the
`"Cerebral Valley Featured"` theme tag (set by `fetch_cerebralvalley` on
events from its `featured=true` call) as a small positive signal inside
the existing host prestige component, not a new scoring axis.

Output is a single JSON object (`picks`, `skipped_count`, `week_note`). Parsing
tries direct `json.loads`, then strips code fences, then extracts the
substring between the first `{` and last `}`. If all three fail, one retry
call is made with a clarifying instruction; if that also fails to parse,
`run_agent` raises and the top-level fatal handler takes over.

## The anti-hallucination guard

`guard.validate_picks(picks, items)` builds a URL index from the fetched item
set (with a trailing-slash-tolerant fallback) and checks every pick's URL
against it. A match is enriched with the matched source item; the digest
renderer then takes every factual field from that item, never from Claude's
pick. A miss is dropped and counted; the run continues and the digest gets a
visible integrity line rather than failing. No fuzzy or substring matching is
used, only exact and trailing-slash-normalised comparison.

## Cache and dedup

`cache.json` is a per-event-record map keyed on the composite `event_id`
(normalized host + normalized title + start date; see `fetcher.py` for the
full record shape and the date-aware resurface logic). `--dry-run` neither
reads nor writes the cache, so it is safe to run repeatedly.

Minimal cross-source collision handling (ROADMAP.md 2.6) sits on top of
this keying, now that Luma and Cerebral Valley make cross-source overlap
real rather than hypothetical: every URL is canonicalized before dedup
(`lu.ma` folds into `luma.com`, `http://` upgrades to `https://`), so a
Cerebral Valley listing that links out to a Luma event collapses with that
same event fetched directly from Luma via the existing URL index. Each
cache record also carries a `norm_title` field; when an incoming item's URL
and composite id both miss, an exact normalized-title match against an
existing record within a 90 day date window reuses that record's
`event_id` instead of minting a second one, and the new URL is appended to
the existing record's `urls` array. This is deliberately narrow (exact
title match only, no fuzzy or LLM-assisted scoring): live recon on
2026-07-15 found a real duplicate this catches ("Build with Gemini XPRIZE"
on both Devpost and Cerebral Valley, dates 90 days apart) and a real
near-miss that fuzzy matching would have wrongly merged (two differently
named hackathons sharing two-thirds of their words on the same date). Full
entity resolution (host+date anchoring, LLM-assisted matching) stays
deferred; see `docs/V2-SOURCING-PLAN.md` section 3.

## Digest and email

`digest.build_digest` renders three tier sections (only if non-empty, sorted
by score within each), a quiet-week note when there are zero picks, and an
always-present source health footer, e.g. `Devpost: 43 new events` or
`Devfolio: FAILED (Connection timeout)`. A zero-result healthy source is
flagged with a warning marker rather than silently omitted. `deliver.py`
renders the markdown to a styled HTML email (blue accent, sans-serif), saves a
plain-text archive copy to `archive/radar_YYYY-MM-DD.md`, and sends via Gmail
SMTP SSL using the app password in `.env`. An email is sent every Sunday no
matter what, including a quiet week or a degraded run; even a fatal crash
triggers a short failure-notice email before the process exits non-zero, so
silence in the inbox always means the pipeline itself is broken.

## Failure resilience

Each source's fetch is wrapped in its own try/except; a failed source
contributes zero items and an error string to `source_health`, and the other
source's results still flow through. The agent short-circuits on empty input
without an API call. The guard degrades rather than aborts on a bad URL. The
top-level handler in `main.py` catches any uncaught exception, prints it,
attempts a failure email (only on a non-dry run), and exits 1.

## v1 non-goals

No social sources (Twitter, LinkedIn), no scraping, no Apify, no Google
Sheets, no WhatsApp. `cache.json` and Gmail SMTP are the only state and
delivery mechanisms. (Luma and Cerebral Valley, originally v1 non-goals,
shipped as the v2 sourcing expansion below.)

## v2 tracker (Units A and B): Track/Applied and the participation log

Two independent processes now share one SQLite file, `tracker.db` (WAL mode,
gitignored, at the repo root):

- The weekly digest run (`main.py`, unchanged oneshot timer) upserts every
  emailed pick into the store as `seen`, and reads the store's tracked/applied
  rows to render two new digest sections.
- `buildathon_radar/tracker_service.py`, a FastAPI app on `127.0.0.1:8015`
  (systemd user service `buildathon-tracker.service`, `Type=simple`), exposed
  publicly at `https://radar.job-joseph.com` via the existing `pi-home`
  Cloudflare Tunnel. It serves `GET /`, `GET /track?event_id=...&t=...`, and
  `GET /applied?event_id=...&t=...`, the endpoints the email's Track/Applied
  buttons link to.

`events` table (`buildathon_radar/tracker_store.py`): keyed on `event_id`, the
same composite id `fetcher.derive_event_id` produces for `cache.json`, with
event metadata (`title`, `url`, `host`, `source`, `event_start`, `event_end`)
denormalized onto the row so the participation log survives `cache.json`
entries aging out. `state` (`seen` -> `tracked` -> `applied` -> `over`) only
ever moves upward; `outcome` and `over_at` are placeholder columns for the
deferred lifecycle work (ROADMAP.md 2.4), already legal in the schema's CHECK
constraints so no migration will be needed to use them. A companion
`action_log` table records every click, including rejected ones, for
debugging.

Every Track/Applied link is HMAC-signed (`tracker_store.sign_action`,
`TRACKER_SECRET` in `.env`) over `action:event_id`, so the endpoints reject a
forged or replayed link rather than trusting the event_id alone; the id is a
readable slug reproducible from public listings by anyone reading this public
repo. Only the digest run inserts rows; the service only updates existing
ones, so a click against an event_id never in a digest gets a graceful 404.

`digest.py`'s HTML template gains a bulletproof-button Track/Applied row per
card, a "Tracked" reminder strip (omitted when empty), and an always-visible
participation log (with a one-line empty state). The plain-text digest is
unchanged.

## v2 sourcing expansion: Luma and Cerebral Valley

Both shipped 2026-07-15; see `docs/V2-SOURCING-PLAN.md` for the full recon
and build plan. Luma (Bengaluru place feed) is live in `SOURCES`.
Cerebral Valley is fully built and tested (`fetch_cerebralvalley`,
`normalise_cerebralvalley`) but deliberately not active: the module-level
`ENABLE_CV_SOURCE` constant in `fetcher.py` defaults to `False` so Luma's
real weekly behaviour can be observed on its own before a second new
source is added; see `ROADMAP.md` for the staged-activation decision and
when to flip it.

## v2 backlog

1. Unstop as a third API source, if college-tier coverage becomes wanted.
2. Deadline-reminder mode (a second mention as a cached event's close date nears).
3. Per-event calendar (.ics) attachments.
4. Lifecycle states and outcomes (ROADMAP.md 2.4), calendar integration
   (2.5), and full cross-source entity resolution beyond the minimal exact-
   title fix above (2.6), all deferred; see `docs/V2-TRACKER-PLAN.md` for
   the tracker's full architecture.
5. Luma's IP-geo-scoped `cat-ai` category feed and additional Indian
   cities' place feeds, documented but not wired in; see
   `docs/V2-SOURCING-PLAN.md`.
