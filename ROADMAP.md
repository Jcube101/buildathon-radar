# ROADMAP.md: buildathon-radar

Forward-looking roadmap: what v1 shipped, the resolved architecture decisions
behind it, and what comes next. For the original overnight build plan (phase
by phase execution, endpoint reconnaissance, systemd unit specification),
see `docs/BUILD-HISTORY.md`. For the current architecture and data contracts,
see `SPEC.md`.

---

## Status: what shipped in v1

- [x] `venv/` with `anthropic`, `requests`, `python-dotenv`, `markdown`, `pytest`, all import-verified.
- [x] `fetcher.py`: Devpost (2 pages, themes filter, best-effort date parse) and
      Devfolio (both `application_open` and `upcoming` types, merged and
      deduped by uuid) fetchers, normalising into the item contract.
- [x] `cache.json` dedup, composite `event_id` records (host + normalized title
      + start date), date-aware resurface logic (suppress until near the
      event's own start date, resurface once, stop after the event lapses;
      falls back to a fixed 45-day TTL when no date is known), migrated
      cleanly from the original flat `{url: date}` cache with no data loss.
- [x] `agent.py`: `claude-sonnet-5` call, extended thinking explicitly
      disabled (see `LEARNINGS.md` for why), system prompt with persona, hard
      exclusions (student/college-run events, India-inaccessible platforms,
      hardware/chip-level AI events), a four-component scoring rubric, tiering
      and output contract, and critical constraints. Strict JSON output, parse
      ladder plus one retry, defensive pick validation, empty-input short
      circuit.
- [x] `guard.py`: exact plus trailing-slash-tolerant URL validation against the
      fetched item set, drop-and-continue on a miss.
- [x] `digest.py`: tier-sectioned markdown for the plain-text part, plus a
      Gmail-Android-safe, table-based, teal-themed HTML digest (fluid width,
      word-break on text cells, explicit cell backgrounds, no external
      assets). Quiet-week and all-failed bodies, always-present source health
      footer, integrity line when picks are dropped.
- [x] `deliver.py`: local archive, Gmail SMTP send, `send_failure_email` for
      the always-send invariant on a crash.
- [x] `main.py`: four-stage orchestration, `--dry-run` flag, top-level fatal
      handler that attempts a failure email before a non-zero exit.
- [x] Full pytest suite, Claude client always mocked, no live calls in tests.
- [x] `systemd` `buildathon-radar.service` and `.timer` installed via
      `systemctl --user` (no sudo), enabled, running every Sunday 17:00 IST.
- [x] Doc set: `README.md`, `SPEC.md`, `ROADMAP.md` (this file), `LEARNINGS.md`,
      `CLAUDE.md`, `CONTRIBUTING.md`, plus `docs/` for archived and reference
      material.
- [x] Live proof-of-life email sent and confirmed on a real phone (Gmail
      Android rendering verified after the mobile-wrapping fix).

## Status: what shipped in v2 Units A and B (tracker, Track/Applied, participation log)

- [x] `tracker_store.py`: SQLite `tracker.db` (WAL mode), `events` + `action_log`
      tables, keyed on the same composite `event_id` as `cache.json`. State
      machine `seen -> tracked -> applied` (only moves upward, never
      downgrades); `over` state and `outcome`/`over_at` columns present but
      unused, reserved for Section 2.4 with no migration needed later.
      HMAC-signed action tokens (`sign_action`/`verify_action`).
- [x] `tracker_service.py`: FastAPI app, `GET /`, `/track`, `/applied`, every
      action signature-verified before touching the store; unknown event_id,
      invalid token, and repeat/out-of-order clicks all handled gracefully
      (404, 403, idempotent 200 respectively), never an error or a downgrade.
- [x] `GET /list`: a read-only view of every row in the tracker store,
      grouped by state (Tracked, Applied, Seen, Over), so the owner can see
      current tracker state without waiting for Sunday's digest. No signed
      token (it never writes), same unauthenticated posture as the health
      page; reuses the same WAL-mode `connect()` path every other route
      uses. Verified live over the real tunnel.
