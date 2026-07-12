> Reference blueprint extracted from the signal-digest repo. Describes patterns to port, not this repo's own architecture.

# Agent Pattern: Digest / Radar Blueprint

This document captures the reusable architecture behind Signal Digest so it can be
lifted into a sibling "digest" or "radar" agent in a separate repo. It describes
the pattern, not a line-by-line summary. Where a component ports directly, the
actual code is quoted inline so it can be copied. Where a component is specific to
RSS, it is marked "replace this layer."

A note on punctuation: the prose in this document uses no em dashes. The only em
dashes that appear are inside fenced code blocks and quoted prompt/unit-file text,
reproduced exactly from the existing source files so they can be copied faithfully.
Altering them would misrepresent the code.

The shape of the pattern is:

```
Scheduler -> Fetcher -> Agent (Claude) -> Delivery
```

A trigger fires, sources are fetched and normalised into a common item shape,
already-seen items are filtered out, the remaining items are sent to Claude with a
persona system prompt that forbids hallucination, and the resulting markdown digest
is rendered to HTML, archived locally, and emailed.

Only one layer is source-specific: the fetcher's use of `feedparser`. Everything
else (the Claude call, the seen-state cache, the dry-run gating, the email send,
the scheduler units, the doc convention) ports as-is.

---

## 1. Project layout

```
signal-digest/
├── signal_digest/
│   ├── __init__.py       # empty package marker
│   ├── fetcher.py        # source ingestion + dedup cache (RSS-specific layer)
│   ├── agent.py          # Claude reasoning call + system prompt
│   └── deliver.py        # markdown -> HTML, local archive, SMTP send
├── scheduler/            # cross-platform scheduler configs
│   ├── cron.md           # Linux cron setup notes
│   ├── launchd.plist     # macOS LaunchAgent
│   └── systemd/          # Linux systemd service + timer (+ README)
├── archive/              # weekly digests saved as dated markdown (gitignored)
├── main.py               # entrypoint / orchestrator
├── run_tracker.bat       # Windows Task Scheduler trigger (dev only)
├── .env                  # secrets, not committed
├── .env.example          # secret template, committed
├── cache.json            # seen-URL state with 21-day TTL (gitignored)
├── scheduler_log.txt     # stdout/stderr from scheduled runs (gitignored)
├── CLAUDE.md             # project context for Claude
├── spec.md               # architecture and sources
├── roadmap.md            # done / not-done checklist
└── learnings.md          # agent-vs-script write-up
```

Module responsibilities:

- **`fetcher.py`** owns source definitions, feed pulling, date filtering, the
  seen-state cache, and normalising each source item into a flat dict. This is the
  one module a new agent rewrites if its sources are not RSS.
- **`agent.py`** owns the Anthropic client, the persona system prompt, and the
  single Claude call that turns raw items into a digest. Source-agnostic.
- **`deliver.py`** owns markdown-to-HTML rendering, the local archive write, and
  the SMTP send. Source-agnostic.
- **`main.py`** is the orchestrator. It wires the three modules together, prints
  the digest to stdout, and gates side effects on `--dry-run`.

### Entrypoint pattern (`main.py`, reusable verbatim)

The orchestrator is deliberately thin. It reads one flag, calls three functions in
order, prints the result, and gates the send. Note the top-level try/except that
turns any failure into a non-zero exit code so a scheduler can detect it.

```python
import sys
from signal_digest.fetcher import fetch_recent_articles
from signal_digest.agent import run_agent
from signal_digest.deliver import send_digest

dry_run = "--dry-run" in sys.argv

try:
    articles = fetch_recent_articles(dry_run=dry_run)
    digest = run_agent(articles)

    print("\n" + "="*60)
    print("SIGNAL DIGEST — WEEKLY DIGEST")
    print("="*60 + "\n")
    print(digest)

    if dry_run:
        print("\nDRY RUN — cache not updated, email not sent")
    else:
        send_digest(digest)

    sys.exit(0)

except Exception as e:
    print(f"\nFATAL ERROR: {e}")
    sys.exit(1)
```

For a new agent, the only edits here are the module names and the banner text.

---

## 2. Config and secrets

Secrets live in a `.env` file at the repo root, loaded with `python-dotenv`. Each
module that needs a secret calls `load_dotenv()` at import time and reads values
with `os.getenv(...)`. There is no central config object; env vars are read
directly where used.

