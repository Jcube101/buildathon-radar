# ROADMAP.md: buildathon-radar

> Execution roadmap for an overnight, unattended build by Claude Sonnet 5.
> Written 2026-07-13 after live endpoint reconnaissance from the target machine (jobpi, Raspberry Pi 5, Debian 13).
> Every endpoint, parameter, and payload shape in this document was verified live on 2026-07-13. Nothing here is assumed.
>
> Executor: follow the phases in Section 10 in order. Each phase has a concrete verification step. Do not skip verifications. Do not build anything listed in Section 12 (non-goals). If something in this roadmap conflicts with reality at build time, prefer reality, note the deviation in `learnings.md`, and keep going. Never stop to ask a question; every known decision is resolved here.

---

## 0. Resolved Answers (authoritative — override any conflicting default below)

These five questions were raised during architecture and resolved by Job on 2026-07-13. Where these conflict with any default described later in this roadmap, THESE WIN.

1. **Quiet-week emails:** Yes. Send a short "nothing this week" email even on empty weeks. Inbox silence must always mean the pipeline is broken, never that there was simply nothing to report.

2. **Cache TTL (announce-once):** Keep the 45-day TTL with a single resurface if an event is still open. No change.

3. **Global online events:** Include them. They rank in the lower "radar" tier by default via the geography penalty, BUT a prestigious global online event (e.g. an Anthropic- or DeepMind-run online hackathon, or a notable sponsor-backed online buildathon) must be able to rank ABOVE the radar tier on theme fit and host prestige alone. The geography penalty must not bury a high-prestige online event. Rationale: Job won a notable online buildathon (Lovable x Granola) and does not want that category skipped.

4. **Timer enabled during build:** Yes. Enable the `systemctl --user` Sunday 5:00 PM IST timer as part of the build. The next auto-send is next Sunday. The build must NOT send any real email tonight; the user takes a separate one-off manual live run in the morning as proof-of-life.

5. **College hackathons:** Trust the rubric to demote them via scale and prestige weighting. Do NOT hard-exclude. A Bengaluru college-hosted AI event with a real theme can legitimately reach "worth a look". Revisit only if real digests prove cluttered.

---

## 1. Mission

