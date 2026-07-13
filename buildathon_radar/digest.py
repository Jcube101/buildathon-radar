TIER_ORDER = ["must_see", "worth_a_look", "radar"]

TIER_HEADERS = {
    "must_see": "## 🔥 Must-see",
    "worth_a_look": "## 👀 Worth a look",
    "radar": "## 📡 On the radar (online / global)",
}


def _format_card(pick):
    """Every factual field comes from pick["item"] (the guard-matched source
    item). Only score and "why" come from Claude's output."""
    item = pick["item"]
    title = item["title"]
    url = item["url"]
    host = item["host"]
    location = item["location"]
    mode = item["mode"]
    dates = item["dates"] or item["published"]
    prize = item["prize"]
    source = item["source"]
    score = pick["score"]
    why = pick.get("why", "")

    header_bits = []
    if host and host != "Unknown":
        header_bits.append(f"**{host}**")
    else:
        header_bits.append(f"**{source}**")
    if location:
        header_bits.append(location)
    if mode and mode != "unknown":
        header_bits.append(mode)
    if dates:
        header_bits.append(dates)
    header_line = " · ".join(header_bits)

    detail_bits = []
    if prize:
        detail_bits.append(f"Prize: {prize}")
    detail_bits.append(f"via {source}")
    detail_bits.append(f"score {score}")
    detail_line = " · ".join(detail_bits)

    lines = [f"### [{title}]({url})", header_line, detail_line]
    if why:
        lines.append(f"> {why}")
    return "\n".join(lines)


def _format_health_footer(source_health, dropped):
    health_bits = []
    for name, info in source_health.items():
        if info.get("error"):
            health_bits.append(
                f"{name}: FAILED ({info['error']}) ⚠️ digest may be incomplete"
            )
        elif info.get("count", 0) == 0:
            health_bits.append(f"{name}: 0 new events ⚠️")
        else:
            health_bits.append(f"{name}: {info['count']} new events")

    lines = ["---", "**Source health:** " + " · ".join(health_bits)]

    if dropped:
        lines.append("")
        lines.append(
            f"**Integrity guard:** {len(dropped)} pick(s) dropped because their "
            "URL was not in the fetched data."
        )
    return "\n".join(lines)


def build_digest(picks, dropped, source_health, week_note):
    """Renders validated picks + source health into markdown. Code-owned:
    Claude never authors factual content, only score/tier/why per pick."""
    lines = []

    if week_note:
        lines.append(f"*{week_note}*")
        lines.append("")

    if not picks:
        if source_health and all(
            info.get("error") for info in source_health.values()
        ):
            lines.append(
                "All sources failed this run. No events could be fetched or scored."
            )
        else:
            total_fetched = sum(
                info.get("count", 0) for info in source_health.values()
            )
            lines.append(
                f"Quiet week: {total_fetched} events were fetched and none "
                "cleared the relevance bar."
            )
        lines.append("")
    else:
        by_tier = {tier: [] for tier in TIER_ORDER}
        for pick in picks:
            tier = pick.get("tier")
            if tier in by_tier:
                by_tier[tier].append(pick)

        for tier in TIER_ORDER:
            tier_picks = sorted(by_tier[tier], key=lambda p: p["score"], reverse=True)
            if not tier_picks:
                continue
            lines.append(TIER_HEADERS[tier])
            lines.append("")
            for pick in tier_picks:
                lines.append(_format_card(pick))
                lines.append("")

    lines.append(_format_health_footer(source_health, dropped))

    return "\n".join(lines)