Exact env var names:

| Variable | Used by | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | `agent.py` | Authenticates the Anthropic client |
| `EMAIL_ADDRESS` | `deliver.py` | Gmail sender **and** recipient (same address) |
| `EMAIL_PASSWORD` | `deliver.py` | Gmail app password (not the account password) |

Note: `deliver.py` uses `EMAIL_ADDRESS` for both the `From` and the `To`. The
digest is mailed to the same account that sends it. A new agent that mails someone
else would add a separate recipient variable.

Loading pattern (top of both `agent.py` and `deliver.py`):

```python
import os
from dotenv import load_dotenv

load_dotenv()
```

### `.env.example` (exact contents, committed)

```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
EMAIL_ADDRESS=your_gmail@gmail.com
EMAIL_PASSWORD=your_gmail_app_password_here

# Dependencies: pip install anthropic feedparser python-dotenv markdown
```

`.env` itself is gitignored. So are `venv/`, `__pycache__/`, `archive/`,
`cache.json`, `logs/`, and `scheduler_log.txt`.

---

## 3. The Claude call

All Claude logic lives in `agent.py`. The client is initialised once at module load:

```python
import anthropic
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
```

Model in use: `claude-opus-4-5` (hardcoded as a string in the `messages.create`
call). `max_tokens=2000`.

Note on the model id: the code pins `claude-opus-4-5`. If a new agent wants the
latest generation at time of writing, the current ids are `claude-opus-4-8`
(Opus 4.8) and `claude-sonnet-5` (Sonnet 5). The existing code was not modified;
this is just a pointer for whoever copies it.

### Function signature

```python
def run_agent(articles):
    ...
    return response.content[0].text
```

It takes the normalised list of item dicts and returns a single markdown string
(the digest body). On an empty list it short-circuits and returns
`"No new articles this week."` without calling the API. On an API exception it
catches and returns an error string rather than raising, so `main.py` still runs
delivery with a visible error message rather than crashing.

### Prompt construction

Two-part prompt: a static persona/rules **system prompt**, and a **user message**
that is just the serialised items plus a one-line instruction.

The items are flattened into a plain-text block, one article per stanza:

```python
formatted = ""
for i, a in enumerate(articles):
    formatted += f"""
Article {i+1}:
Source: {a['source']}
Title: {a['title']}
Published: {a['published']}
URL: {a['url']}
Summary: {a['summary']}
---
"""
```

The API call:

```python
response = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=2000,
    system=SYSTEM_PROMPT,
    messages=[
        {
            "role": "user",
            "content": f"Here are this week's articles. Use ONLY these articles — "
                       f"do not reference anything from your training data. Filter "
                       f"and write my digest.\n\n{formatted}"
        }
    ]
)
```

### Anti-hallucination guard (the important part)

There is **no programmatic output validation**. The digest text is returned as-is;
nothing checks that every URL in the output was actually in the input. The guard is
entirely at the prompt level, and it is layered in two places:

1. A `CRITICAL CONSTRAINTS` block in the system prompt.
2. A reinforcing instruction in the user message ("Use ONLY these articles").

The system prompt's constraint block, quoted verbatim so it can be reused:

```
CRITICAL CONSTRAINTS:
- Reason ONLY from the articles listed in the user message. Do NOT draw on training knowledge.
- If a title or summary is too vague to assess, skip the article — do not infer or fill in content.
- Every signal you extract must be directly traceable to the provided article text.
- Do NOT invent article details, authors, or sources not explicitly listed below.
- Cross-article synthesis is encouraged (e.g. spotting a trend across multiple articles), but only from the provided set.
- NEVER reference articles by number (e.g. "Article 3" or "#12"). Always use the source name and a hyperlink.
- Format every individual signal as a markdown hyperlink: [Source Name: signal text](URL)
  Use the exact URL provided for that article.
```

`learnings.md` records why this block exists: an early run hallucinated articles
("Project Glasswing", "GLM-5.1") that were never in the feed, because the model
filled gaps from training knowledge. The constraint block was the fix.