- [x] `fetcher.py`: every returned item now carries `event_id`, matching the
      cache key, so a Claude pick's guard-matched item ties back to the same
      tracker row.
- [x] `digest.py`: Track (filled) / Applied (outlined) bulletproof buttons on
      every HTML card, a "Tracked" reminder strip (omitted when empty), and
      an always-visible participation log with a one-line empty state. The
      plain-text digest is unchanged.
- [x] `main.py`: non-dry runs upsert validated picks into the tracker store
      and read tracked/applied rows for the digest; wrapped in its own
      try/except so a broken tracker store never blocks the Sunday send.
- [x] `buildathon-tracker.service`: `systemctl --user` unit (`Type=simple`,
      no sudo), running continuously alongside the digest's oneshot timer.
- [x] Exposed at `https://radar.job-joseph.com` via the existing `pi-home`
      Cloudflare Tunnel; verified end-to-end (local and public) with signed
      test clicks against throwaway rows.
- [x] Full pytest coverage for the store, the service, event_id passthrough,
      and the new digest sections; existing suites unaffected.

Sections 2.4 (lifecycle/outcomes), 2.5 (calendar), and 2.6 (entity
resolution) remain deferred, not built; see Section 2 below and
`docs/V2-TRACKER-PLAN.md` for the full architecture this was built from.

## Status: what shipped in the v2 sourcing expansion (Luma and Cerebral Valley)

Built 2026-07-15 from `docs/V2-SOURCING-PLAN.md` (the full recon and build
plan, including verified endpoint details, live example payloads, and the
entity-resolution assessment).

- [x] `fetch_luma()` / `normalise_luma()`: the undocumented public
      `api.luma.com` discover API, Bengaluru place feed only (the
      IP-personalised `cat-ai` category feed was evaluated and deliberately
      not used, see Known limitations). Host derivation falls back from a
      "Personal" calendar to the first listed human host. **Live in
      `SOURCES` now.**
- [x] `fetch_cerebralvalley()` / `normalise_cerebralvalley()`: the
      undocumented public `api.cerebralvalley.ai` pull endpoint, found by
      tracing the site's own JS bundles. No server-side date filter exists,
      so this pages backward from the tail of the ~3900-event ledger and
      applies a structured pre-filter (featured, CVEvent, HACKATHON, India,
      Remote) to cut the ~300-event upcoming window to a relevant handful.
      **Built, fully tested, deliberately NOT active.**
- [x] **Staged activation decision:** `fetcher.ENABLE_CV_SOURCE` defaults to
      `False`. Luma alone went live this run so its real weekly behaviour
      (event volume, relevance, any API drift) can be observed
      independently before a second new source is layered on top of it.
      Flip `ENABLE_CV_SOURCE` to `True` in `fetcher.py` about a week after
      this shipped (around 2026-07-22) to activate Cerebral Valley; no
      other change is needed, since it is already wired into `SOURCES`,
      the collision handling, and the agent prompt.
