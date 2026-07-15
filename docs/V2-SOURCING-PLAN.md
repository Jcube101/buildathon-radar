# V2-SOURCING-PLAN.md

Build plan for the v2 sourcing expansion: adding Luma and Cerebral Valley as
event sources alongside the existing Devpost and Devfolio. Written 2026-07-15
by an architecture session after live read-only recon from jobpi; to be
executed by a later Claude (Sonnet) session.

Why this matters: the two events that motivated this project (the Google
DeepMind Bangalore hackathon, and the Razorpay x Anthropic Claude showcase)
lived on Cerebral Valley and Luma respectively, not on Devpost or Devfolio.
During this session's recon, the Luma Bengaluru feed was carrying, live,
"India Builds with Claude - Razorpay | Anthropic | Peak XV" (2026-07-16), the
literal event class this project exists to catch, and it appears on none of
the current v1 sources. The gap is real and the fix below is verified
obtainable for free.

Hard constraints honored: no paid services anywhere (no Apify), no scraping
framework needed, both sources turn out to have real unauthenticated JSON
endpoints of the same undocumented-but-public kind as Devpost's
`devpost.com/api/hackathons`. Every endpoint, parameter, and payload below
was verified live from jobpi on 2026-07-15 with plain `curl` and the
project's standard User-Agent, no cookies, no auth headers.

---

## 1. Recon findings: Luma

### The mechanism: an undocumented public JSON API (priority path 1, no scraping needed)

Luma migrated from `lu.ma` to `luma.com` (old URLs 301). Its discover pages
are Next.js and embed full event JSON in `__NEXT_DATA__`, but better: the API
the pages call is directly reachable, unauthenticated, on both
`api.luma.com` and `api.lu.ma` (identical responses):

```
GET https://api.luma.com/discover/get-paginated-events?discover_place_api_id=discplace-G0tGUVYwl7T17Sb&pagination_limit=50
GET https://api.luma.com/discover/get-paginated-events?discover_category_api_id=cat-ai&pagination_limit=50
```

Both verified HTTP 200 with plain curl. `robots.txt` on `luma.com` restricts
only Googlebot on a few paths; `api.luma.com/robots.txt` disallows only
`/insights/`. The discover endpoints are not disallowed for any agent.

| Feed | What it returns (verified) |
|---|---|
| Place feed, `discplace-G0tGUVYwl7T17Sb` | The Bengaluru city page feed. Returned all 36 events the place reported (`has_more: false` in one page of 50), all categories (AI events plus book clubs, workshops). The place api_id is stable and was extracted from `luma.com/bengaluru`'s `__NEXT_DATA__` (note: `/bangalore` 307s to `/bengaluru`). |
| Category feed, `cat-ai` | The AI category feed. Returned 50 events, and here is the catch: it is geo-personalized by requesting IP. From jobpi (a Bengaluru IP), all 50 were Bengaluru-area AI events, and the cursor exhausted after page one. Effectively "AI events near you", and it is richer for AI than the curated place feed (50 AI events vs 36 total city events; it included AI events the place feed did not). |

Response shape (verified):

```json
{
  "entries": [ { "api_id": "evt-...", "event": {...}, "calendar": {...},
                 "hosts": [...], "guest_count": 0, ... } ],
  "has_more": false,
  "next_cursor": "eyJzdiI6..."
}
```

Pagination: `pagination_cursor=<next_cursor>` (verified working; second page
of `cat-ai` returned 0 entries, confirming the geo-scoped feed fits in one
page from here).

Real example inner `event` (trimmed, captured live; this is the motivating
event class, on the feed right now):

```json
{
  "api_id": "evt-...",
  "name": "India Builds with Claude - Razorpay | Anthropic | Peak XV",
  "start_at": "2026-07-16T...Z",
  "end_at": "2026-07-16T...Z",
  "timezone": "Asia/Kolkata",
  "url": "8v8l5x5g",
  "location_type": "offline",
  "visibility": "public",
  "geo_address_info": {
    "mode": "obfuscated", "city": "Bengaluru",
    "city_state": "Bengaluru, India", "country": "India", "region": "Karnataka"
  },
  "coordinate": {"latitude": 12.99, "longitude": 77.65}
}
```

