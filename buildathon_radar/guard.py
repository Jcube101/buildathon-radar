MIN_PICK_SCORE = 35  # the rubric's own floor: anything below is meant to be excluded


def validate_picks(picks, items):
    """Programmatic anti-hallucination check.

    Every pick's URL must exact-match (trailing-slash tolerant) a URL in the
    fetched input set. Non-matches are dropped rather than aborting the run.
    Returns (valid_picks, dropped_picks). Each valid pick is enriched with
    pick["item"], the matched source item, which the digest renderer uses
    for every factual field.

    Two more checks, both seen live: Claude can return the same event twice
    (a 2026-11-01 dry run repeated a real Devpost URL as a score-0
    "placeholder" pick), and can include picks below the rubric's 35 floor.
    Only the highest-scored pick per event is kept, and below-floor picks are
    skipped. Neither counts as a dropped (unrecognised URL) pick, since the
    URL itself is real.
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
        try:
            score = int(pick.get("score"))
        except (TypeError, ValueError):
            score = 0
        if score < MIN_PICK_SCORE:
            print(f"  WARNING: Guard skipped below-floor pick (score {score}): {url}")
            continue
        enriched = dict(pick)
        enriched["item"] = matched
        valid_picks.append(enriched)

    # One pick per event, keeping the highest score; order otherwise preserved.
    best = {}
    for pick in valid_picks:
        key = pick["item"]["url"]
        if key not in best or pick["score"] > best[key]["score"]:
            best[key] = pick
    deduped = [p for p in valid_picks if best[p["item"]["url"]] is p]
    if len(deduped) < len(valid_picks):
        print(f"  WARNING: Guard removed {len(valid_picks) - len(deduped)} duplicate pick(s)")

    return deduped, dropped_picks