- [x] Minimal cross-source collision handling (ROADMAP.md 2.6, scoped
      narrowly): URL canonicalization (`lu.ma` folds into `luma.com`) so a
      Cerebral Valley listing that links out to Luma collapses with that
      same event via the existing URL-index dedup, plus an exact
      normalized-title match within a 90 day window for cases the URL
      index can't catch. **Deliberately exact-match only, no fuzzy or
      LLM-assisted scoring:** live recon on 2026-07-15 found a real
      duplicate this catches ("Build with Gemini XPRIZE" on both Devpost
      and Cerebral Valley, recorded dates exactly 90 days apart) and,
      separately, a real near-miss (two differently named hackathons
      sharing two-thirds of their normalized words on the same date) that
      fuzzy matching would have wrongly merged. That observed false
      positive is the reason fuzzy/LLM-assisted matching stays off the
      table; full entity resolution (2.6's options B and C) remains
      deferred.
- [x] `agent.py`: system prompt now names Luma and Cerebral Valley as
      sources, tells the model not to auto-demote a meetup or community
      showcase just because it isn't titled "hackathon," and credits a
      `"Cerebral Valley Featured"` theme tag as a modest signal inside the
      existing host prestige component (not a new scoring axis).
- [x] Live dry run proof: "India Builds with Claude - Razorpay | Anthropic
      | Peak XV", the exact event that motivated this whole project,
      appeared as a Luma-sourced `must_see` pick (score 82) alongside
      several other real Bengaluru Luma events, all scored correctly by
      geography and host. Source-health footer showed exactly three
      sources (Devpost, Devfolio, Luma); Cerebral Valley did not appear,
      confirming the gate holds.
- [x] Full pytest coverage for both fetchers, the pre-filter, the
      canonicalizer, and the collision handling; existing suites
      unaffected.

## v1 non-goals (still out of scope)

No other social sources (Twitter, LinkedIn), no scraping, no Apify, no
Google Sheets, no WhatsApp, no web UI, no database beyond `cache.json` and
`tracker.db`. (Luma and Cerebral Valley, listed here in earlier versions of
this file, shipped as the sourcing expansion above.)

## v2 backlog

1. Flip `ENABLE_CV_SOURCE` to activate Cerebral Valley, once Luma's first
   live week has been observed (see the sourcing status above).
2. Unstop as a third API source, if college-tier coverage becomes wanted.
3. Deadline-reminder mode (a second mention as a cached event's close date nears).
4. Per-event calendar (.ics) attachments.
5. The remainder of the tracker vision below (Section 2): lifecycle states
   and outcomes (2.4), calendar integration (2.5), and full cross-source
   entity resolution beyond the minimal exact-title fix shipped above
   (2.6). Sections 2.2 and 2.3 shipped; see the status above.
6. Luma's IP-geo-scoped `cat-ai` category feed and place feeds for other
   Indian cities, evaluated but not built; see `docs/V2-SOURCING-PLAN.md`.

---

## 0. Resolved architecture decisions

- **Quiet-week emails:** yes, sent every Sunday even when nothing clears the
  bar, so inbox silence always means the pipeline is broken, not that there
  was nothing to report.
- **Cache TTL:** 45 days for date-less events; date-aware resurface logic
  (Section "Status" above) supersedes the original fixed-TTL-only design.
- **Global online events:** included, ranked into the lower tier by
  geography, but a prestigious online event can still reach `must_see` on
  theme fit and host prestige alone. The owner has personally won a notable
  online buildathon (Lovable x Granola) and did not want that category
  buried.
- **Timer:** enabled live during the build; the next auto-send is always the
  coming Sunday 17:00 IST.
- **College hackathons:** the rubric now hard-excludes student and
  college-run events entirely (tuned after the first real digest showed them
  cluttering the picks), rather than only demoting them.

## 1. Mission

The owner is an AI product manager in Bengaluru who repeatedly missed AI
hackathons, buildathons, and showcases because discovery was luck-driven (a
stray tweet, a mentor's link). Two concrete misses motivated this project:
the Google DeepMind Bangalore Hackathon (Gemini on-device, found on Twitter
too late, was listed on Cerebral Valley) and India Builds with Claude,
Razorpay x Anthropic (a Claude builders showcase, surfaced only by a mentor,
was listed on Luma).

buildathon-radar scans event sources weekly, filters for genuine relevance
(AI/agents/Claude/Gemini themes, Bengaluru/India geography, prestigious
hosts), and emails a ranked digest every Sunday 5:00 PM IST so these events
arrive by system, not by luck.

---

## 2. v2 tracker vision (product direction, documentation of intent, not a build instruction)

This section records where the project should grow after v1, written before any of it was built. 2.2 and 2.3 have since shipped largely as described here (see the Status section above); 2.4, 2.5, and 2.6 remain deferred, and nothing there should be built without being explicitly scoped.

### 2.1 The evolution: one-way notifier to two-way tracker

v1 is a one-way system: it watches sources and reports events. It has no memory of what the owner actually did about any of them. v2's central idea is to close that loop: the owner acts on an event (tracks it, applies to it), and buildathon-radar holds state about that action so future digests, a participation log, and eventually a small dashboard can all reflect what is actually happening, not just what exists to be found. The cache restructure already done (composite `event_id`, `urls` as an array, `event_start`/`event_end` on every record) is deliberately shaped so this later state can hang off the same per-event record without another migration.

### 2.2 Per-event actions: Track and Applied

**Shipped, see Status above.** The design intent below is kept as written
for context; the actual routes and store shape are documented in `SPEC.md`.

Two buttons on every event card in the email:

- **Track**: bring this event back into next week's digest as a standing reminder, independent of the date-aware resurface logic. A tracked event is something the owner has flagged as worth watching, not something the system decided to resurface on its own.
- **Applied**: log that the owner has registered for this event. This is the seed of the participation log (2.3) and the lifecycle state (2.4).

The hard technical constraint, stated plainly so a future session does not try to fight it: **email is static HTML**. There is no way for a button inside an email to write state back to any store by itself; an `<a>` tag can only navigate somewhere. So a "Track" or "Applied" button is a link to an HTTP endpoint that performs the action and returns a small confirmation page, not a form submission handled in-place.

This means buildathon-radar has to grow a small web service to receive those clicks. The natural shape, matching infrastructure already run on the same Pi for other personal tools:

- A small FastAPI app, run as its own systemd user service alongside `buildathon-radar.service` (the weekly digest job stays a `Type=oneshot` timer-triggered script; this would be a separate long-running `Type=simple` service).
- Exposed to the internet via Cloudflare Tunnel, the same pattern already used for other personal tools (PhotoRank, Vane), so there is no new infrastructure concept to learn, just another tunnel and another subdomain. Candidate subdomain: `radar.job-joseph.com`.
- Routes along the lines of `GET /track?event_id=...` and `GET /applied?event_id=...` (GET, not POST, since the only client is a clicked email link, not a form), each looking up the event_id in the tracker store, updating its state, and rendering a minimal HTML confirmation page ("Tracked: Build with Gemma" or similar). No auth needed if the event_id space is large and unguessable enough to not be worth securing further for a personal tool, though this should be revisited if the service ever does anything more sensitive than logging a click.
- The tracker store itself could start as simply an extension of `cache.json` (each record already has an `event_id` to key off of) or a small separate JSON/SQLite store keyed the same way. Given the lifecycle fields in 2.4, a slightly richer store than a flat JSON file may be worth it once this is actually scoped, but that decision belongs to whichever session builds this.

### 2.3 The participation log

**Shipped, see Status above.** The design intent below is kept as written
for context; the actual rendering is documented in `SPEC.md`.

A new section at the bottom of the weekly digest, a small table listing every event marked Applied, not yet resolved to Over. Columns: event title (linked), registration or start date, submission or end date. This is purely a rendered view over the tracker store's state, the same "code renders from data, Claude touches none of it" principle that governs the rest of the digest. As events move to Over (2.4), they drop out of this table (or move to a separate small history section, a detail for the future build to decide).

### 2.4 Lifecycle states

Every event engaged with moves through a small state machine, richer than the cache's own internal `seen` / `resurfaced` / `lapsed` housekeeping states, which are about suppression, not participation:

```
seen -> tracked -> applied -> over
```

- `seen`: the default. buildathon-radar found it, no action taken.
- `tracked`: Track was clicked. It will keep reappearing in the digest as a reminder until it resolves further or its dates pass.
- `applied`: Applied was clicked. It now shows up in the participation log (2.3).
- `over`: the event's own end date has passed. An event reaching `over` needs one more piece of input that nothing in v1 or the FastAPI layer alone can infer: an outcome. The three outcomes to record: did not participate, participated, participated and won. This is effectively a small per-event record that could eventually be managed from a dashboard (not scoped, not designed, just named here as the natural next surface once the state exists to show).

### 2.5 Calendar integration

Once a tracked or applied event has a reliable `event_start` (already populated by the cache restructure), adding it to the owner's calendar as a real calendar event is a small, clean addition, not a new pattern: a calendar-event-creation pattern already exists elsewhere in the owner's stack, so this would reuse that rather than inventing a new integration. Natural trigger points: automatically on Track or Applied, or as a third button/link. Left for the future session to decide against whatever the existing calendar pattern's constraints turn out to be.

### 2.6 Cross-source entity resolution: the key v2 data problem

This is the hardest and most important data problem in the whole v2 vision, worth documenting carefully rather than glossing over.

Once Cerebral Valley and Luma (the v2 backlog above) are added as sources, the same real-world event will sometimes appear on more than one platform, under different URLs and, critically, under different title text. The concrete motivating example, drawn from real data already seen this season: **"Agentic Commerce Hackathon (Build agents that act, shop, book, renew and pay.)" on Devfolio** and a plausible **"Agentic Commerce Hackathon" listing on Luma** are the same event and must resolve to the same `event_id`, not two separate cache records that both get surfaced, scored, and shown as if they were different hackathons.

This does not meaningfully occur in v1. Devpost and Devfolio rarely list the same event (they serve different audiences, global versus India-focused), so the composite `event_id` derivation (normalized host plus normalized title plus start date) has never yet had to resolve a genuine cross-source collision. That is exactly why real resolution logic is deferred rather than built now: designing it against a hypothetical is guesswork, and the risk of getting it wrong (either merging two genuinely different events, or failing to merge the same event twice) is high enough that it deserves real dual-source data to test against, not invented test cases.

Candidate approaches to evaluate when that data exists, in rough order of complexity:

- **(A) Hard normalization before hashing.** Extend the existing normalization approach (already in `fetcher.py`) more aggressively: stronger punctuation and filler-word stripping, maybe stemming, before combining with host and date into the composite id. Cheapest to build (no new infrastructure), but risks false collisions: two different hackathons with very similar generic names ("AI Hackathon 2026") and the same rough date could collide even though they are unrelated events.
- **(B) Host plus date as the anchor, title as secondary confirmation.** Treat host and start date as the primary matching key (since a specific hackathon on a specific date run by a specific organiser is a strong signal on its own), and only use title similarity to confirm or reject a candidate match rather than to drive it. Reduces the false-collision risk of (A) somewhat, at the cost of needing a two-step matching process instead of one hash.
- **(C) Fuzzy-match or LLM-assisted "are these the same event" comparison.** For candidate pairs that share a host and a nearby date but whose titles do not obviously match, ask an LLM (or use a string-similarity library) directly: are these the same event? Most flexible and most likely to get genuinely ambiguous cases right, but adds real cost (an extra call per candidate pair, at minimum) and a threshold to tune (how confident is confident enough to merge), and introduces exactly the kind of unverified-inference risk the anti-hallucination guard elsewhere in this project was built to avoid, so any LLM-assisted resolution step would need its own guard: a merge decision should probably require corroborating structured signal (matching host, dates within some window), not title similarity alone.

The tradeoff across all three is the same shape: normalization alone risks false collisions, fuzzy or LLM-assisted matching adds cost and tuning and its own failure modes. The right choice should be made by looking at real observed collisions once v2 sources are live, not by picking one now on priors. The v1 cache is already structured to make whichever approach is chosen a drop-in change rather than another migration: `event_id` is already a composite (not a bare URL), and `urls` is already an array precisely so a second source's URL for the same event can be appended to an existing record rather than forcing a new one.

This is recorded as "evaluate whether this is worth building at all" when the time comes, not as a queued feature with an assumed yes.

**Update, 2026-07-15:** the hypothetical above stopped being hypothetical the moment Luma and Cerebral Valley were added. Live recon that day found exactly one real duplicate ("Build with Gemini XPRIZE" on Devpost and Cerebral Valley) and, in the same scan, one real fuzzy near-miss (two differently named hackathons sharing two-thirds of their words on the same date) that a similarity-based matcher would have wrongly merged. That single data point was enough to justify a small slice of option (A), URL canonicalization plus an exact normalized-title match within a 90 day window, and enough to rule out option (C) outright: the near-miss is direct evidence that fuzzy or LLM-assisted matching would actively cause harm here, not just cost more. Options (B) and full (C) remain deferred exactly as this section originally described; see `docs/V2-SOURCING-PLAN.md` section 3 and `SPEC.md`'s Cache and dedup section for what was actually built.