Entry-level extras: `hosts` (list of person names, e.g. "Vineet Agarwal"),
`calendar` (organizer calendar; `name` is often "Personal" for
individually-hosted events), `guest_count`, `ticket_count`.

What is obtainable per event: name, ISO start/end (UTC, convert to IST like
Devfolio), timezone, event URL slug (`https://luma.com/{url}` verified to
resolve HTTP 200), online/offline (`location_type`), city/state/country,
host names, cover image. Single event pages additionally carry a full
`description_mirror` and `categories` (e.g. `cat-ai`) in `__NEXT_DATA__`,
verified, but per-event page fetches are NOT part of this design (volume and
politeness; the feed fields suffice for the item contract, matching how
Devpost items have no description either).

What is NOT obtainable: prize (Luma has no such field), themes (only via
per-event page categories, skipped), a reliable organization name for
individually-hosted events (see host mapping in §4).

Known limitations, stated honestly:

- The `cat-ai` feed's geography is IP-inferred and undocumented. From the Pi
  it is Bengaluru-scoped, which is exactly what this project wants, but Luma
  could change the ranking or radius silently. The place feed is the
  deterministic anchor; `cat-ai` is enrichment.
- The discover feeds returned zero `location_type: "online"` events in this
  recon. This Luma integration therefore targets the in-person
  Bengaluru/India gap (which is the original miss), not global online
  events, which Devpost already covers well.
- Undocumented API, same standing as Devpost's: it can change without
  notice. The zero-results safeguard (§5) is the tripwire.

### Verification commands (for the executor to re-run in Phase 0)

```bash
curl -s -A "Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0" \
  "https://api.luma.com/discover/get-paginated-events?discover_place_api_id=discplace-G0tGUVYwl7T17Sb&pagination_limit=50" | head -c 300
curl -s -A "Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0" \
  "https://api.luma.com/discover/get-paginated-events?discover_category_api_id=cat-ai&pagination_limit=50" | head -c 300
```

---

## 2. Recon findings: Cerebral Valley

### The mechanism: an undocumented public JSON API (priority path 1, no scraping needed)

`cerebralvalley.ai/events` is a Next.js App Router page whose server HTML
contains no event data (fully client-fetched), so scraping the HTML is a dead
end. The real backend was located by downloading the page's 35 JS chunks and
tracing the fetch call: `API_URL = https://api.cerebralvalley.ai/v1`, and the
events list calls:

```
GET https://api.cerebralvalley.ai/v1/public/event/pull?approved=true&limit=100&offset=N
GET https://api.cerebralvalley.ai/v1/public/event/pull?featured=true
```

Both verified HTTP 200, unauthenticated, plain curl. The endpoint is even
self-documenting: called bare it returns
`{"detail":"Must pass in one of featured, approved, pending, or denied to retrieve."}`.

Robots note, resolved: `cerebralvalley.ai/robots.txt` disallows `/api/` and
`*.json` on the site host, but the events API lives on a different host,
`api.cerebralvalley.ai`, which serves no robots.txt at all (Express 404).
Per-host robots semantics make the API host unrestricted; we deliberately do
NOT touch the disallowed site-host `/api/*` routes.

Response shape (verified):

```json
{
  "detail": "...", "events": [...], "totalCount": 3854, "limit": 100, "offset": 3600
}
```

Real example event (trimmed, captured live):

```json
{
  "id": "c8f46fab-5708-40cf-b8da-a803ab997f74",
  "name": "Open-source AI demo night",
  "description": "...long text...",
  "descriptionSummary": "An open-source AI demo night featur...",
  "startDateTime": "2024-08-09 00:00:00",
  "endDateTime": "...",
  "url": "https://lu.ma/...  OR  https://cerebralvalley.ai/e/...  OR eventbrite etc.",
  "location": "San Francisco, CA",
  "venue": "...",
  "type": "HACKATHON" ,
  "CVEvent": true,
  "imageUrl": "...", "featuredStartTime": null, "featuredEndTime": null,
  "platformEventData": {...}
}
```

Verified behavior of `approved=true` (the full ledger):

- `totalCount` 3854 at recon time; sorted ascending by start date, oldest
  (2024) first. `limit` caps at 100 (requesting 200 returns 100). `offset`
  paging works exactly as expected.
