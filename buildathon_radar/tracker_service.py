import html as html_lib
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from buildathon_radar import tracker_store

load_dotenv()

if not os.getenv("TRACKER_SECRET"):
    raise RuntimeError(
        "TRACKER_SECRET is not set. The tracker service cannot verify signed "
        "links without it and must not run open; add it to .env."
    )

DB_PATH = tracker_store.DB_FILE

FONT_STACK = "-apple-system, Roboto, 'Helvetica Neue', Arial, sans-serif"
TEAL_DARK = "#0f4c4c"
PAGE_BG = "#f6f4ef"
CARD_BG = "#ffffff"
ACCENT = "#0d9488"

STATE_ORDER = ["tracked", "applied", "seen", "over"]
STATE_LABELS = {
    "tracked": "Tracked",
    "applied": "Applied",
    "seen": "Seen",
    "over": "Over",
}

app = FastAPI()


def _get_conn():
    return tracker_store.connect(DB_PATH)


def _esc(value):
    return html_lib.escape(str(value or ""))


def _format_date(value):
    """A "YYYY-MM-DD" date string to "Mon DD, YYYY", or None passthrough."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return value


def _format_ts_date(iso_ts):
    """An ISO 8601 timestamp (as stored in tracked_at/applied_at) to
    "Mon DD, YYYY", or a safe fallback if unparseable/missing."""
    if not iso_ts:
        return "an earlier visit"
    try:
        return datetime.fromisoformat(iso_ts).strftime("%b %d, %Y")
    except ValueError:
        return "an earlier visit"


def _page(headline, lines, event_url=None, accent=ACCENT):
    """Self-contained confirmation page: inline CSS only, no external
    assets, no JavaScript, system font stack, teal palette matching the
    digest template. Meant to be opened on a phone, possibly weeks later."""
    body_lines = "".join(f'<p style="margin:0 0 10px 0;">{line}</p>' for line in lines)
    link_html = ""
    if event_url:
        link_html = (
            f'<p style="margin:18px 0 0 0;">'
            f'<a href="{_esc(event_url)}" style="color:{accent}; font-weight:bold; '
            f'text-decoration:none;">Open event page &rarr;</a></p>'
        )
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Buildathon Radar</title>
</head>
<body style="margin:0; padding:0; background-color:{PAGE_BG}; font-family:{FONT_STACK};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{PAGE_BG};">
<tr>
<td align="center" style="background-color:{PAGE_BG}; padding:40px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%; max-width:480px; background-color:{CARD_BG};">
<tr>
<td style="background-color:{accent}; padding:20px 24px;">
<div style="font-family:{FONT_STACK}; font-size:13px; font-weight:bold; color:#ffffff; letter-spacing:0.5px;">BUILDATHON RADAR</div>
</td>
</tr>
<tr>
<td style="background-color:{CARD_BG}; padding:24px; font-family:{FONT_STACK}; color:#2e4243;">
<div style="font-size:20px; font-weight:bold; color:{TEAL_DARK}; margin-bottom:12px; word-break:break-word; overflow-wrap:break-word;">{_esc(headline)}</div>
<div style="font-size:14px; line-height:1.5; word-break:break-word; overflow-wrap:break-word;">{body_lines}</div>
{link_html}
</td>
</tr>
</table>
</td>
</tr>
</table>
</body>
</html>"""


def _health_page():
    return _page("Buildathon Radar tracker is running.", [
        "This is a liveness check only. No event data is exposed here."
    ])


def _malformed_page():
    return _page("Malformed link", ["This link is missing its event. Nothing was recorded."])


def _invalid_token_page():
    return _page("Invalid link", [
        "This link is missing its signature or the signature does not match.",
        "Nothing was recorded.",
    ])


def _unknown_event_page():
    return _page("Unknown event", [
        "This link may be from a digest sent before tracking existed, or the "
        "event was never in a digest. Nothing was recorded.",
    ])


def _ok_page(action, row):
    title = _esc(row["title"])
    if action == "track":
        lines = [f"<strong>{title}</strong>"]
        start = _format_date(row["event_start"])
        if start:
            lines.append(f"Starts {_esc(start)}.")
        lines.append(
            "This event will reappear in your Sunday digest as a reminder "
            "until it starts."
        )
        return _page("\U0001F4CC Tracked", lines, event_url=row["url"])
    else:
        lines = [
            f"<strong>{title}</strong>",
            "It's now in your participation log at the bottom of every digest.",
        ]
        return _page("\U0001F3AF Applied", lines, event_url=row["url"])


