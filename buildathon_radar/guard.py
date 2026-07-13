def validate_picks(picks, items):
    """Programmatic anti-hallucination check.

    Every pick's URL must exact-match (trailing-slash tolerant) a URL in the
    fetched input set. Non-matches are dropped rather than aborting the run.
    Returns (valid_picks, dropped_picks). Each valid pick is enriched with
    pick["item"], the matched source item, which the digest renderer uses
    for every factual field.
    """
    by_url = {item["url"]: item for item in items if item.get("url")}
    by_stripped_url = {
        item["url"].rstrip("/"): item for item in items if item.get("url")
    }

    valid_picks = []
    dropped_picks = []

    for pick in picks:
        url = pick.get("url", "")
        matched = by_url.get(url)
        if matched is None:
            stripped = url.strip().rstrip("/")
            matched = by_stripped_url.get(stripped)
        if matched is None:
            print(f"  WARNING: Guard dropped pick with unrecognised URL: {url}")
            dropped_picks.append(pick)
            continue
        enriched = dict(pick)
        enriched["item"] = matched
        valid_picks.append(enriched)

    return valid_picks, dropped_picks