**Reuse note:** for a new agent, the persona paragraphs (who the reader is, what
their lens is) get rewritten, but the entire `CRITICAL CONSTRAINTS` block and the
output-format rules port unchanged. If the new agent needs a hard guarantee rather
than a prompt-level one, add a post-generation check that every markdown link URL
in the output appears in the input item set. That guard does not exist today.

---

## 4. Source fetching

Entry function:

```python
def fetch_recent_articles(days_back=7, dry_run=False):
    ...
    return articles
```

Returns a flat list of dicts. **This normalised shape is the contract** between the
source layer and everything downstream. It is the source-agnostic part: the agent
and delivery only ever see this shape.

```python
{
    "source":    "Simon Willison",      # human-readable source name
    "title":     "...",                 # item title
    "url":       "https://...",         # canonical link, also the dedup key
    "summary":   "...",                 # trimmed to 500 chars
    "published": "2026-04-11",          # "YYYY-MM-DD" or "Unknown"
}
```

Any new agent should preserve exactly these five keys, because `agent.py`'s prompt
builder reads `a['source']`, `a['title']`, `a['url']`, `a['published']`,
`a['summary']` by name.

### What is RSS-specific (REPLACE THIS LAYER)

Everything that touches `feedparser` is the swap point. In a new agent, this is the
only code that changes shape:

```python
import feedparser

SOURCES = [
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/"},
    # ... 16 feed dicts total
]

feed = feedparser.parse(source["url"])

# feedparser-specific failure detection: network errors do not raise,
# they return a "bozo" feed object with an exception attached
if feed.bozo and not feed.entries:
    print(f"  WARNING: {source['name']} feed error: {feed.bozo_exception}")
    failed_sources.append(source["name"])
    continue

for entry in feed.entries[:10]:      # cap 10 items per source
    published = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        published = datetime(*entry.published_parsed[:6])
    url = entry.get("link", "")
    title = entry.get("title", "No title")
    summary = entry.get("summary", "")[:500]
```

The RSS-specific concerns a replacement must re-implement in its own terms:
- Iterating a source list and pulling from each.
- Detecting per-source failure without crashing the whole run (RSS uses
  `feed.bozo`; an API source would check an HTTP status).
- Extracting a published timestamp (RSS gives `published_parsed`; another source
  gives its own field).
- Producing the five-key dict above.

### What is source-agnostic (REUSE)

These parts sit around the feedparser calls and port directly:

- The `days_back` cutoff filter (`datetime.now() - timedelta(days=days_back)`).
- The per-source try/except with a `failed_sources` list, so one bad source does
  not abort the run.
- The seen-state cache read/filter/write (see next section).
- Producing and returning the flat list.

A replacement source layer keeps the same function signature
`fetch_recent_articles(days_back=7, dry_run=False)` and the same return contract,
and only swaps the feedparser body.

---

## 5. Deduplication / seen-state

State lives in `cache.json` at the repo root (gitignored). It exists so an item is
not surfaced twice across runs, and re-surfaces after a cooling-off period.

### Structure

```json
{
  "https://example.com/post-a": "2026-04-11",
  "https://example.com/post-b": "2026-04-12"
}
```

A flat map of `url -> date-first-seen` (`"YYYY-MM-DD"`). The URL is the dedup key.
TTL is 21 days (`CACHE_TTL_DAYS = 21`).

There is a legacy format `{"urls": [...], "last_updated": "..."}` that `load_cache`
migrates on first read, stamping every old URL with today's date.

### When it is read

