import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

CACHE_FILE = "cache.json"
CACHE_TTL_DAYS = 45  # fallback suppression window for events with no parseable date
RESURFACE_WINDOW_DAYS = 14  # days before event_start a suppressed event may resurface, once
TITLE_MERGE_WINDOW_DAYS = 90  # exact-normalized-title cross-source merge window (see derive_event_id docstring)
SOURCE_REQUEST_DELAY_S = 1  # politeness delay between successive paged requests to the same host

# Cerebral Valley's fetcher is fully built and tested (see fetch_cerebralvalley
# below and tests/test_fetcher.py) but deliberately not wired into the live
# SOURCES list yet. Decision: activate Luma alone this week, verify its real
# behaviour in a live digest, then flip this to True about a week later to
# activate Cerebral Valley. See ROADMAP.md for the full reasoning.
ENABLE_CV_SOURCE = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0",
    "Accept": "application/json",
}

DEVPOST_URL = "https://devpost.com/api/hackathons"
DEVFOLIO_URL = "https://api.devfolio.co/api/search/hackathons"
LUMA_API_URL = "https://api.luma.com/discover/get-paginated-events"
LUMA_PLACE_BENGALURU = "discplace-G0tGUVYwl7T17Sb"
CV_API_URL = "https://api.cerebralvalley.ai/v1/public/event/pull"
CV_WINDOW_DAYS = 60  # how far ahead the Cerebral Valley upcoming window looks
CV_PAGE_LIMIT = 100  # verified server-side cap on the pull endpoint
CV_MAX_PAGES = 6  # runaway guard while paging backward from the tail

IST = timezone(timedelta(hours=5, minutes=30))


# --- Cache record structure ---
#
# {
#   "<event_id>": {
#     "event_id": "<slug>",
#     "urls": ["<url1>", ...],
#     "first_seen": "YYYY-MM-DD",
#     "last_shown": "YYYY-MM-DD",
#     "status": "seen" | "resurfaced" | "lapsed",
#     "resurfaced": bool,          # one-time resurface flag, enforced here, not by the upstream API
#     "event_start": "YYYY-MM-DD" or None,
#     "event_end": "YYYY-MM-DD" or None,
#   }
# }
#
# event_id is a composite of normalized host + normalized title + start date,
# so the same event reappearing under a superficially different title (a
# parenthetical subtitle) or a new URL still maps to one record. Without a
# parseable start date, the id falls back to host + title only, which is a
# weaker (more collision-prone) key: kept only because there is nothing
# better to anchor on.


def _is_legacy_flat_cache(data):
    if not data:
        return False
    sample_value = next(iter(data.values()))
    return isinstance(sample_value, str)


def _legacy_event_id(url):
    """Fallback id for entries migrated from the old flat {url: date} cache,
    which carries no host/title/date to build a composite id from. Weaker
    than derive_event_id (no cross-field collision risk either, since it is
    1:1 with the URL), good enough to preserve already-seen state across the
    migration without inventing facts that were never recorded."""
    stripped = re.sub(r"^https?://", "", url or "").rstrip("/")
    slug = re.sub(r"[^a-z0-9]+", "-", stripped.lower()).strip("-")
    return f"legacy-{slug}" if slug else "legacy-unknown"


def _migrate_legacy_flat_cache(data):
    migrated = {}
    for url, date_str in data.items():
        event_id = _legacy_event_id(url)
        if event_id in migrated:
            if url not in migrated[event_id]["urls"]:
                migrated[event_id]["urls"].append(url)
            continue
        migrated[event_id] = {
            "event_id": event_id,
            "urls": [url],
            "first_seen": date_str,
            "last_shown": date_str,
            "status": "seen",
            "resurfaced": False,
            "event_start": None,
            "event_end": None,
        }
    return migrated


def load_cache():
    """Returns {event_id: record} dict. Migrates, in order: the oldest
    {"urls": [...], "last_updated": ...} format, then the flat {url: date}
    format used through the v1 build, into the current per-event record
    structure. Migration is idempotent: an already-migrated cache round-trips
    unchanged (values are dicts, not strings, so _is_legacy_flat_cache is
    False on the second load)."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)

            if isinstance(data, dict) and isinstance(data.get("urls"), list):
                today = datetime.now().strftime("%Y-%m-%d")
                data = {url: today for url in data["urls"]}

            if _is_legacy_flat_cache(data):
                return _migrate_legacy_flat_cache(data)

            return data
    except Exception:
        pass
    return {}


def save_cache(cache):
    """Saves the {event_id: record} dict to the cache file."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"  WARNING: Cache save error: {e}")