- No date/sort filter is honored: `upcoming`, `timeframe`, `startsAfter`,
  `order`, `sort`, `past`, `minEndDateTime` were all probed and all ignored.
  The frontend evidently pages and filters client-side.
- Therefore the fetch pattern is: read `totalCount`, then page backward from
  the tail (`offset = totalCount - 100`, stepping back) until a page's first
  event starts before today. The current-through-future window sat at
  offsets ~3450 to 3854 at recon time, roughly 300 events covering the next
  two months plus far-future listings out to 2028.
- Content profile of the upcoming window (measured): heavily US/UK
  (SF 16, London 13, NYC 9 in one 100-page sample), mostly
  community-submitted conference listings with `type` unset and
  `CVEvent: false`. Occasional `Remote` events (4 in that sample) and rare
  India listings (one "Bengaluru, India" observed in the historical set).

Verified behavior of `featured=true` (the curated tier):

- Returned exactly 3 events at recon time, all near-term and all precisely
  this project's prestige class: "fal x Sequoia 72-Hour Video Hackathon"
  (Remote), "The Future of Agentic AI in Healthcare - Abridge x Anthropic"
  (SF), "AI Supply Chain Hackathon 2026" (SF). This is CV's hand-picked
  shelf, the DeepMind-Bangalore-class surface.

What is obtainable: name, full description AND a pre-written
`descriptionSummary` (great for the item `summary`), start/end datetimes
(naive `YYYY-MM-DD HH:MM:SS` strings, treated as UTC by CV's own frontend
code, so parse date-part best-effort), location string, venue, type
(HACKATHON/COWORKING/unset), `CVEvent` (CV-curated flag), and the external
registration `url`, which is frequently a Luma link (5 of 50 sampled were
`lu.ma/...`), sometimes CV's own page, Partiful, Eventbrite.

What is NOT obtainable: a host/organizer field (host must fall back to
"Unknown" or be inferred nowhere; the name carries the brand), prize,
themes.

Volume control (required): unlike Devfolio's ~20, CV's upcoming window is
~300 events of mostly low-relevance US conference noise. Sending all of it
to Claude weekly is wasteful and would bloat the cache. The design (§4)
applies a structured, code-side pre-filter using only API fields (no content
judgment, so no hallucination surface): keep an upcoming-window event iff
`featured` OR `CVEvent` is true OR `type == "HACKATHON"` OR `location`
contains "India"/"Bengaluru" OR `location` is "Remote". Measured against the
live window this keeps roughly 10 to 30 events. The DeepMind-Bangalore class
is covered three ways (CVEvent, HACKATHON, India).

### Verification commands (for the executor to re-run in Phase 0)

```bash
curl -s -A "Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0" \
  "https://api.cerebralvalley.ai/v1/public/event/pull?featured=true" | head -c 300
curl -s -A "Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0" \
  "https://api.cerebralvalley.ai/v1/public/event/pull?approved=true&limit=100&offset=3600" | head -c 300
```

---

## 3. The entity-resolution assessment (ROADMAP 2.6)

Live scan performed this session: all four sources fetched fresh
(Devpost 70, Devfolio 24, Luma 68 deduped across both feeds, Cerebral
Valley 303 in the Jul-Sep window), 465 events total, compared by the
project's own `_normalize_title` plus a looser same-date word-overlap sweep.

**Verdict: overlap is real, currently rare, and the observed case would NOT
be caught by the existing event_id derivation. Minimal collision handling is
justified and specified below. Full 2.6 entity resolution stays deferred.**

What was actually observed:

1. **One genuine cross-source duplicate, live right now:** "Build with
   Gemini XPRIZE" appears on Devpost (`event_start` 2026-05-19, the
   submission window start) and on Cerebral Valley (2026-08-17, evidently
   the finale/deadline date). Identical normalized titles, but different
   recorded start dates and different host fields (Devpost: "XPRIZE"; CV:
   none). The composite event_id (host+title+date) therefore yields two
   different ids, and the event would be announced twice. This is exactly
   the failure 2.6 predicted, observed in the wild on the first scan.
2. **One fuzzy near-miss that is a false positive:** "GatewayGS & The AEI
   Initiative: AI 4 Earth Hackathon" (Devpost) vs "AI Internship Hackathon"
   (Luma), same date, 67% word overlap, genuinely different events. Direct
   live evidence that loose fuzzy matching (2.6 option C territory) would
   produce false merges. Do not build it.
