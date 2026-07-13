# spec.md: architecture and design

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

### Rejected for v1: Unstop

`GET https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&per_page=10&oppstatus=open&searchTerm=ai`
works (verified), but the result set skews heavily toward college and
student-eligibility events, and Devfolio already covers the India tier with
richer structured fields. Left as a documented v2 option.

## Normalised item contract

```python
{
    "source":    "Devpost" | "Devfolio",
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
disabled (`thinking={"type": "disabled"}`). See `learnings.md` for why: with
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

`cache.json` is a flat `{url: date_first_seen}` map, TTL 45 days (longer than
signal-digest's 21, since hackathon registration windows commonly run for
weeks and a 21 day TTL would re-announce a still-open event mid-window). An
item still open after 45 days resurfaces once. `--dry-run` neither reads nor
writes the cache, so it is safe to run repeatedly.

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

No Luma, no Cerebral Valley, no social sources (Twitter, LinkedIn), no
scraping, no Apify, no Google Sheets, no WhatsApp. `cache.json` and Gmail SMTP
are the only state and delivery mechanisms.

## v2 backlog

1. Cerebral Valley as a source (the Google DeepMind Bangalore Hackathon was
   listed there and found too late on Twitter).
2. Luma as a source (India Builds with Claude, Razorpay x Anthropic, was on
   Luma and reached the owner only via a mentor).
3. Unstop as a third API source, if college-tier coverage becomes wanted.
4. Deadline-reminder mode (a second mention as a cached event's close date nears).
5. Per-event calendar (.ics) attachments.