def _normalize_title(title):
    """Strip parenthetical suffixes and dash/colon-introduced trailing
    descriptive text, lowercase, strip punctuation, collapse whitespace.
    e.g. "Agentic Commerce Hackathon (Build agents that act...)" and
    "Agentic Commerce Hackathon" both normalize to "agentic commerce hackathon"."""
    if not title:
        return ""
    t = re.sub(r"\([^)]*\)", "", title)
    t = re.split(r"\s[-:]\s", t)[0]
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _normalize_host(host):
    if not host:
        return ""
    h = host.lower()
    h = re.sub(r"[^a-z0-9\s]", " ", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def _slugify(text):
    return re.sub(r"\s+", "-", text.strip())


def _canonicalize_url(url):
    """Normalizes a URL for cross-source dedup: strips whitespace, forces
    https, and folds Luma's old lu.ma host into its current luma.com host so
    a Cerebral Valley listing that links out to lu.ma/<slug> collapses with
    the same event fetched directly from Luma via the existing url_index
    dedup in fetch_events. A no-op for Devpost/Devfolio URLs, which never
    matched the lu.ma pattern to begin with."""
    if not url:
        return url
    u = url.strip()
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    u = re.sub(r"^https://lu\.ma/", "https://luma.com/", u)
    return u


def derive_event_id(item):
    """Composite id: normalized host + normalized title + start date. Falls
    back to host + title only when start date is unknown or unparseable;
    date-less ids are weaker (two differently-dated instances of the same
    recurring hackathon name and host would collide) but there is nothing
    better available. Returns None only if both host and title are empty."""
    norm_title = _normalize_title(item.get("title", ""))
    norm_host = _normalize_host(item.get("host", ""))
    start = item.get("event_start")

    parts = [p for p in (norm_host, norm_title) if p]
    if not parts:
        return None
    if start:
        parts.append(start)
    return _slugify(" ".join(parts))


def _new_record(event_id, url, today_str, item):
    return {
        "event_id": event_id,
        "urls": [url],
        "first_seen": today_str,
        "last_shown": today_str,
        "status": "seen",
        "resurfaced": False,
        "event_start": item.get("event_start"),
        "event_end": item.get("event_end"),
    }


def _should_show(record, item_event_start, today_dt):
    """Decide whether an already-seen event should be shown again this run.

    With a known event_start (from the record, or freshly parsed this run if
    the record did not have one yet): stay suppressed until within
    RESURFACE_WINDOW_DAYS of the start, resurface exactly once inside that
    window, then stay suppressed for good once the start date has passed (a
    lapsed event does not resurface again). The one-time resurface is
    enforced with the record's own "resurfaced" flag, not by assuming the
    upstream API will eventually stop returning the event.

    With no parseable start date at all, fall back to the original fixed
    CACHE_TTL_DAYS-since-last-shown behavior.

    Returns (show, new_status, new_resurfaced).
    """
    event_start_str = record.get("event_start") or item_event_start
    event_start = None
    if event_start_str:
        try:
            event_start = datetime.strptime(event_start_str, "%Y-%m-%d")
        except ValueError:
            event_start = None

    if event_start is not None:
        if today_dt.date() > event_start.date():
            return False, "lapsed", record.get("resurfaced", False)
        days_until_start = (event_start.date() - today_dt.date()).days
        if days_until_start <= RESURFACE_WINDOW_DAYS and not record.get("resurfaced", False):
            return True, "resurfaced", True
        return False, record.get("status", "seen"), record.get("resurfaced", False)

    last_shown_str = record.get("last_shown") or record.get("first_seen")
    try:
        last_shown = datetime.strptime(last_shown_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        last_shown = datetime.min
    if (today_dt - last_shown).days >= CACHE_TTL_DAYS:
        return True, "seen", record.get("resurfaced", False)
    return False, record.get("status", "seen"), record.get("resurfaced", False)


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _parse_devpost_date(submission_period_dates):
    """Best-effort parse of Devpost's human date range into YYYY-MM-DD start
    date, for display. Returns "Unknown" on failure (kept exactly as before;
    see _parse_devpost_date_range for the None-fallback version used to
    populate event_start/event_end for the cache)."""
    if not submission_period_dates:
        return "Unknown"
    try:
        parts = submission_period_dates.split(" - ")
        if len(parts) != 2:
            return "Unknown"
        first, last = parts[0].strip(), parts[1].strip()
        year_match = re.search(r"(\d{4})$", last)
        if not year_match:
            return "Unknown"
        year = year_match.group(1)
        if not re.search(r"\d{4}$", first):
            first = f"{first}, {year}"
        dt = datetime.strptime(first, "%b %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "Unknown"


def _parse_devpost_date_range(submission_period_dates):
    """Best-effort parse into (event_start, event_end) as YYYY-MM-DD or None
    each. Separate from _parse_devpost_date: this returns None rather than
    "Unknown" so the cache's date-aware resurface logic can tell "no date"
    apart from a display placeholder string."""
    if not submission_period_dates:
        return None, None
    try:
        parts = submission_period_dates.split(" - ")
        if len(parts) != 2:
            return None, None
        first, last = parts[0].strip(), parts[1].strip()
        year_match = re.search(r"(\d{4})$", last)
        if not year_match:
            return None, None
        year = year_match.group(1)
        first_full = first if re.search(r"\d{4}$", first) else f"{first}, {year}"
        start_dt = datetime.strptime(first_full, "%b %d, %Y")

        # `last` can omit the month when it matches `first`'s, e.g.
        # "Jul 18 - 19, 2026" (the end is "19, 2026", month borrowed from "Jul 18").
        if re.match(r"^[A-Za-z]{3}", last):
            last_full = last
        else:
            month = first.split()[0]
            last_full = f"{month} {last}"
        end_dt = datetime.strptime(last_full, "%b %d, %Y")

        return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    except Exception:
        return None, None


def normalise_devpost(item):
    title = item.get("title") or "Unknown"
    url = _canonicalize_url((item.get("url") or "").strip())
    themes = [t.get("name", "") for t in (item.get("themes") or []) if t.get("name")]
    displayed_location = item.get("displayed_location") or {}
    location = displayed_location.get("location") or "Unknown"
    mode = "online" if location == "Online" else "in-person"
    host = item.get("organization_name") or "Unknown"
    dates_raw = item.get("submission_period_dates") or ""
    published = _parse_devpost_date(dates_raw)
    event_start, event_end = _parse_devpost_date_range(dates_raw)
    prize = _strip_html(item.get("prize_amount") or "")
    time_left = item.get("time_left_to_submission") or ""

    summary_parts = [title]
    if themes:
        summary_parts.append("Themes: " + ", ".join(themes))
    if time_left:
        summary_parts.append(time_left)
    summary = " | ".join(summary_parts)[:500]

    return {
        "source": "Devpost",
        "title": title,
        "url": url,
        "summary": summary,
        "published": published,
        "location": location,
        "mode": mode,
        "host": host,
        "dates": dates_raw,
        "prize": prize,
        "themes": themes,
        "event_start": event_start,
        "event_end": event_end,
    }


def _to_ist(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(IST)
    except Exception:
        return None


def _format_human_date(date_str):
    """A "YYYY-MM-DD" date string to "Mon DD, YYYY" for the "dates" display
    field, or the raw string back if unparseable. Shared by the Luma and
    Cerebral Valley normalisers, whose "dates" field is built from plain
    YYYY-MM-DD parts rather than a pre-formatted upstream string."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return date_str


def normalise_devfolio(src):
    name = src.get("name") or "Unknown"
    tagline = src.get("tagline") or ""
    if tagline and tagline.lower() not in name.lower():
        title = f"{name} ({tagline})"
    else:
        title = name

    slug = src.get("slug") or ""
    url = _canonicalize_url(f"https://{slug}.devfolio.co/" if slug else "")

    desc = src.get("desc") or tagline or ""
    summary = desc.strip()[:500]

    starts_ist = _to_ist(src.get("starts_at"))
    ends_ist = _to_ist(src.get("ends_at"))
    published = starts_ist.strftime("%Y-%m-%d") if starts_ist else "Unknown"
    event_start = starts_ist.strftime("%Y-%m-%d") if starts_ist else None
    event_end = ends_ist.strftime("%Y-%m-%d") if ends_ist else None
    if starts_ist and ends_ist:
        dates = f"{starts_ist.strftime('%b %d, %Y')} to {ends_ist.strftime('%b %d, %Y')}"
    elif starts_ist:
        dates = starts_ist.strftime("%b %d, %Y")
    else:
        dates = ""

    is_online = bool(src.get("is_online"))
    city = src.get("city")
    country = src.get("country")
    loc_field = src.get("location")
    if city:
        location = f"{city}, {country}" if country else city
    elif loc_field:
        location = loc_field
    elif is_online:
        location = "Online"
    else:
        location = "Unknown"
    mode = "online" if is_online else "in-person"

    host = src.get("hosted_by")
    if not host:
        sponsor_tiers = src.get("sponsor_tiers") or []
        if sponsor_tiers:
            sponsors = sponsor_tiers[0].get("sponsors") or []
            if sponsors:
                host = sponsors[0].get("name")
    host = host or "Unknown"

    prizes = src.get("prizes") or []
    prize = ", ".join(p.get("name", "") for p in prizes if p.get("name"))

    themes = [t.get("name", "") for t in (src.get("themes") or []) if t.get("name")]

    return {
        "source": "Devfolio",
        "title": title,
        "url": url,
        "summary": summary,
        "published": published,
        "location": location,
        "mode": mode,
        "host": host,
        "dates": dates,
        "prize": prize,
        "themes": themes,
        "event_start": event_start,
        "event_end": event_end,
    }


def normalise_luma(entry):
    """entry is one item from the discover feed's "entries" list: the outer
    envelope with "event", "calendar", and "hosts" keys, not just the inner
    event dict, since host derivation needs the calendar and hosts too."""
    ev = entry.get("event") or {}
    title = ev.get("name") or "Unknown"

    slug = ev.get("url") or ""
    url = _canonicalize_url(f"https://luma.com/{slug}" if slug else "")

    geo = ev.get("geo_address_info") or {}
    location_type = ev.get("location_type")
    if geo.get("city_state"):
        location = geo["city_state"]
    elif geo.get("city"):
        location = geo["city"]
    elif location_type == "online":
        location = "Online"
    else:
        location = "Unknown"
    mode = "online" if location_type == "online" else "in-person"

    calendar = entry.get("calendar") or {}
    cal_name = calendar.get("name")
    hosts = entry.get("hosts") or []
    if cal_name and cal_name != "Personal":
        host = cal_name
    elif hosts and hosts[0].get("name"):
        host = hosts[0]["name"]
    else:
        host = "Unknown"

    start_ist = _to_ist(ev.get("start_at"))
    end_ist = _to_ist(ev.get("end_at"))
    published = start_ist.strftime("%Y-%m-%d") if start_ist else "Unknown"
    event_start = start_ist.strftime("%Y-%m-%d") if start_ist else None
    event_end = end_ist.strftime("%Y-%m-%d") if end_ist else None
    if start_ist and end_ist:
        dates = f"{start_ist.strftime('%b %d, %Y')} to {end_ist.strftime('%b %d, %Y')}"
    elif start_ist:
        dates = start_ist.strftime("%b %d, %Y")
    else:
        dates = ""

    host_names = ", ".join(h.get("name", "") for h in hosts if h.get("name"))
    summary_parts = [title]
    if host_names:
        summary_parts.append(host_names)
    if location and location != "Unknown":
        summary_parts.append(location)
    summary = " | ".join(summary_parts)[:500]

    return {
        "source": "Luma",
        "title": title,
        "url": url,
        "summary": summary,
        "published": published,
        "location": location,
        "mode": mode,
        "host": host,
        "dates": dates,
        "prize": "",
        "themes": [],
        "event_start": event_start,
        "event_end": event_end,
    }


def fetch_devpost():
    """Returns (items, error). error is None on success."""
    items = []
    try:
        for page in (1, 2):
            resp = requests.get(
                DEVPOST_URL,
                params={
                    "status[]": ["upcoming", "open"],
                    "themes[]": "Machine Learning/AI",
                    "per_page": 40,
                    "page": page,
                },
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            hackathons = data.get("hackathons", [])
            if page == 1:
                total_count = (data.get("meta") or {}).get("total_count", 0)
                if total_count > 80:
                    print(f"  WARNING: Devpost total_count={total_count} exceeds 2-page coverage (80); some events will be missed this run.")
            for h in hackathons:
                try:
                    items.append(normalise_devpost(h))
                except Exception:
                    continue
            if len(hackathons) < 40:
                break
        return items, None
    except Exception as e:
        print(f"  WARNING: Devpost fetch error: {e}")
        return [], str(e)


def fetch_devfolio():
    """Returns (items, error). error is None on success."""
    items = []
    seen_uuids = set()
    try:
        for body in (
            {"type": "application_open", "from": 0, "size": 50},
            {"type": "upcoming", "from": 0, "size": 50},
        ):
            resp = requests.post(DEVFOLIO_URL, json=body, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            hits = ((data.get("hits") or {}).get("hits")) or []
            for h in hits:
                src = h.get("_source") or {}
                uuid = src.get("uuid")
                if uuid:
                    if uuid in seen_uuids:
                        continue
                    seen_uuids.add(uuid)
                try:
                    items.append(normalise_devfolio(src))
                except Exception:
                    continue
        return items, None
    except Exception as e:
        print(f"  WARNING: Devfolio fetch error: {e}")
        return [], str(e)


def fetch_luma():
    """Returns (items, error). error is None on success.

    Bengaluru place feed only. The cat-ai category feed found during recon
    (docs/V2-SOURCING-PLAN.md) is geo-personalised by requesting IP and was
    judged not worth the added complexity for this build; see LEARNINGS.md.
    """
    items = []
    seen_ids = set()
    try:
        cursor = None
        pages_fetched = 0
        while True:
            params = {
                "discover_place_api_id": LUMA_PLACE_BENGALURU,
                "pagination_limit": 50,
            }
            if cursor:
                params["pagination_cursor"] = cursor
            resp = requests.get(LUMA_API_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("entries") or []
            for entry in entries:
                api_id = (entry.get("event") or {}).get("api_id")
                if api_id:
                    if api_id in seen_ids:
                        continue
                    seen_ids.add(api_id)
                if (entry.get("event") or {}).get("visibility") not in (None, "public"):
                    continue
                try:
                    items.append(normalise_luma(entry))
                except Exception:
                    continue
            pages_fetched += 1
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor or pages_fetched >= 5:
                break
            time.sleep(SOURCE_REQUEST_DELAY_S)
        return items, None
    except Exception as e:
        print(f"  WARNING: Luma fetch error: {e}")
        return [], str(e)


SOURCES = [
    {"name": "Devpost", "fetch": fetch_devpost},
    {"name": "Devfolio", "fetch": fetch_devfolio},
]
if ENABLE_CV_SOURCE:
    SOURCES.append({"name": "Cerebral Valley", "fetch": fetch_cerebralvalley})
SOURCES.append({"name": "Luma", "fetch": fetch_luma})


def fetch_events(dry_run=False):
    """Returns (items, source_health).

    source_health = {"Devpost": {"count": N, "error": None or str}, ...}
    """
    cache = {} if dry_run else load_cache()
    today_dt = datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")

    url_index = {}
    for eid, record in cache.items():
        for u in record.get("urls") or []:
            url_index[u] = eid

    all_items = []
    source_health = {}
    updates = {}

    for source in SOURCES:
        name = source["name"]
        try:
            raw_items, error = source["fetch"]()
        except Exception as e:
            raw_items, error = [], str(e)

        if error:
            source_health[name] = {"count": 0, "error": error}
            continue

        fresh = []
        for item in raw_items:
            url = item.get("url")
            if not url:
                continue

            event_id = url_index.get(url) or derive_event_id(item) or _legacy_event_id(url)
            item["event_id"] = event_id
            existing = updates.get(event_id) or cache.get(event_id)

            if existing is None:
                fresh.append(item)
                updates[event_id] = _new_record(event_id, url, today_str, item)
                url_index[url] = event_id
                continue

            urls = list(existing.get("urls") or [])
            if url not in urls:
                urls.append(url)

            show, new_status, new_resurfaced = _should_show(existing, item.get("event_start"), today_dt)

            updates[event_id] = {
                "event_id": event_id,
                "urls": urls,
                "first_seen": existing.get("first_seen", today_str),
                "last_shown": today_str if show else existing.get("last_shown", today_str),
                "status": new_status,
                "resurfaced": new_resurfaced,
                "event_start": existing.get("event_start") or item.get("event_start"),
                "event_end": existing.get("event_end") or item.get("event_end"),
            }
            url_index[url] = event_id

            if show:
                fresh.append(item)

        source_health[name] = {"count": len(fresh), "error": None}
        all_items.extend(fresh)

    if not dry_run:
        merged = {**cache, **updates}
        save_cache(merged)

    return all_items, source_health


if __name__ == "__main__":
    events, health = fetch_events(dry_run=True)
    print("Source health:")
    for name, info in health.items():
        print(f"  {name}: {info}")
    print(f"\nTotal fresh items: {len(events)}")
    for item in events[:2]:
        print(json.dumps(item, indent=2))