Job is an AI PM in Bengaluru who repeatedly misses AI hackathons, buildathons, and showcases because discovery is luck-driven (a stray tweet, a mentor's link). Two concrete misses motivated this project:

1. **Google DeepMind Bangalore Hackathon** (Gemini on-device, Bengaluru, July 2026): found on Twitter too late. Was listed on Cerebral Valley.
2. **India Builds with Claude, Razorpay x Anthropic** (Claude builders showcase, Bengaluru, Anthropic India MD present): surfaced by a mentor. Was listed on Luma.

buildathon-radar scans event sources weekly, filters for genuine relevance to Job's profile (AI/agents/Claude/Gemini themes, Bengaluru/India geography, prestigious hosts), and emails a ranked digest every **Sunday 5:00 PM IST** so these events arrive by system, not by luck.

The build ports the proven spine of the sibling project signal-digest (documented in `AGENT-PATTERN.md` in this repo root): normalised item dicts, a single Claude reasoning call, `cache.json` dedup, markdown-to-HTML email over Gmail SMTP, `--dry-run` gating, and a systemd user timer.

---

## 2. Architecture overview

```
systemd timer (Sun 17:00 IST)
        |
        v
main.py ──> fetcher.py ──────> agent.py ──────> guard.py ──> digest.py ──> deliver.py
            Devpost API        claude-sonnet-5   URL           markdown     HTML render
            Devfolio API       scores + picks    validation    assembly     archive/
            normalise          as strict JSON    vs input      (code-owned) Gmail SMTP
            cache.json dedup                     URL set
```

Key structural difference from signal-digest: there, Claude authors the entire digest body as free markdown and no code checks it. Here, **Claude only selects, scores, and explains**; it returns strict JSON keyed by URL. Code then re-joins each pick to its original source item and renders the digest from **source data**, with Claude contributing only the score, tier, and "why it matters" line. This makes the anti-hallucination guard a mechanical set-membership check and makes it impossible for the model to fabricate a venue, date, or host in the final email.

### Module map

| Module | Origin | Notes |
|---|---|---|
| `main.py` | **Port as-is** from AGENT-PATTERN.md §1 | Rename imports and banner text; add source-health plumbing and the always-send failure email (Section 9) |
| `buildathon_radar/__init__.py` | **Port as-is** | Empty package marker |
| `buildathon_radar/fetcher.py` | **Build new** (the designated swap layer) | Two HTTP JSON sources replace feedparser; reuse cache helpers, per-source try/except pattern, and dry-run gating verbatim from AGENT-PATTERN.md §4 and §5 |
| `buildathon_radar/agent.py` | **Port structure, rebuild prompt** | Client init and call shape port; persona, rubric, and JSON output contract are new; model is `claude-sonnet-5` |
| `buildathon_radar/guard.py` | **Build new** | The programmatic anti-hallucination check that signal-digest lacks (its absence caused a documented hallucination incident there) |
| `buildathon_radar/digest.py` | **Build new** | Renders validated picks + source health into markdown; in signal-digest this job was done by the model |
| `buildathon_radar/deliver.py` | **Port as-is, retheme** | `markdown_to_html`, `save_to_archive`, `send_digest` port verbatim from AGENT-PATTERN.md §6 and §7; change heading, subject, accent colour |
| `scheduler/systemd/*` | **Port, edit paths and calendar** | Full unit files in Section 11 |
| Doc set (5 files) | **Port convention** | AGENT-PATTERN.md §10 |
| `tests/` | **Build new** | pytest, Claude call always mocked (Section 10, Phase rules) |

### Project layout (target state)

```
buildathon-radar/
├── buildathon_radar/
│   ├── __init__.py
│   ├── fetcher.py        # Devpost + Devfolio fetch, normalise, cache dedup
│   ├── agent.py          # claude-sonnet-5 call, rubric prompt, JSON parse
│   ├── guard.py          # programmatic URL validation
│   ├── digest.py         # markdown assembly from validated picks
│   └── deliver.py        # markdown -> HTML, archive, Gmail SMTP
├── tests/
│   ├── fixtures/         # trimmed real API payloads captured in Phase 1
│   └── test_*.py
├── scheduler/systemd/
│   ├── buildathon-radar.service
│   ├── buildathon-radar.timer
│   └── README.md
├── archive/              # gitignored, created at runtime
├── main.py
├── requirements.txt
├── .env / .env.example   # already present, see Section 13
├── cache.json            # gitignored, created on first non-dry run
├── AGENT-PATTERN.md      # reference blueprint (leave untouched)
├── ROADMAP.md            # this file (leave untouched)
├── README.md, spec.md, roadmap.md, learnings.md, CLAUDE.md   # Phase 8
└── .gitignore            # exists; Phase 0 appends entries
```

---

## 3. Sourcing layer (verified live, 2026-07-13)

Both v1 sources are free, public, unauthenticated JSON APIs. No scraping, no Apify, no keys. Use the `requests` library, `timeout=30`, and send a browser-like User-Agent on every call (both APIs answered a plain custom UA fine during recon, but a browser-like UA is cheap insurance):

```
User-Agent: Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0
Accept: application/json
```

### 3.1 Source 1: Devpost (primary, global)

**Endpoint:** `GET https://devpost.com/api/hackathons`

**Verified query parameters** (all confirmed working):

| Param | Verified behaviour |
|---|---|
| `status[]` | Repeatable. `open` and `upcoming` both work. `status[]=upcoming&status[]=open` returns the union. |
| `themes[]` | Repeatable. Exact theme name, URL-encoded. `themes[]=Machine Learning/AI` (encode as `Machine%20Learning%2FAI`) returned 69 open+upcoming events on 2026-07-13. |
| `challenge_type[]` | `in-person` and `online` work. AI + open/upcoming + in-person alone returned 65 events; combined with `search=bangalore` returned 0 (no Bengaluru in-person AI events listed that day, which is exactly the gap the v2 sources will close). |
| `search` | Free-text. `search=india&status[]=upcoming&status[]=open` returned 10 events including several India college hackathons. |
| `page` | 1-based. Page 2 verified returning the next slice with identical `meta.total_count`. |
| `per_page` | **Caps at 40.** Requesting `per_page=50` returns `meta.per_page = 40` with 40 items. Default is 9. |

**Response shape** (verified):

```json
{
  "hackathons": [ { ...21 fields per item... } ],
  "meta": { "total_count": 69, "per_page": 40, "fuzzy": false }
}
```

**Real example item** (captured live 2026-07-13, trimmed sponsor noise only):

```json
{
  "id": 29541,
  "title": "Build with Gemini XPRIZE",
  "displayed_location": { "icon": "globe", "location": "Online" },
  "open_state": "open",
  "thumbnail_url": "//d112y698adiu2z.cloudfront.net/photos/production/challenge_thumbnails/004/686/462/datas/medium_square.png",
  "url": "https://xprize.devpost.com/",
  "time_left_to_submission": "about 1 month left",
  "submission_period_dates": "May 19 - Aug 17, 2026",
  "themes": [ { "id": 6, "name": "Machine Learning/AI" }, { "id": 19, "name": "Education" } ],
  "prize_amount": "$<span data-currency-value>2,000,000</span>",
  "prizes_counts": { "cash": 11, "other": 0 },
  "registrations_count": 19146,
  "featured": false,
  "organization_name": "XPRIZE",
  "winners_announced": false,
  "invite_only": false,
  "managed_by_devpost_badge": true
}
```

**Critical facts the executor must code around:**

- The list API has **no ISO dates**. `submission_period_dates` is a human string like `"May 19 - Aug 17, 2026"` or `"Jul 18 - 19, 2026"`. Parse best-effort (algorithm below); on failure set `published = "Unknown"` and keep the raw string in `dates`. Freshness does not depend on this parse because the `status[]` filter already restricts to open/upcoming events.
- `prize_amount` contains literal HTML (`$<span data-currency-value>2,000,000</span>`). Strip tags with `re.sub(r"<[^>]+>", "", s)`.
- `displayed_location.location` can be vague (`"Auditorium"`, `"KIT main building"`). Pass through as-is; the Claude rubric treats unresolvable locations as low geo score.
- `url` (e.g. `https://xprize.devpost.com/`) is stable and unique: it is the dedup key and the guard key.
- `organization_name` is present but sometimes empty; fall back to `"Unknown"`.

**Fetch plan (exactly two requests per run):**

```
GET https://devpost.com/api/hackathons?status[]=upcoming&status[]=open&themes[]=Machine Learning/AI&per_page=40&page=1
GET  same, page=2
```

69 matching events existed at recon time, so two pages of 40 cover the full set with headroom. Stop early if a page returns fewer than 40 items or is empty. Do not fetch page 3+ in v1 (if `total_count > 80`, log a warning so it shows in the journal; do not add pages).

**Devpost date-parse algorithm** for `published` (start date):

1. Split `submission_period_dates` on `" - "`.
2. The last segment carries the year (`"Aug 17, 2026"`). Extract the year with a regex (`(\d{4})$`).
3. If the first segment lacks a year, append the extracted year (`"May 19" -> "May 19, 2026"`).
4. Parse with `datetime.strptime(s, "%b %d, %Y")`.
5. Any exception at any step: `published = "Unknown"`.

### 3.2 Source 2: Devfolio (India-focused)

Devfolio was chosen over Unstop (comparison in Section 3.3). It is where Indian developer hackathons live, and recon proved the point: the very first result was **"Build with Gemma: Bengaluru AI Sprint"**, an in-person Bengaluru AI hackathon at Ramaiah Institute of Technology. That is precisely the class of event this agent exists to catch.

**Endpoint:** `POST https://api.devfolio.co/api/search/hackathons`
**Headers:** `Content-Type: application/json` (plus the standard UA above). No auth.

**Verified request bodies:**

```json
{"type": "application_open", "from": 0, "size": 50}
{"type": "upcoming",         "from": 0, "size": 50}
```

| Body field | Verified behaviour |
|---|---|
| `type` | `application_open` returned 19 hackathons; `upcoming` returned 2 (registration not yet open). Fetch **both** and merge. |
| `from` / `size` | Elasticsearch-style offset pagination. `size=50` accepted and returned all 19 in one page. Volume is small; one request per type suffices. |
| `q` | **Do not use.** Accepted but `{"q": "ai"}` returned 0 hits (appears to match differently than the site's own search). Fetch everything and let the Claude filter do theme selection; total volume is ~21 items. |

**Response shape** (Elasticsearch envelope, verified):

```json
{
  "hits": {
    "total": { "value": 19 },
    "hits": [ { "_source": { ...40 fields... } } ]
  }
}
```

**Real example `_source`** (captured live 2026-07-13, trimmed to the fields we consume):

```json
{
  "name": "Build with Gemma",
  "slug": "build-with-gemma-bengaluru-ai-sprint",
  "tagline": "Bengaluru AI Sprint",
  "desc": "Build with Gemma : Bengaluru AI Sprint is a one-day, in-person hackathon organized by Heapify Global Community in collaboration with the IEEE Computational Intelligence Society (IEEE CIS) Bangalore ...",
  "starts_at": "2026-07-18T03:30:00+00:00",
  "ends_at": "2026-07-18T15:00:00+00:00",
  "city": "Bengaluru",
  "country": "India",
  "location": "Ramaiah Institute of Technology, MSRIT Post, M S R Nagar, Mathikere, Bengaluru, Karnataka, India",
  "is_online": false,
  "apply_mode": "both",
  "status": "publish",
  "type": "HACKATHON",
  "uuid": "9ca9be8320484be0840ad2f4771bc4f9",
  "themes": [ { "name": "FinTech", "verified": true }, { "name": "AI/ML", "verified": true } ],
  "prizes": [ { "name": "Overall Prize Money" }, { "name": "Runner Up" } ],
  "hackathon_setting": { "reg_starts_at": "2026-07-03T04:30:00+00:00", "reg_ends_at": "2026-07-15T18:30:00+00:00" },
  "hosted_by": null,
  "sponsor_tiers": [ { "sponsors": [ { "name": "IEEE Computer Society" }, { "name": "Kaggle" } ] } ]
}
```

Full `_source` key list observed (for reference): `apply_mode, city, country, cover_img, desc, devfolio_official, discover, ends_at, featured, hackathon_faqs, hackathon_setting, hashtags, hosted_by, is_online, judges, location, name, participants_count, participants_details, private, prizes, projects_submitted, rating, slug, sponsor_tiers, starts_at, state, status, tagline, team_min, team_size, themed, themes, timezone, type, user_hackathon, user_hackathon_reminder, uuid, verified`.

**Critical facts the executor must code around:**

- **Event URL is constructed, not returned:** `https://{slug}.devfolio.co/`. Verified live: `https://build-with-gemma-bengaluru-ai-sprint.devfolio.co/` answers HTTP 200. This constructed URL is the item's `url`, dedup key, and guard key.
- Dates are proper ISO 8601 UTC strings. Convert `starts_at` to IST (`+05:30`) before taking the date for `published`, otherwise late-evening IST events land on the wrong day.
- `city`, `country`, `location`, `hosted_by`, `desc`, `tagline` are all nullable. Guard every access with `or` fallbacks.
- Host derivation order: `hosted_by`, else first sentence of `desc` often names the organiser but do not parse it, just fall back to the first sponsor name in `sponsor_tiers[0].sponsors[0].name`, else `"Unknown"`.
- Merge the two `type` fetches and dedupe by `uuid` before normalising (an event could appear in both).

### 3.3 Considered and rejected for v1: Unstop

Verified working, documented for the record and as a v2 option:

`GET https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&per_page=10&oppstatus=open&searchTerm=ai` returns HTTP 200, no auth, a Laravel-paginated envelope (`data.current_page`, `data.data[]`, `data.next_page_url`, `data.total`) whose items carry `title`, `seo_url` (absolute event URL), `end_date` (ISO with +05:30 offset), `region` (`"offline"`/`"online"`), `organisation.name`, `prizes`, `filters` (eligibility tags).

Rejected for v1 because the result set is dominated by college/student-eligibility events (recon page 1 was almost entirely engineering-college hackathons), the payloads are 10x heavier, and Devfolio already covers the India quality tier with richer structured fields (ISO dates, city, themes). Adding Unstop would mostly add noise for the Claude filter to reject at token cost.

---

## 4. The normalised item contract

Every source maps into this dict. The first five keys are **identical in name and meaning** to signal-digest's contract so the ported prompt-serialisation and cache code keep working; six event-specific keys are added. Downstream modules (`agent`, `guard`, `digest`) read only this shape and never see raw API payloads.

```python
{
    "source":    "Devpost",                  # "Devpost" | "Devfolio"
    "title":     "Build with Gemini XPRIZE", # event name
    "url":       "https://xprize.devpost.com/",  # canonical link; dedup key; guard key
    "summary":   "...",                      # plain text, trimmed to 500 chars
    "published": "2026-05-19",               # event start date "YYYY-MM-DD", or "Unknown"
    "location":  "Bengaluru, India",         # human location string, or "Online"
    "mode":      "in-person",                # "in-person" | "online" | "unknown"
    "host":      "XPRIZE",                   # organiser, or "Unknown"
    "dates":     "May 19 - Aug 17, 2026",    # human-readable window, or ""
    "prize":     "$2,000,000",               # plain text, tags stripped, or ""
    "themes":    ["Machine Learning/AI"],    # list of theme name strings, may be []
}
```

Normalisation rules: every value is a `str` (except `themes`, a `list[str]`); never `None`; missing data becomes `"Unknown"` (title/host/published/location) or `""` (dates/prize) or `[]` (themes). `url` is stored exactly as returned/constructed, stripped of surrounding whitespace.

### Field mapping tables

**Devpost -> contract:**

| Contract key | Devpost source |
|---|---|
| `source` | literal `"Devpost"` |
| `title` | `title` |
| `url` | `url` |
| `summary` | `title` + themes + `time_left_to_submission` joined (list API has no description; keep it short) |
| `published` | parsed from `submission_period_dates` (algorithm in 3.1), else `"Unknown"` |
| `location` | `displayed_location.location` |
| `mode` | `"online"` if location is `"Online"`, else `"in-person"` |
| `host` | `organization_name` or `"Unknown"` |
| `dates` | `submission_period_dates` |
| `prize` | `prize_amount` with HTML tags stripped |
| `themes` | `[t["name"] for t in themes]` |

**Devfolio -> contract:**

| Contract key | Devfolio source |
|---|---|
| `source` | literal `"Devfolio"` |
| `title` | `name` (append `tagline` in parentheses when present and different) |
| `url` | `f"https://{slug}.devfolio.co/"` |
| `summary` | `desc` stripped to plain text, 500 chars; fallback `tagline`, fallback `""` |
| `published` | `starts_at` converted to IST, date part; else `"Unknown"` |
| `location` | `"{city}, {country}"` when city present; else `location`; else `"Online"` if `is_online` else `"Unknown"` |
| `mode` | `"online"` if `is_online` is true, else `"in-person"` |
| `host` | `hosted_by`, else first sponsor name, else `"Unknown"` |
| `dates` | `"{starts_at date} to {ends_at date}"` in IST, human format |
| `prize` | joined prize names, else `""` |
| `themes` | `[t["name"] for t in themes]` |

---

## 5. The Claude filter (`agent.py`)

**Model:** `claude-sonnet-5` (hard requirement; do not copy signal-digest's stale `claude-opus-4-5`). `max_tokens=4000`. Client init ports verbatim from AGENT-PATTERN.md §3.

**Signature:** `run_agent(items) -> dict` where the dict is the parsed JSON described below. On an empty `items` list, short-circuit and return `{"picks": [], "skipped_count": 0, "week_note": "No new events found this week."}` without calling the API.

### Prompt construction

Serialise every item as a stanza (extends the signal-digest loop with the six new keys):

```
Event 7:
Source: Devfolio
Title: Build with Gemma (Bengaluru AI Sprint)
URL: https://build-with-gemma-bengaluru-ai-sprint.devfolio.co/
Host: IEEE Computer Society
Location: Bengaluru, India
Mode: in-person
Dates: Jul 18, 2026 to Jul 18, 2026
Prize: Overall Prize Money, Runner Up
Themes: FinTech, AI/ML
Summary: Build with Gemma : Bengaluru AI Sprint is a one-day, in-person hackathon...
---
```

### System prompt design

Three blocks, in order:

**Block 1, persona and mission** (new prose; executor writes it from this spec):
The reader is an AI product manager based in Bengaluru, India. He builds with Claude and Gemini, cares about AI agents, LLM tooling, and on-device AI, and wants to attend high-signal hackathons, buildathons, and builder showcases. He has repeatedly missed exactly two kinds of event: prestigious AI-lab or big-tech events held in Bengaluru, and India-wide flagship AI events. The agent's job is to make sure nothing in that class slips past him again.

**Block 2, scoring rubric.** Score each event 0 to 100 as the sum of four components:

| Component | Max | Guidance for the prompt |
|---|---|---|
| Theme fit | 35 | AI agents / LLMs / Claude / Gemini / GenAI as the core theme: 28 to 35. AI as one track among many: 15 to 25. Adjacent tech (fintech, web3, IoT) with an AI angle: 5 to 15. No AI relevance: 0, exclude. |
| Geography | 30 | In-person in Bengaluru: 26 to 30. In-person elsewhere in India: 14 to 22. Online and open to Indian participants: 8 to 14. In-person outside India (not travel-worthy): 0 to 5. Unclear location: treat as at most 8. |
| Host prestige | 25 | Major AI lab or big tech (Anthropic, Google/DeepMind, OpenAI, Meta, Microsoft, XPRIZE tier): 20 to 25. Major startup / unicorn / large dev community (Razorpay, MLH tier): 12 to 19. College clubs and unknown hosts: 0 to 8. |
| Scale and signal | 10 | Large prize pool, high registration count, or "managed by Devpost" badge, or verified Devfolio themes: up to 10. |

**Block 3, tiering, caps, and output contract:**

- `must_see`: score >= 70. `worth_a_look`: 50 to 69. `radar`: 35 to 49 (typically notable global online events). Below 35: exclude and count in `skipped_count`.
- At most 12 picks total. If more qualify, keep the highest-scored.
- Output **only** a JSON object, no markdown fences, no prose, exactly this shape:

```json
{
  "picks": [
    {
      "url": "<copied character-for-character from the event's URL line>",
      "title": "<the event's title>",
      "tier": "must_see",
      "score": 87,
      "scoring": {"theme": 33, "geo": 28, "host": 19, "signal": 7},
      "why": "One or two sentences on why this matters to the reader."
    }
  ],
  "skipped_count": 41,
  "week_note": "One-sentence overview of the week's crop."
}
```

**Block 4, critical constraints** (adapted from signal-digest's ported block; the incident that motivated it is documented in AGENT-PATTERN.md §3):

```
CRITICAL CONSTRAINTS:
- Reason ONLY from the events listed in the user message. Do NOT draw on training knowledge.
- Do NOT invent events, hosts, locations, dates, or URLs not explicitly listed.
- Every "url" value MUST be copied character-for-character from an event's URL line.
  Any URL not present in the input will be programmatically discarded.
- If an event's data is too vague to score a component, score that component low. Never fill gaps by inference.
- Never reference events by their input number. Identify them only by title and url.
- Output raw JSON only: no code fences, no commentary before or after.
```

The user message ports signal-digest's reinforcement line, adapted: `"Here are this week's events. Use ONLY these events. Score, tier, and select per your rubric, and return the JSON object only.\n\n{formatted}"`.

### Response parsing (robust, deterministic)

1. Take `response.content[0].text`, strip whitespace.
2. If it starts with a code fence, strip leading/trailing fence lines.
3. If parsing still fails, extract the substring from the first `{` to the last `}` and retry `json.loads`.
4. If parsing fails after step 3, make **one** retry API call appending `"Your previous output was not valid JSON. Return only the JSON object."` to the user message.
5. If the retry also fails to parse, raise `RuntimeError("agent returned unparseable output twice")`. `main.py` catches this (Section 9).
6. Validate shape defensively: `picks` must be a list; each pick must have string `url`, string `title`, `tier` in the allowed set, int-able `score`, string `why`. Drop malformed picks with a printed warning rather than failing the run. Missing `week_note`/`skipped_count` default to `""`/`0`.

Expected steady-state volume: roughly 40 to 90 input events, 5 to 12 picks in the digest.

---

## 6. The programmatic anti-hallucination guard (`guard.py`)

This is a required architectural element. signal-digest's guard is prompt-only and it still hallucinated once (AGENT-PATTERN.md §3 records the "Project Glasswing" incident). Here the guard is mechanical:

```
validate_picks(picks, items) -> (valid_picks, dropped_picks)
```

Algorithm:

1. Build `by_url = {item["url"]: item for item in items}`. Also build a fallback index keyed by `url.rstrip("/")` to tolerate a trailing-slash difference, the single most likely benign mismatch.
2. For each pick: look up `pick["url"]` exactly; on miss, retry with `pick["url"].strip().rstrip("/")` against the fallback index. No other fuzziness. No substring matching, no domain matching.
3. **Miss:** the pick is dropped into `dropped_picks` and a warning is printed with the offending URL. Dropped picks never reach the digest.
4. **Hit:** the pick is enriched with a reference to the matched source item (`pick["item"] = matched_item`). The digest renderer takes **title, host, location, mode, dates, prize, source from the matched item**, not from Claude's output. Claude contributes only `tier`, `score`, `scoring`, and `why`. A hallucinated venue or date is therefore structurally impossible in the email, even for a pick that passes the URL check.
5. If `dropped_picks` is non-empty, the digest gets a visible integrity footer line: `"Integrity guard: N pick(s) dropped because their URL was not in the fetched data."` The run itself continues; a partial digest beats no digest.

---

## 7. Dedup / cache design (`cache.json`)

Port `load_cache` / `save_cache` verbatim from AGENT-PATTERN.md §5, including the corrupt-file fallback to `{}` and the legacy-format migration branch (harmless here).

- **Structure:** flat map `{url: "YYYY-MM-DD first seen"}`. Same as signal-digest.
- **Key:** the normalised item `url` (Devpost's returned URL; Devfolio's constructed slug URL). Both verified stable and unique.
- **TTL:** `CACHE_TTL_DAYS = 45` (vs signal-digest's 21). Rationale: hackathon registration windows run for weeks; announce-once semantics need a TTL longer than a typical open window so an event is not re-announced mid-window. An event still open after 45 days resurfaces once, which doubles as a deadline reminder. Tunable constant, documented in spec.md.
- **What gets cached:** every item that survives fetch and reaches Claude (the signal-digest behaviour), not just digest picks. Consequence: each weekly digest contains only events **first seen** that week, and rejected events are not re-scored weekly (saves tokens). Tradeoff documented in learnings.md: an event whose details improve after first sight will not be re-evaluated within the TTL.
- **When read/written:** read once at the top of `fetch_events`; items with a cache hit inside TTL are skipped before normalisation returns. Written once at the end of a **non-dry** run, merging `{item.url: today}` over the old map.
- **`--dry-run` interaction:** identical to signal-digest. Dry run neither loads (`cache = {}`) nor saves the cache, so it shows everything currently live and is repeatable without polluting state.

---

## 8. Digest and email design

### Markdown assembly (`digest.py`, code-owned)

`build_digest(picks, dropped, source_health, week_note) -> str` renders markdown deterministically:

```
*{week_note}*

## 🔥 Must-see
### [Build with Gemma (Bengaluru AI Sprint)](https://build-with-gemma-bengaluru-ai-sprint.devfolio.co/)
**IEEE Computer Society** · Bengaluru, India · in-person · Jul 18, 2026
Prize: Overall Prize Money, Runner Up · via Devfolio · score 87
> One or two sentences from Claude on why this matters.

## 👀 Worth a look
...same card shape...

## 📡 On the radar (online / global)
...same card shape...

---
**Source health:** Devpost: 43 new events · Devfolio: 12 new events
```

Rules:

- Sections appear only if they have picks; within a section, picks sort by score descending.
- Every card's factual fields come from `pick["item"]` (the guard-matched source item). Only the blockquote line and the score come from Claude.
- Empty `prize` and `"Unknown"` host degrade gracefully (omit the fragment rather than printing "Unknown" where it reads badly; keep "Unknown host" out of the bold slot by falling back to the source name).

### Zero-results and degradation safeguards (required)

The **source health footer is always present** and is the safeguard: a source is never silently dropped.

- Source returned items: `Devpost: 43 new events`.
- Source returned zero (fetch OK, nothing new): `Devpost: 0 new events ⚠️`.
- Source failed (exception/HTTP error): `Devpost: FAILED (Connection timeout) ⚠️ digest may be incomplete`.
- Guard drops, if any, appear as the integrity line (Section 6).
- **Zero picks but sources healthy:** the digest body is `"Quiet week: N events were fetched and none cleared the relevance bar."` plus the health footer. The email still goes out.
- **All sources failed:** digest body is a plain failure notice listing each source's error. The email still goes out.

Policy: **an email is sent every Sunday no matter what** (except a crash caught by the fatal handler, Section 9, which also tries to email). Silence on a Sunday therefore always means the pipeline itself is broken, never "there was nothing to say". This makes the system's health observable from the inbox alone.

### Email chrome and send path (`deliver.py`, ported)

- Port `markdown_to_html` (with `markdown` lib, `extra` + `nl2br` extensions), `get_date_range`, `save_to_archive`, and `send_digest` from AGENT-PATTERN.md §6 and §7 verbatim, then retheme.
- Heading: `Buildathon Radar`. Subtitle: the date-range line. Accent colour: switch the orange to a deep blue (`#1a56db`); sans-serif body is fine, executor's aesthetic call.
- Subject: `🛰️ Buildathon Radar | {Mon DD, YYYY} | {N} events` (N = pick count; on failure emails use `| run failed`).
- From/To both `EMAIL_ADDRESS` (mails to self), Gmail `SMTP_SSL` on port 465 with the app password, `multipart/alternative` with the markdown as the plain part. All exactly as ported.
- Archive: `archive/radar_YYYY-MM-DD.md` written before send; archive failure warns but never blocks the send (ported behaviour).

---

## 9. Failure resilience

Layered, from the inside out:

1. **Per-source isolation** (`fetcher.py`): each source's fetch runs inside its own try/except (the AGENT-PATTERN §4 pattern with HTTP-shaped failure detection replacing `feed.bozo`): `requests` exceptions, non-2xx status (`raise_for_status`), and JSON decode errors are all caught per source. A failed source contributes zero items plus an error string to `source_health`. One broken source never kills the run.
2. **Source health contract:** `fetch_events(dry_run=False) -> (items, source_health)` where `source_health = {"Devpost": {"count": 43, "error": None}, "Devfolio": {"count": 0, "error": "HTTP 503"}}`. This flows through `main.py` into the digest footer.
3. **Agent-level:** empty item list short-circuits without an API call. Unparseable model output retries once, then raises (Section 5).
4. **Guard-level:** invalid URLs degrade the digest, never abort it (Section 6).
5. **Delivery-level:** archive failure warns and continues; missing credentials print an error and return; SMTP failures are caught and printed (ported behaviour).
6. **Fatal handler** (`main.py`): the top-level try/except ports from AGENT-PATTERN §1 (non-zero exit for the journal) with one addition: on a fatal exception in a **non-dry** run, before exiting 1, attempt to send a minimal failure email (`subject: 🛰️ Buildathon Radar | run failed`, body: the exception text) inside its own try/except. Preserves the "silence means broken pipeline, an email means the timer fired" invariant even for crashes, while never masking the non-zero exit.

A **degraded digest** therefore looks like: normal picks from the healthy source, a ⚠️ FAILED line for the broken one in the health footer, and possibly the integrity-guard line. A **failed run** looks like: a short failure email plus a non-zero exit in `journalctl --user -u buildathon-radar.service`.

---

## 10. Build plan: ordered, verifiable phases

Global rules for the executor:

- Work through phases strictly in order. Each phase ends with its verification passing.
- `git add` + `git commit` at the end of every phase with a one-line message (`Phase 3: agent filter with mocked tests`). Do not push.
- **Claude API usage rule:** all tests mock the `anthropic` client (patch `client.messages.create`). The **only** live Claude calls permitted during the build are the single `--dry-run` executions in Phases 6 and 8. Never call `send_digest`'s SMTP send path with a real message during the build; the one real email is Job's morning proof-of-life run.
- Live HTTP fetches of Devpost/Devfolio are read-only and permitted freely.
- Python: create `venv/` with the system Python 3.13 (`python3 -m venv venv`). Always invoke via `venv/bin/python` and `venv/bin/pip` (no activation needed; matches the systemd unit).

**Phase 0: environment and scaffolding.**
Create `venv/`; `venv/bin/pip install anthropic requests python-dotenv markdown pytest`; write `requirements.txt` (pin nothing, list the five names); append to `.gitignore`: `cache.json`, `archive/`, `scheduler_log.txt` (the existing .gitignore already covers `.env`, `venv/`, `__pycache__/`, `*.log`, `.pytest_cache/`); create the package skeleton (`buildathon_radar/__init__.py`, empty module files, `tests/`, `scheduler/systemd/`).
*Verify:* `venv/bin/python -c "import anthropic, requests, dotenv, markdown, pytest; print('ok')"` prints ok, and `venv/bin/python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(all(os.getenv(k) for k in ('ANTHROPIC_API_KEY','EMAIL_ADDRESS','EMAIL_PASSWORD')))"` prints True.

**Phase 1: fetcher.**
Implement `fetcher.py`: `fetch_devpost()`, `fetch_devfolio()`, normalisation per Section 4, cache helpers per Section 7, `fetch_events(dry_run=False)` per Section 9. Add an `if __name__ == "__main__":` harness that runs `fetch_events(dry_run=True)` and prints per-source counts and the first two normalised items. While here, save one live raw response per source, trimmed to 2 or 3 items, into `tests/fixtures/devpost_sample.json` and `tests/fixtures/devfolio_sample.json` for Phase 2.
*Verify:* `venv/bin/python -m buildathon_radar.fetcher` exits 0, shows a nonzero Devpost count (expect roughly 40 to 80) and a nonzero Devfolio count (expect roughly 15 to 25), and every printed item has all 11 contract keys with no `None` values.

**Phase 2: fetcher and cache tests.**
pytest tests against the Phase 1 fixtures (no network in tests; patch `requests.post`/`requests.get` or feed the normaliser functions fixtures directly): normalisation field mapping for both sources including null-field fallbacks and the Devpost date-parse edge cases; cache TTL logic (fresh hit suppressed, stale entry resurfaces, corrupt file yields `{}`); dry-run skips cache read and write.
*Verify:* `venv/bin/pytest` green.

**Phase 3: agent.**
Implement `agent.py` per Section 5 (client init, stanza serialiser, system prompt blocks 1 to 4, JSON parse ladder, defensive shape validation, empty-input short-circuit). Tests mock `messages.create`: clean JSON parses; fenced JSON parses; prose-wrapped JSON parses via brace extraction; garbage triggers exactly one retry then `RuntimeError`; malformed pick dropped with warning; empty input never touches the client.
*Verify:* `venv/bin/pytest` green. No live API call in this phase.

**Phase 4: guard and digest.**
Implement `guard.py` per Section 6 and `digest.py` per Section 8. Tests: fabricated URL dropped and counted; trailing-slash variant matched; card facts come from the source item even when the pick's `title` disagrees; section ordering and score sort; zero-picks quiet-week body; failed-source ⚠️ footer; integrity line renders when drops exist.
*Verify:* `venv/bin/pytest` green.

**Phase 5: delivery.**
Implement `deliver.py` (port + retheme per Section 8). Two checks, neither sends mail: (a) render a sample digest through `markdown_to_html` and write it to the scratch dir, inspect that it contains the heading, cards, and footer; (b) SMTP auth-only probe: `smtplib.SMTP_SSL("smtp.gmail.com", 465)` + `login(...)` + `quit()` using the .env credentials, so the morning run cannot fail on auth. Do not call `sendmail`.
*Verify:* login probe prints success; rendered HTML file contains the expected sections. pytest still green (add a unit test for subject formatting and the failure-email helper with SMTP mocked).

**Phase 6: orchestrator and first live dry run.**
Implement `main.py` per Sections 2 and 9 (flag parse, four-stage flow, source-health plumbing, fatal handler with failure-email attempt gated on `not dry_run`).
*Verify:* `venv/bin/python main.py --dry-run` exits 0, prints a real digest built from live fetches and **one live claude-sonnet-5 call**, prints the DRY RUN line, sends no email, and leaves no `cache.json` and no `archive/` writes. Sanity-read the output: picks have plausible scores, Bengaluru/India events outrank generic online ones, the health footer shows both sources.

**Phase 7: scheduling.**
Write both unit files exactly as in Section 11 into `scheduler/systemd/` plus a short install README; copy them to `~/.config/systemd/user/`; `systemctl --user daemon-reload`; `systemctl --user enable --now buildathon-radar.timer`. (Machine facts, verified: timezone `Asia/Kolkata`, `Linger=yes` for jcube, so user timers fire without an active session. `OnCalendar` uses system local time, hence 17:00 is 5:00 PM IST.) Do **not** `systemctl --user start buildathon-radar.service` (that would send a real email).
*Verify:* `systemctl --user list-timers` shows `buildathon-radar.timer` with NEXT = the coming Sunday 17:00 IST.

**Phase 8: docs and final gate.**
Write the five-file doc set per AGENT-PATTERN §10: `README.md` (what it is, setup, run, morning proof-of-life instructions), `spec.md` (architecture, sources with verified endpoints, contract, rubric, guard), `roadmap.md` (done/not-done checklist reflecting this build plus the v2 backlog from Section 12), `learnings.md` (design rationale: JSON-picks vs free-markdown, the mechanical guard vs prompt-only, cache-everything tradeoff, TTL choice, Unstop rejection), `CLAUDE.md` (working context: owner, machine, stack, structure, commands, limitation notes). Update `.env.example`'s dependency comment line to the new package list.
*Verify (final gate, all three):* `venv/bin/pytest` green; `venv/bin/python main.py --dry-run` exits 0 (second and last live Claude call); `systemctl --user list-timers` still shows the timer. Then final commit.

**Explicitly left for me (morning proof-of-life):** run `venv/bin/python main.py` once (no flag). This performs the first real run: live fetch, live Claude call, writes `cache.json`, writes `archive/radar_*.md`, and sends the one real digest email to my inbox. Nothing else remains.

---

## 11. systemd unit files (final content)

Machine facts verified on 2026-07-13: project at `/home/jcube/projects/buildathon-radar`, timezone `Asia/Kolkata`, `loginctl` Linger=yes for `jcube`, no conflicting user timers.

`scheduler/systemd/buildathon-radar.service`:

```ini
[Unit]
Description=Buildathon Radar weekly AI-event digest
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/jcube/projects/buildathon-radar
ExecStart=/home/jcube/projects/buildathon-radar/venv/bin/python main.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

`scheduler/systemd/buildathon-radar.timer`:

```ini
[Unit]
Description=Run Buildathon Radar every Sunday at 5:00 PM IST
Requires=buildathon-radar.service

[Timer]
OnCalendar=Sun *-*-* 17:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Install (Phase 7): copy both to `~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now buildathon-radar.timer`. Logs: `journalctl --user -u buildathon-radar.service`. `Persistent=true` runs a missed Sunday slot at next boot.

---

## 12. v1 non-goals and v2 backlog

### Hard non-goals for v1 (executor: do NOT build any of these)

- No Luma, no Cerebral Valley (v2, below).
- No LinkedIn, no Twitter/X, no social sources of any kind.
- No scraping and no Apify; API-only sourcing.
- No Google Sheets or any external state; `cache.json` only.
- No WhatsApp or any delivery channel besides the Gmail SMTP email.
- No web UI, no database, no extra config system beyond `.env`.

### v2 backlog (document in `roadmap.md`, do not build)

1. **Cerebral Valley events source.** Motivating incident: the Google DeepMind Bangalore Hackathon was listed there and Job found it too late on Twitter. This is the network-driven, high-prestige tier the v1 APIs structurally miss (recon confirmed: zero Bengaluru in-person AI events on Devpost the same week that class of event existed in the city).
2. **Luma source (lu.ma).** Motivating incident: India Builds with Claude (Razorpay x Anthropic, Bengaluru) was on Luma and reached Job only via a mentor. Luma hosts most Bengaluru AI-community meetups and showcases.
3. Unstop as a third API source if college-tier coverage turns out to be wanted (endpoint verified working, Section 3.3).
4. Deadline-reminder mode (second mention when a cached event nears its close date).
5. Per-event calendar (.ics) attachments.

---

## 13. Pre-run human checklist (before launching the overnight executor)

Verified already done (this session, on this machine):

- [x] `.env` populated with working `ANTHROPIC_API_KEY`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD` (Gmail app password format present).
- [x] `.env` gitignored; `.env.example` committed.
- [x] Pi timezone is `Asia/Kolkata` (so `OnCalendar` 17:00 = 5 PM IST).
- [x] `loginctl` lingering enabled for `jcube` (user timers fire headless).
- [x] Both v1 API endpoints reachable from this Pi (recon ran from here).
- [x] Python 3.13.5 present at `python3`.

To do by Job before the overnight run:

- [ ] Confirm the Anthropic account behind the API key has credit for roughly two Sonnet calls during the build (the Phase 6 and Phase 8 dry runs; a few cents) plus the weekly run thereafter.
- [ ] Answer the open questions in Section 14 and, if any answer differs from the stated default, note it at the top of this file for the executor.
- [ ] Leave the Pi powered and online overnight.
- [ ] Nothing else: no new accounts, no new keys, no package installs (the executor creates the venv and installs deps itself).

Morning proof-of-life (the only post-build human step): `cd ~/projects/buildathon-radar && venv/bin/python main.py`, then check the inbox for the digest and confirm `cache.json` and `archive/` now exist.

---

## 14. Open questions for Job

Each has a default; the executor builds the default unless an override is noted at the top of this file.

1. **Quiet-week emails.** Default: an email is sent every Sunday even when nothing clears the bar (short "quiet week" note plus source health), so inbox silence always means breakage. Alternative: skip the email on empty weeks. Keep default?
2. **Announce-once TTL of 45 days.** Default: each event is announced once and suppressed for 45 days; a still-open event resurfaces once after that. Alternative: shorter TTL for more reminder-like behaviour, or explicit deadline reminders (pushed to v2 backlog item 4). Keep 45?
3. **Global online events.** Default: included but scored into the lower "radar" tier, digest capped at 12 picks. Recon shows most Devpost AI events are online-global, so excluding them would make Devpost nearly silent; including them uncapped would drown the local signal. Keep the capped-tier compromise?
4. **Timer goes live immediately.** Default: the executor enables the systemd timer during the overnight build, so the first automatic send is next Sunday 17:00 IST, and your morning manual run is the first real send. Alternative: leave the timer disabled until you have seen the morning email. Enable overnight?
5. **College-hackathon noise.** Default: trust the rubric (host prestige 0 to 8 for college clubs keeps them out of the top tier, but a Bengaluru college AI hackathon can still reach "worth a look" on geo + theme). Alternative: hard-exclude college events entirely. Trust the rubric?

---

## Appendix A: recon evidence log (2026-07-13, run from jobpi)

| Probe | Result |
|---|---|
| `GET devpost.com/api/hackathons?page=1` | 200, 9 items, `meta.total_count=13583` (all hackathons, unfiltered) |
| `+ status[]=upcoming&status[]=open&themes[]=Machine Learning/AI` | 200, `total_count=69` |
| `+ page=2` | 200, next slice, same total |
| `+ per_page=50` | 200, `meta.per_page=40`, 40 items returned (cap confirmed) |
| `+ challenge_type[]=in-person` | 200, `total_count=65` (param filters) |
| `+ challenge_type[]=in-person&search=bangalore` | 200, `total_count=0` (no Bengaluru in-person AI events listed that day) |
| `?search=india&status[]=upcoming&status[]=open` | 200, `total_count=10`, India college events visible |
| `POST api.devfolio.co/api/search/hackathons {"type":"application_open","from":0,"size":10}` | 200, `hits.total.value=19`, first hit a Bengaluru AI hackathon |
| same, `size=50` | 200, all 19 returned in one page |
| same, `{"type":"upcoming"}` | 200, `hits.total.value=2` |
| same, `+ "q":"ai"` | 200 but `hits.total.value=0` (param unusable, documented) |
| `GET https://build-with-gemma-bengaluru-ai-sprint.devfolio.co/` | 200 (slug URL construction confirmed) |
| `GET unstop.com/api/public/opportunity/search-result?opportunity=hackathons&per_page=10&oppstatus=open&searchTerm=ai` | 200, Laravel pagination, 10 items, student-heavy (v1 rejected) |