3. **A free win already in the code:** CV's `url` field is often the
   literal Luma link for the same event. `fetch_events` already maintains a
   per-run and cached `url_index`, so two sources carrying the same URL
   already collapse into one record, provided the URL strings match. Luma
   URLs appear as both `lu.ma/<slug>` and `luma.com/<slug>`, so a domain
   canonicalization (rewrite `lu.ma/` to `luma.com/` before dedup) turns
   this existing mechanism into real cross-source dedup for the
   CV-links-to-Luma case at zero new complexity.

Minimal viable collision handling for this build (2.6 "option A minus",
normalization-anchored, scoped to what was observed):

- **URL canonicalization (mechanical):** one helper applied to every item's
  `url` at normalise time: strip whitespace, rewrite `http://` to
  `https://`, rewrite `lu.ma/` host to `luma.com/`. Feeds the existing
  url_index dedup. Handles observed case 3.
- **Exact-normalized-title merge (narrow):** inside `fetch_events`, after
  the per-source loops produce their records, and against the cache across
  runs: if an incoming item's `_normalize_title` output exactly equals that
  of an existing record (same run or cached), AND the two start dates are
  within 90 days of each other or either is unknown, treat it as the same
  event: reuse the existing `event_id`, append the new URL to the record's
  `urls` array (the mechanism 2.6 pre-built for exactly this), and do not
  emit a second item. Exact match only, no similarity thresholds; the
  false-positive near-miss above is precisely why. The 90-day window
  prevents a recurring annual event name from merging across editions.
- **Persistence prerequisite:** cache records do not currently store a
  normalized title (the event_id embeds a slugified composite, unusable for
  clean matching). Add a `norm_title` field to new/updated cache records;
  old records lacking it simply never title-match, which is acceptable
  (collisions matter for events being newly listed, and re-seen events
  refresh their record anyway).
- **Source priority on merge:** when both copies arrive in one run, keep
  the item from the richer source for display, in this order: Devpost,
  Devfolio, Cerebral Valley, Luma (Devpost/Devfolio carry prize/themes; CV
  carries a summary; Luma is thinnest).

Explicitly NOT built (stays deferred per 2.6): fuzzy or LLM-assisted
matching, host+date anchoring as a driver, any merge of
different-normalized-title listings. One observed collision does not
justify them, and the observed near-miss argues actively against.

---

## 4. The two new fetcher functions

Both live in `buildathon_radar/fetcher.py`, matching `fetch_devpost` /
`fetch_devfolio` exactly in shape: `fetch_luma()` and
`fetch_cerebralvalley()`, each returning `(items, error)` with error `None`
on success, each item conforming to the normalised contract (no `None`
except `event_start`/`event_end`; fallbacks `"Unknown"`/`""`/`[]`).

Module constants:

```python
LUMA_API_URL = "https://api.luma.com/discover/get-paginated-events"
LUMA_PLACE_BENGALURU = "discplace-G0tGUVYwl7T17Sb"
LUMA_CATEGORY_AI = "cat-ai"
CV_API_URL = "https://api.cerebralvalley.ai/v1/public/event/pull"
CV_WINDOW_DAYS = 60          # how far ahead the CV window looks
CV_PAGE_LIMIT = 100          # verified server-side cap
SOURCE_REQUEST_DELAY_S = 1   # politeness delay between paged requests
```

### `fetch_luma()`

1. GET the place feed (one request, covers the page; follow `next_cursor`
   with a 1s delay only while `has_more`, defensive).
2. GET the `cat-ai` feed the same way.
3. Merge both, dedupe by `event["api_id"]`.
4. Drop entries with `visibility != "public"` (defensive).
5. Normalise each entry:

| Contract key | Luma source |
|---|---|
| `source` | literal `"Luma"` |
| `title` | `event.name` |
| `url` | `f"https://luma.com/{event.url}"` (canonicalizer applies; dedup/guard key) |
| `summary` | name + host names + `geo_address_info.city_state`, joined, 500 cap (feed has no description; same policy as Devpost's list API) |
| `published` | `start_at` converted UTC to IST, date part; else `"Unknown"` |
| `location` | `geo_address_info.city_state`, else `geo_address_info.city`, else `"Online"` if `location_type == "online"`, else `"Unknown"` |
| `mode` | `"in-person"` if `location_type == "offline"` else `"online"` |
| `host` | `calendar.name` when present and not `"Personal"`, else first `hosts[].name`, else `"Unknown"` (Luma events are often person-hosted; the title carries the brand, which the rubric reads anyway) |
| `dates` | human string built from IST start/end, Devfolio style |
| `prize` | `""` (not available) |
| `themes` | `["AI"]` for items that came from the `cat-ai` feed, else `[]` |
| `event_start`/`event_end` | IST date parts of `start_at`/`end_at`, else `None` |

### `fetch_cerebralvalley()`

1. GET `featured=true` (one request, tiny).
2. GET `approved=true&limit=100&offset=totalCount-100` (first request also
   reveals `totalCount`; a defensive first call with `limit=1&offset=0`
   reads it cheaply), then page backward with a 1s delay until a page's
   earliest `startDateTime` is before today, capping at 6 pages as a
   runaway guard.
3. Keep upcoming-window events only: `startDateTime` date within
   [today, today + CV_WINDOW_DAYS], or already started but `endDateTime`
   still in the future.
4. Apply the structured pre-filter: keep iff featured OR `CVEvent` OR
   `type == "HACKATHON"` OR location contains "India" or "Bengaluru" OR
   location == "Remote".
5. Dedupe by `id`, merge featured over approved.
6. Normalise:

| Contract key | CV source |
|---|---|
| `source` | literal `"Cerebral Valley"` |
| `title` | `name` |
| `url` | `url` field, canonicalized (often a Luma link, which is the cross-source dedup working as designed). Items with an empty `url` are skipped with a counted warning: no stable key, no guard anchor. |
| `summary` | `descriptionSummary`, else `description`, 500 cap |
| `published` | date part of `startDateTime` (naive string, split on space), else `"Unknown"` |
| `location` | `location` as-is; `"Remote"` becomes `"Online"` |
| `mode` | `"online"` if location is Remote else `"in-person"` |
| `host` | `"Unknown"` (no organizer field; venue is a place, not a host) |
| `dates` | human string from start/end date parts |
| `prize` | `""` |
| `themes` | `["Hackathon"]` if `type == "HACKATHON"` else `[]` |
| `event_start`/`event_end` | date parts, else `None` |

### Shared plumbing changes

- `SOURCES` grows to four entries in priority order: Devpost, Devfolio,
  Cerebral Valley, Luma (priority is the §3 merge preference; iteration
  order is also merge order since the first record wins).
- The URL canonicalizer from §3 is applied in every `normalise_*` function
  (including the two existing ones, where it is a no-op for current data).
- The exact-title merge from §3 runs inside `fetch_events` where records
  are created/updated; `_new_record` gains the `norm_title` field.
- `agent.py`: one minimal system-prompt addition naming Luma and Cerebral
  Valley as sources and noting that meetups, showcases, and demo nights are
  now in scope alongside hackathons (the persona already wants "hackathons,
  buildathons, and builder showcases"; this keeps the model from
  auto-demoting non-hackathon formats). No rubric weight changes.
- `digest.py`: no changes. The source-health footer iterates
  `source_health`, so four sources appear automatically.

Volume expectation, measured: steady-state adds roughly 60 to 70 Luma items
and 10 to 30 CV items to the ~90 existing, all subject to cache
suppression after first sight. The first run is a one-time bump of roughly
150 to 190 total events into one Claude call; input cost roughly doubles
for that week, picks stay capped at 12, and LEARNINGS' extended-thinking
fix (thinking disabled) means no token-budget failure mode. Subsequent
weeks return to a trickle of newly-listed events.

---

## 5. Resilience design

- **Per-source isolation, unchanged pattern:** each new fetch function has
  its own try/except returning `([], str(e))`; `fetch_events`' outer
  per-source try/except also wraps it. A Luma outage cannot touch CV,
  Devpost, or Devfolio, and vice versa.
- **Zero-results safeguard, automatic:** both sources report through
  `source_health` like the existing two, so the digest footer shows
  `Luma: 0 new events ⚠️` or `Cerebral Valley: FAILED (...)` rather than
  silently thinning. Because both APIs are undocumented, this footer is the
  primary breakage tripwire; a structure change surfaces as FAILED (JSON
  keys missing raise inside the fetch, caught, reported) or as a sustained
  zero-events streak, visible in every Sunday email.
- **Defensive parsing:** every field access uses `.get` with the contract
  fallbacks; a malformed entry is skipped with a counted warning, not a
  crashed source (same as `normalise_devpost`'s per-item try/except).
- **Politeness:** requests are plain GETs with the project UA
  (`Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0`), `timeout=30`,
  1s delay between successive paged requests to the same host, at most ~2
  requests to Luma and ~7 to CV per weekly run. robots.txt on the queried
  hosts permits these paths (verified §1/§2); the CV site-host `/api/*`
  disallow is respected by never touching that host's API routes.
- **Fragility statement, honest:** both APIs are undocumented and can
  change or vanish without notice, the same standing Devpost has had since
  v1. Additionally, Luma's `cat-ai` feed geography is IP-inferred; if Luma
  changes that ranking, AI coverage shifts silently even while the place
  feed keeps working. Accepted tradeoff for a free, scrape-free path; the
  weekly footer is the detector, and the place feed plus CV featured are
  deterministic anchors.

---

## 6. Build plan: ordered, verifiable phases

Global rules for the executor, unchanged from house style: phases strictly
in order, each ends verification-green; commit and push per CONTRIBUTING.md
(fetcher, agent prompt, tests, and docs are all in the safe zone; nothing
in this build touches the send path, scheduler, or secrets); no live Claude
calls except the Phase 5 and 6 dry runs; live HTTP to the four source APIs
is read-only and permitted freely; all automated tests mock the network.

**Phase 0: endpoint preflight (read-only, no repo changes).**
Run the four verification curls from §1 and §2. Confirm both Luma feeds
return `entries` with the documented keys, CV `featured=true` returns
events, CV `approved=true` returns `totalCount` > 3000 with ascending
dates. If any endpoint has drifted from this document, stop and flag rather
than improvising a new mechanism mid-build.
*Verify:* all four curls return HTTP 200 JSON matching the documented
shapes. Nothing to commit.

**Phase 1: fixtures.**
Capture one live response per feed, trim to 3 or 4 representative entries
each (keep the India Builds with Claude entry if still live, a `Personal`
calendar entry, a CV featured entry, a CV entry whose `url` is a Luma
link), into `tests/fixtures/luma_place_sample.json`,
`tests/fixtures/luma_catai_sample.json`,
`tests/fixtures/cv_featured_sample.json`,
`tests/fixtures/cv_approved_sample.json`.
*Verify:* fixtures load as JSON; committed.

**Phase 2: Luma fetcher.**
Implement `normalise_luma` + `fetch_luma` per §4, plus the URL
canonicalizer helper (applied in all four normalisers). Tests: field
mapping against fixtures including host fallback chain
(calendar name, "Personal" skipped, person host, Unknown), UTC-to-IST date
conversion, online/offline mode, url construction, api_id dedupe across the
two feeds, per-item error skip, `(items, error)` failure shape with
requests mocked to raise.
*Verify:* `venv/bin/pytest` green. Commit and push.

**Phase 3: Cerebral Valley fetcher.**
Implement `normalise_cerebralvalley` + `fetch_cerebralvalley` per §4:
tail-paging with the 6-page guard, window filter, structured pre-filter,
empty-url skip, naive-datetime parsing. Tests: each pre-filter arm keeps
and drops correctly, window boundaries, tail-paging walk with mocked pages,
featured-over-approved merge, Luma-link canonicalization in `url`.
*Verify:* `venv/bin/pytest` green. Commit and push.

**Phase 4: cross-source collision handling.**
Implement §3: `norm_title` on cache records, exact-title-plus-90-day merge
in `fetch_events` (same run and against cache), source-priority item
selection, URL append to `urls`. Tests: the Build with Gemini XPRIZE
scenario reconstructed from fixtures (same title, dates 90 days apart,
different hosts) merges to one item; the AI-4-Earth vs AI-Internship
near-miss stays two items; a CV item whose url equals a Luma item's
canonicalized url collapses via url_index; legacy cache records without
`norm_title` still load and round-trip.
*Verify:* `venv/bin/pytest` green, including the whole pre-existing suite
(the resurface and migration tests must be untouched). Commit and push.

**Phase 5: wiring and live dry run.**
Add both sources to `SOURCES`; make the minimal `agent.py` prompt addition
(§4). Run `venv/bin/python main.py --dry-run` (live fetch of all four, one
live Claude call, no send, no cache write).
*Verify:* exit 0; the printed footer shows all four sources with plausible
counts (Devpost ~70, Devfolio ~20, Luma ~40-70, Cerebral Valley ~10-30);
picks look sane and include at least one Luma-sourced Bengaluru event if
one is live that week; no crash on any source. Commit and push.

**Phase 6: docs and final gate.**
Update `SPEC.md` (sources section: the two new APIs, shapes, the collision
handling), `ROADMAP.md` (v2 backlog items 1 and 2 shipped; 2.6 status
updated to "minimal exact-title handling built, full resolution still
deferred"), `CLAUDE.md` (sources line, known limitations: undocumented
APIs, IP-geo caveat), `LEARNINGS.md` (a short entry: both "no API" sources
turned out to have real public JSON endpoints found by tracing the
frontend, and the live near-miss that argues against fuzzy matching).
*Final gate:* `venv/bin/pytest` green; `venv/bin/python main.py --dry-run`
exit 0 (second and last live Claude call); footer shows four sources.
Commit and push.

**Left for the human:** nothing operational. The next scheduled Sunday run
sends the first four-source digest; expect it to be a bumper week (the
one-time cache fill) with up to the capped 12 picks.

---

## 7. Testing approach

- **Mocked:** all HTTP in the automated suite (`requests.get`/`requests.post`
  patched, or normalisers fed fixture dicts directly, matching
  `test_fetcher.py`'s existing style); the Anthropic client, always, as
  ever.
- **Real in tests:** nothing network-touching. Fixture payloads are real
  captured responses, trimmed, so field-mapping tests exercise true shapes
  (the Phase 1 fixtures serve the same role `devpost_sample.json` does).
- **Live proof:** the Phase 5 and Phase 6 `--dry-run`s are the
  dry-run-equivalent proof: real fetches from all four sources, one real
  Claude call, printed digest, zero side effects (no cache write, no email,
  no tracker.db touch). The four-source footer line is the observable
  success criterion.
- **Regression net:** the existing fetcher/cache/resurface/migration tests
  must pass unmodified through every phase; Phase 4 explicitly re-runs them
  since it touches `fetch_events` and `_new_record`.

---

## 8. Pre-run human checklist

Nothing is required. No new accounts, no keys, no paid services, no sudo,
no infra. The only steps:

1. Answer the open questions in §9 (defaults will be built otherwise).
2. Leave the Pi powered and online.

---

## 9. Open questions for the user

Each has a default; the executor builds the default unless overridden at
the top of this file.

1. **Luma geographic scope.** Default: Bengaluru place feed + the
   IP-geo-scoped `cat-ai` feed (which from the Pi is also Bengaluru-area).
   Alternative: also resolve and add place feeds for other Indian cities
   (Mumbai, Delhi, Hyderabad have discover pages whose place ids can be
   extracted the same way). Costs one request per city per week and widens
   the geography the rubric already down-scores; probably not worth it now.

2. **CV pre-filter breadth.** Default: featured OR CVEvent OR HACKATHON OR
   India OR Remote, 60-day window (measured ~10-30 events/week). This
   deliberately drops generic US/UK conference listings before Claude sees
   them. Alternative: loosen (send the whole window, ~300 first week,
   higher token cost, more radar-tier noise) or tighten (featured +
   CVEvent + India only, risks missing an unfeatured global hackathon).

3. **First-week flood handling.** Default: accept one bumper digest (the
   cache absorbs everything after week one; picks are already capped at
   12). Alternative: stage the rollout, Luma one week, CV the next, at the
   cost of an extra deploy step. The 2x one-week Claude token cost is a few
   cents.

4. **The prompt tweak scope.** Default: one added sentence in the system
   prompt naming the new sources and legitimizing meetup/showcase formats,
   no rubric weight changes. Alternative: also add a small scoring note
   that CV-featured events carry curation signal (could feed the
   scale-and-signal component). Default keeps the rubric untouched on the
   theory that title/host already carry the signal.