def _noop_page(action, row):
    title = _esc(row["title"])
    state = row["state"]

    if action == "track" and state == "applied":
        headline = "Already applied"
        marked = _format_ts_date(row["applied_at"])
        lines = [
            f"<strong>{title}</strong>",
            f"Marked applied on {_esc(marked)}. Applied outranks Track, so "
            "nothing was downgraded.",
        ]
    elif action == "track":
        headline = "Already tracked"
        marked = _format_ts_date(row["tracked_at"])
        lines = [
            f"<strong>{title}</strong>",
            f"Marked on {_esc(marked)}. Nothing was changed.",
        ]
    else:
        headline = "Already applied"
        marked = _format_ts_date(row["applied_at"])
        lines = [
            f"<strong>{title}</strong>",
            f"Marked on {_esc(marked)}. Nothing was changed.",
        ]
    return _page(headline, lines, event_url=row["url"])


def _list_row(row):
    title = _esc(row["title"])
    url = _esc(row["url"])
    source = _esc(row["source"] or "Unknown")
    start = _esc(_format_date(row["event_start"]) or "TBD")
    end = _esc(_format_date(row["event_end"]) or "TBD")
    return f"""<div class="event-row">
<a class="event-title" href="{url}">{title}</a>
<div class="event-meta">{source} &middot; {start} to {end}</div>
</div>"""


def _list_page(rows):
    """Read-only view over every row in tracker.db, grouped by state so
    tracked and applied events stand out. A real browser page, not an email:
    no need for the table-layout/inline-CSS email rules, just simple,
    mobile-readable HTML in the same teal theme as the confirmation pages."""
    if not rows:
        body = (
            '<p class="empty">Nothing tracked or applied yet. Tap Track or '
            "Applied on an event in your weekly digest and it will show up "
            "here.</p>"
        )
    else:
        by_state = {}
        for row in rows:
            by_state.setdefault(row["state"], []).append(row)

        sections = []
        for state in STATE_ORDER:
            state_rows = by_state.get(state)
            if not state_rows:
                continue
            rows_html = "".join(_list_row(r) for r in state_rows)
            sections.append(f"""<section>
<h2>{_esc(STATE_LABELS[state])} <span class="count">{len(state_rows)}</span></h2>
{rows_html}
</section>""")
        body = "".join(sections)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Buildathon Radar Tracker</title>
<style>
body {{ margin:0; padding:0; background-color:{PAGE_BG}; font-family:{FONT_STACK}; color:#2e4243; }}
header {{ background-color:{TEAL_DARK}; padding:24px; }}
header .title {{ font-size:20px; font-weight:bold; color:#eaf6f4; }}
main {{ max-width:640px; margin:0 auto; padding:16px; }}
section {{ margin-bottom:24px; }}
h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:0.5px; color:{ACCENT}; margin:0 0 8px 0; }}
h2 .count {{ color:#8a9a9a; font-weight:normal; }}
.event-row {{ background-color:{CARD_BG}; border-radius:6px; padding:12px 16px; margin-bottom:8px; }}
.event-title {{ display:block; font-size:16px; font-weight:bold; color:{TEAL_DARK}; text-decoration:none; word-break:break-word; }}
.event-meta {{ font-size:13px; color:#6b7b7b; margin-top:4px; }}
.empty {{ font-size:14px; color:#6b7b7b; padding:24px 16px; }}
</style>
</head>
<body>
<header><div class="title">Buildathon Radar Tracker</div></header>
<main>
{body}
</main>
</body>
</html>"""


def _handle_action(action, event_id, token):
    if not event_id:
        return HTMLResponse(_malformed_page(), status_code=400)

    if not tracker_store.verify_action(action, event_id, token):
        conn = _get_conn()
        try:
            tracker_store.log_action(conn, event_id, action, "bad_token")
        finally:
            conn.close()
        return HTMLResponse(_invalid_token_page(), status_code=403)

    conn = _get_conn()
    try:
        result, row = tracker_store.apply_action(conn, action, event_id)
    finally:
        conn.close()

    if result == "unknown_event":
        return HTMLResponse(_unknown_event_page(), status_code=404)
    if result == "noop":
        return HTMLResponse(_noop_page(action, row), status_code=200)
    return HTMLResponse(_ok_page(action, row), status_code=200)


@app.get("/")
def health():
    return HTMLResponse(_health_page(), status_code=200)


@app.get("/track")
def track(event_id: str | None = None, t: str | None = None):
    return _handle_action("track", event_id, t)


@app.get("/applied")
def applied(event_id: str | None = None, t: str | None = None):
    return _handle_action("applied", event_id, t)


@app.get("/list")
def list_view():
    """Read-only: displays every row in the tracker store, grouped by
    state. No parameters, no signed token, no writes. Intentionally
    unauthenticated, same as the health page, since the data (hackathon
    names and dates) is low-sensitivity."""
    conn = _get_conn()
    try:
        rows = tracker_store.get_all_events(conn)
    finally:
        conn.close()
    return HTMLResponse(_list_page(rows), status_code=200)
