import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

CACHE_FILE = "cache.json"
CACHE_TTL_DAYS = 45

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) buildathon-radar/1.0",
    "Accept": "application/json",
}

DEVPOST_URL = "https://devpost.com/api/hackathons"
DEVFOLIO_URL = "https://api.devfolio.co/api/search/hackathons"

IST = timezone(timedelta(hours=5, minutes=30))


def load_cache():
    """Returns {url: date_first_seen} dict. Migrates old {"urls": [...]} format."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
            if "urls" in data:
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


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _parse_devpost_date(submission_period_dates):
    """Best-effort parse of Devpost's human date range into YYYY-MM-DD start date."""
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


def normalise_devpost(item):
    title = item.get("title") or "Unknown"
    url = (item.get("url") or "").strip()
    themes = [t.get("name", "") for t in (item.get("themes") or []) if t.get("name")]
    displayed_location = item.get("displayed_location") or {}
    location = displayed_location.get("location") or "Unknown"
    mode = "online" if location == "Online" else "in-person"
    host = item.get("organization_name") or "Unknown"
    dates_raw = item.get("submission_period_dates") or ""
    published = _parse_devpost_date(dates_raw)
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
    }


def _to_ist(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(IST)
    except Exception:
        return None


def normalise_devfolio(src):
    name = src.get("name") or "Unknown"
    tagline = src.get("tagline") or ""
    if tagline and tagline.lower() not in name.lower():
        title = f"{name} ({tagline})"
    else:
        title = name

    slug = src.get("slug") or ""
    url = f"https://{slug}.devfolio.co/" if slug else ""

    desc = src.get("desc") or tagline or ""
    summary = desc.strip()[:500]

    starts_ist = _to_ist(src.get("starts_at"))
    ends_ist = _to_ist(src.get("ends_at"))
    published = starts_ist.strftime("%Y-%m-%d") if starts_ist else "Unknown"
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


SOURCES = [
    {"name": "Devpost", "fetch": fetch_devpost},
    {"name": "Devfolio", "fetch": fetch_devfolio},
]


def fetch_events(dry_run=False):
    """Returns (items, source_health).

    source_health = {"Devpost": {"count": N, "error": None or str}, ...}
    """
    cache = {} if dry_run else load_cache()
    cutoff = datetime.now() - timedelta(days=CACHE_TTL_DAYS)

    all_items = []
    source_health = {}

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
            if url in cache:
                try:
                    seen_date = datetime.strptime(cache[url], "%Y-%m-%d")
                except ValueError:
                    seen_date = datetime.min
                if seen_date >= cutoff:
                    continue
            fresh.append(item)

        source_health[name] = {"count": len(fresh), "error": None}
        all_items.extend(fresh)

    if not dry_run:
        today = datetime.now().strftime("%Y-%m-%d")
        updated_cache = {**cache, **{item["url"]: today for item in all_items if item.get("url")}}
        save_cache(updated_cache)

    return all_items, source_health


if __name__ == "__main__":
    events, health = fetch_events(dry_run=True)
    print("Source health:")
    for name, info in health.items():
        print(f"  {name}: {info}")
    print(f"\nTotal fresh items: {len(events)}")
    for item in events[:2]:
        print(json.dumps(item, indent=2))