Once, at the top of `fetch_recent_articles`, before iterating sources. During the
per-item loop, an item is skipped if its URL is in the cache **and** was first seen
within the last 21 days. If the seen date is older than the TTL, the item is
treated as new again (and will be re-stamped with today's date on save).

```python
if url in cache:
    try:
        seen_date = datetime.strptime(cache[url], "%Y-%m-%d")
    except ValueError:
        seen_date = datetime.min
    if seen_date >= prune_cutoff:
        continue
    # seen_date older than TTL -> treat as new
```

### When it is written

Once, at the end of the run, only on a non-dry run. The new batch's URLs are merged
in with today's date, then the whole map is written back:

```python
if not dry_run:
    updated_cache = {**cache, **{a["url"]: today for a in articles}}
    save_cache(updated_cache)
```

Note the merge keeps old entries. Entries are not actively pruned from the file;
they simply stop suppressing once past TTL. The file grows over time.

### Reusable read/write helpers (port directly)

```python
CACHE_FILE = "cache.json"
CACHE_TTL_DAYS = 21

def load_cache():
    """Returns {url: date_first_seen} dict. Migrates old {"urls": [...]} format."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
            if "urls" in data:  # migrate legacy format
                today = datetime.now().strftime("%Y-%m-%d")
                return {url: today for url in data["urls"]}
            return data
    except Exception:
        pass
    return {}

def save_cache(cache):
    """Saves {url: date_first_seen} dict to cache file."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"  WARNING: Cache save error: {e}")
```

Both helpers swallow exceptions and fall back gracefully (empty dict on read error,
warning on write error), so a corrupt cache never crashes the run.

### How `--dry-run` interacts with the cache

Two effects, both in `fetch_recent_articles`:

1. The cache is **not loaded**: `cache = {} if dry_run else load_cache()`. With an
   empty cache, no item is suppressed, so a dry run shows every item from the last
   `days_back` days regardless of prior runs.
2. The cache is **not written**: the `save_cache` call is inside `if not dry_run`.

So a dry run neither reads nor writes state. It is safe to run repeatedly without
polluting the cache.

**Reuse note:** the cache is keyed purely on URL. Any new agent whose items have
stable unique URLs (or any stable string id) reuses this whole mechanism by
swapping the key. An agent whose items lack a stable id must pick a different key
(a content hash, for example) before this ports.

---

## 6. Digest formatting

The digest **body** is authored entirely by Claude as markdown. `agent.py` returns
that markdown string; no code assembles the body. The format is dictated by the
system prompt, not by code:

- 3 to 5 theme clusters.
- Each cluster: a theme title, 2 to 3 signals, and a short "why this matters"
  paragraph.
- Every signal is a markdown hyperlink `[Source Name: signal text](URL)`.
- A single "Signal of the week" at the end.

Code owns only the **chrome** around that body, in `deliver.py`:

- A fixed `<h1>` heading ("Job's Weekly Signal Digest"), injected by code, not by
  Claude, so the title is never at the model's discretion.
- A dynamic date-range subtitle computed by `get_date_range()` (for example
  "April 5 – 11, 2026"), spanning the last 6 days.
- A fixed footer.

The markdown-to-HTML conversion uses the `markdown` library with the `extra` and
`nl2br` extensions (extra handles tables/links/etc; nl2br turns newlines into line
breaks so the model's plain newlines render as expected):

```python
import markdown
html_body = markdown.markdown(text, extensions=["extra", "nl2br"])
```

The full HTML template (inline CSS, serif body, orange accent) lives in
`markdown_to_html(text, date_range=None)` in `deliver.py`. It is a self-contained
styled email shell; a new agent can copy it wholesale and change the heading text
and accent colour.

---

## 7. Email delivery

Mechanism: Gmail over SMTP SSL on port 465, authenticating with an app password.
The message is a `multipart/alternative` carrying both a plain-text part (the raw
markdown) and an HTML part (the rendered template). One function does archive +
send.

Setup gotchas:
- `EMAIL_PASSWORD` must be a Gmail **app password**, not the account password.
  Requires 2FA enabled on the Google account.
- Sender and recipient are both `EMAIL_ADDRESS` (mails to self).
- Archive-to-disk happens first and is wrapped so an archive failure does not block
  the send.
- If credentials are missing, it prints an error and returns rather than raising.

### The send function (port directly)

```python
def send_digest(digest_text):
    try:
        save_to_archive(digest_text)
    except Exception as e:
        print(f"  WARNING: Could not save to archive: {e}")

    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_ADDRESS")

    if not sender or not password:
        print("  ERROR: EMAIL_ADDRESS or EMAIL_PASSWORD not set in .env — skipping email send.")
        return

    try:
        date_range = get_date_range()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📡 Signal Digest — {datetime.now().strftime('%b %d, %Y')}"
        msg["From"] = f"Signal Digest <{sender}>"
        msg["To"] = recipient

        text_part = MIMEText(digest_text, "plain")
        html_part = MIMEText(markdown_to_html(digest_text, date_range), "html")

        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print("Digest sent to your inbox.")
    except smtplib.SMTPAuthenticationError:
        print("  ERROR: Gmail authentication failed. Check EMAIL_ADDRESS and EMAIL_PASSWORD in .env.")
    except smtplib.SMTPException as e:
        print(f"  ERROR: SMTP error — {e}")
    except Exception as e:
        print(f"  ERROR: Failed to send email — {e}")
```

### Local archive (port directly)

Before sending, the raw digest markdown is saved to `archive/digest_YYYY-MM-DD.md`:

```python
def save_to_archive(digest_text):
    archive_dir = "archive"
    os.makedirs(archive_dir, exist_ok=True)
    week_label = datetime.now().strftime("%Y-%m-%d")
    filename = f"{archive_dir}/digest_{week_label}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Signal Digest — Week of {week_label}\n\n")
        f.write(digest_text)
    return filename
```

The required imports for the whole delivery module:

```python
import smtplib, os, markdown
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
```

**Reuse note:** for a non-Gmail sender, only the host/port in `SMTP_SSL` and the
credential handling change; the multipart assembly ports as-is. For a non-email
channel (Slack, a webhook), replace the SMTP block but keep the archive step and
the `markdown_to_html` render if the channel accepts HTML.

---

## 8. The `--dry-run` flag

Detected in `main.py` as `dry_run = "--dry-run" in sys.argv` and threaded into
`fetch_recent_articles(dry_run=...)`.

What it **suppresses**:
- **Cache read.** The cache is not loaded, so no item is filtered as "seen."
- **Cache write.** The new batch is not persisted.
- **Email send.** `main.py` prints the digest and the line
  `"DRY RUN — cache not updated, email not sent"` instead of calling
  `send_digest`.

What it **still does**:
- Fetches all sources for real (live network calls).
- Runs the real Claude call and produces a real digest.
- Prints the full digest to stdout.

What it notably does **not** do: because `send_digest` is skipped entirely, a dry
run also does **not** write to `archive/` (the archive write lives inside
`send_digest`, not the fetch path). So dry-run leaves both `cache.json` and
`archive/` untouched.

**Reuse note:** the pattern is "gate every side effect behind one boolean, thread
it from argv into the functions that mutate state." Any new agent keeps this and
just makes sure each new side effect is added inside an `if not dry_run` guard.

---

## 9. Scheduling

Production runs on a Raspberry Pi 5 (headless) using a **systemd user timer + service**
pair. The service is `Type=oneshot`: it runs the pipeline once and exits, and the
timer decides when.

### `signal-digest.service`

```ini
[Unit]
Description=Signal Digest — weekly RSS digest
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# Replace with the absolute path to your project
WorkingDirectory=/home/YOUR_USERNAME/signal-digest
# Replace with the path to your venv Python
ExecStart=/home/YOUR_USERNAME/signal-digest/venv/bin/python main.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

### `signal-digest.timer`

```ini
[Unit]
Description=Run Signal Digest every Monday at 10:00 AM
Requires=signal-digest.service

[Timer]
# Every Monday at 10:00 AM (system local time)
OnCalendar=Mon *-*-* 10:00:00
# If the timer was missed (e.g. machine was off), run at next opportunity
Persistent=true

[Install]
WantedBy=timers.target
```

Key details that make this port cleanly:
- Absolute path to the venv Python in `ExecStart`. Scheduled environments do not
  inherit an activated venv, so the full path is required (the same lesson is
  documented for the Windows `.bat` in `learnings.md`).
- `Persistent=true` catches missed runs when the Pi was off at the scheduled time.
- `WantedBy=default.target` (a user service) rather than `multi-user.target`.
- Output goes to the journal; read it with
  `journalctl --user -u signal-digest.service`.

Install steps (from `scheduler/systemd/README.md`): copy both unit files to
`~/.config/systemd/user/`, then `systemctl --user daemon-reload`,
`enable --now signal-digest.timer`.

The repo also carries alternates that are not the production path: `cron.md` (Linux
cron, `0 10 * * 1`), `launchd.plist` (macOS, Monday 10 AM), and `run_tracker.bat`
(Windows Task Scheduler, at-login, redirecting to `scheduler_log.txt`). A new agent
on the Pi copies the systemd pair and ignores the rest.

---

## 10. Doc-set convention

The repo keeps a deliberate four-file doc discipline. Mirror it in the new repo:

| File | Purpose |
|---|---|
| `CLAUDE.md` | Context for Claude/agents working in the repo: what the project is, the owner, project locations, stack, structure, how it works, sources table, and known limitations. First thing an assistant reads. |
| `spec.md` | Architecture and design: the pipeline flow, the sources table, the project structure, and the stack table. The "what and how it is built" reference. |
| `roadmap.md` | A done / not-done checklist. Completed items marked `[x]` with a one-line note; longer-term items under a separate heading. |
| `learnings.md` | The narrative write-up: the script-vs-agent framing, where the intelligence lives, design lessons (system prompt as identity, hallucination as a risk), and deployment lessons. The "why it is built this way" reference. |

The split is: `CLAUDE.md` for the agent's working context, `spec.md` for structure,
`roadmap.md` for status, `learnings.md` for rationale. Keeping them separate stops
any one file from becoming a dumping ground.

---

## 11. Dependencies

Four runtime packages, installed into a venv. There is no `requirements.txt` in the
repo; the install line is documented in `.env.example` and `CLAUDE.md`:

```bash
pip install anthropic feedparser python-dotenv markdown
```

| Package | Role | Ports to a new agent? |
|---|---|---|
| `anthropic` | Official SDK for the Claude call in `agent.py` | Yes, unchanged |
| `feedparser` | Parses RSS/Atom feeds in `fetcher.py` | No: this is the source-specific layer |
| `python-dotenv` | Loads `.env` into the environment | Yes, unchanged |
| `markdown` | Renders the digest markdown to HTML (`extra` + `nl2br`) | Yes, unchanged (drop it only if delivery is not HTML) |

Standard library used throughout: `smtplib`, `email.mime`, `os`, `json`, `sys`,
`datetime`. Python 3.11.9.

A new agent would drop `feedparser` and add whatever client its source needs (an
HTTP client, a vendor SDK, etc). The other three stay.

---

## What to reuse vs. rebuild for a new agent

| Component | Reuse directly | Rebuild for a new source |
|---|---|---|
| `main.py` orchestrator (flag, 3-call flow, exit codes) | Yes | |
| `.env` loading pattern + var names | Yes | |
| Anthropic client init + `run_agent` structure | Yes | |
| System-prompt `CRITICAL CONSTRAINTS` block | Yes | |
| Persona paragraphs in the system prompt | | Rewrite (new reader, new lens) |
| Prompt item-serialisation loop | Yes (keep the 5-key shape) | |
| Normalised item dict contract (5 keys) | Yes | |
| `load_cache` / `save_cache` + TTL dedup logic | Yes | |
| Cache key = URL | | Rebuild if items lack a stable URL/id |
| `feedparser` fetch, `SOURCES` list, `feed.bozo` handling | | Rebuild (this is the source layer) |
| `days_back` cutoff + per-source try/except pattern | Yes | |
| `markdown_to_html` template + `get_date_range` | Yes (retheme) | |
| `save_to_archive` | Yes | |
| `send_digest` SMTP send | Yes (swap host/creds if not Gmail) | |
| `--dry-run` gating pattern | Yes | |
| systemd service + timer units | Yes (edit paths) | |
| Doc-set convention (4 files) | Yes | |

The single hard boundary is the source layer. Everything upstream of the
normalised five-key dict is `feedparser`-specific and gets rebuilt; everything from
that dict onward (dedup, Claude call, formatting, delivery, scheduling, docs) ports
without structural change.

### Points where the pattern does not transfer cleanly to a non-RSS source

- **The dedup cache assumes a stable per-item URL.** A source whose items have no
  stable unique URL (a search API returning shifting result sets, a social feed
  with ephemeral ids) needs a different key (content hash, composite id) before the
  cache mechanism works.
- **Failure detection is RSS-shaped.** The `feed.bozo and not feed.entries` check
  has no analogue outside feedparser; an API source must implement its own
  per-source error detection to preserve the "one bad source does not abort the
  run" behaviour.
- **The published-date filter assumes each item carries a timestamp.** RSS provides
  `published_parsed`; a source without per-item timestamps cannot use the
  `days_back` cutoff and would need a different freshness signal.
- **There is no programmatic anti-hallucination check.** The guard is prompt-only.
  If a new agent's correctness bar is higher, add a post-generation validation that
  every output link URL was present in the input set. Nothing like that exists in
  the current code.
```