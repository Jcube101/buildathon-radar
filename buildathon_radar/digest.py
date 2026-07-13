import html as html_lib

TIER_ORDER = ["must_see", "worth_a_look", "radar"]

TIER_HEADERS = {
    "must_see": "## 🔥 Must-see",
    "worth_a_look": "## 👀 Worth a look",
    "radar": "## 📡 On the radar (online / global)",
}

TIER_LABELS = {
    "must_see": "🔥 Must-see",
    "worth_a_look": "👀 Worth a look",
    "radar": "📡 On the radar (online / global)",
}

FONT_STACK = "-apple-system, Roboto, 'Helvetica Neue', Arial, sans-serif"
WRAP = "word-break:break-word; overflow-wrap:break-word;"
TEAL_DARK = "#0f4c4c"
PAGE_BG = "#f6f4ef"
CARD_BG = "#ffffff"
WHY_TINT_BG = "#eaf3f1"
SCORE_BADGE_BG = "#0d9488"

TIER_COLORS = {
    "must_see": "#0d9488",
    "worth_a_look": "#5b8a8a",
    "radar": "#8fa6a6",
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


def _esc(value):
    return html_lib.escape(str(value or ""))


def _html_tier_header_row(tier):
    color = TIER_COLORS[tier]
    label = TIER_LABELS[tier]
    return f"""<tr>
<td style="background-color:{PAGE_BG}; padding:22px 24px 8px 24px; font-family:{FONT_STACK}; font-size:13px; font-weight:bold; letter-spacing:0.5px; color:{color}; {WRAP}">{_esc(label)}</td>
</tr>"""


def _html_card_row(pick, tier):
    """Every factual field comes from pick["item"] (the guard-matched source
    item), same rule as the markdown card. Only score and "why" come from
    Claude's output."""
    item = pick["item"]
    title = _esc(item["title"])
    url = _esc(item["url"])
    host = _esc(item["host"]) if item.get("host") and item["host"] != "Unknown" else _esc(item["source"])
    location = _esc(item["location"])
    mode = _esc(item["mode"]) if item.get("mode") and item["mode"] != "unknown" else ""
    dates = _esc(item["dates"] or item["published"])
    prize = _esc(item["prize"])
    source = _esc(item["source"])
    score = _esc(pick["score"])
    why = _esc(pick.get("why", ""))
    stripe_color = TIER_COLORS.get(tier, TIER_COLORS["radar"])

    meta_bits = [b for b in (host, location, mode) if b]
    meta_line = " &middot; ".join(meta_bits)

    dates_line = dates
    if prize:
        dates_line = f"{dates_line} &middot; Prize: {prize}" if dates_line else f"Prize: {prize}"

    why_row = ""
    if why:
        why_row = f"""<tr>
<td style="background-color:{CARD_BG}; padding:4px 0 0 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="background-color:{WHY_TINT_BG}; padding:10px 12px; font-family:{FONT_STACK}; font-size:13px; font-style:italic; color:#2e4243; {WRAP}">{why}</td>
</tr></table>
</td>
</tr>"""

    return f"""<tr>
<td style="background-color:{PAGE_BG}; padding:0 24px 14px 24px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{CARD_BG}; max-width:100%;">
<tr>
<td width="6" style="background-color:{stripe_color}; padding:0; font-size:0; line-height:0;">&nbsp;</td>
<td style="background-color:{CARD_BG}; padding:14px 18px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td style="background-color:{CARD_BG}; padding:0 0 4px 0;"><a href="{url}" style="font-family:{FONT_STACK}; font-size:17px; font-weight:bold; color:{TEAL_DARK}; text-decoration:none; {WRAP}">{title}</a></td></tr>
<tr><td style="background-color:{CARD_BG}; padding:0 0 4px 0; font-family:{FONT_STACK}; font-size:13px; color:#6b7b7b; {WRAP}">{meta_line}</td></tr>
<tr><td style="background-color:{CARD_BG}; padding:0 0 10px 0; font-family:{FONT_STACK}; font-size:13px; color:#6b7b7b; {WRAP}">{dates_line}</td></tr>
<tr><td style="background-color:{CARD_BG}; padding:0 0 4px 0;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="background-color:{SCORE_BADGE_BG}; padding:3px 9px;"><span style="font-family:{FONT_STACK}; font-size:12px; font-weight:bold; color:#ffffff;">{score}</span></td>
<td style="background-color:{CARD_BG}; padding:0 0 0 8px; font-family:{FONT_STACK}; font-size:12px; color:#8a9a9a; {WRAP}">via {source}</td>
</tr></table>
</td></tr>
{why_row}
</table>
</td>
</tr>
</table>
</td>
</tr>"""


def _html_footer_row(source_health, dropped):
    health_bits = []
    for name, info in source_health.items():
        esc_name = _esc(name)
        if info.get("error"):
            health_bits.append(f"{esc_name}: FAILED ({_esc(info['error'])})")
        elif info.get("count", 0) == 0:
            health_bits.append(f"{esc_name}: 0 new events")
        else:
            health_bits.append(f"{esc_name}: {info['count']} new events")
    health_line = " &middot; ".join(health_bits)

    integrity_row = ""
    if dropped:
        integrity_row = f"""<tr>
<td style="background-color:{PAGE_BG}; padding:6px 0 0 0; font-family:{FONT_STACK}; font-size:12px; color:#8a5a3a; {WRAP}">Integrity guard: {len(dropped)} pick(s) dropped because their URL was not in the fetched data.</td>
</tr>"""

    return f"""<tr>
<td style="background-color:{PAGE_BG}; padding:20px 24px 24px 24px; border-top:1px solid #d8d3c4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr>
<td style="background-color:{PAGE_BG}; padding:12px 0 0 0; font-family:{FONT_STACK}; font-size:12px; color:#7a8a8a; {WRAP}">Source health: {health_line}</td>
</tr>
{integrity_row}
<tr>
<td style="background-color:{PAGE_BG}; padding:14px 0 0 0; font-family:{FONT_STACK}; font-size:11px; color:#a3aba3; {WRAP}">Buildathon Radar scans Devpost and Devfolio weekly and emails you every Sunday.</td>
</tr>
</table>
</td>
</tr>"""


def build_html_digest(picks, dropped, source_health, week_note, date_range=None):
    """Gmail Android compatible HTML digest: table-based layout, all CSS
    inline, system font stack, no external assets, no JavaScript. Presentation
    only, same content rule as build_digest: every factual field comes from
    the matched source item, Claude only supplies score, tier, and why."""
    rows = []

    subtitle_html = (
        f'<div style="font-family:{FONT_STACK}; font-size:13px; color:#a9cccc; margin-top:4px; {WRAP}">{_esc(date_range)}</div>'
        if date_range
        else ""
    )
    rows.append(f"""<tr>
<td style="background-color:{TEAL_DARK}; padding:28px 24px 20px 24px;">
<div style="font-family:{FONT_STACK}; font-size:22px; font-weight:bold; color:#eaf6f4; {WRAP}">Buildathon Radar</div>
{subtitle_html}
</td>
</tr>""")

    if week_note:
        rows.append(f"""<tr>
<td style="background-color:{PAGE_BG}; padding:20px 24px 4px 24px; font-family:{FONT_STACK}; font-size:14px; font-style:italic; color:#3d4f4f; {WRAP}">{_esc(week_note)}</td>
</tr>""")

    if not picks:
        if source_health and all(
            info.get("error") for info in source_health.values()
        ):
            body_text = "All sources failed this run. No events could be fetched or scored."
        else:
            total_fetched = sum(info.get("count", 0) for info in source_health.values())
            body_text = f"Quiet week: {total_fetched} events were fetched and none cleared the relevance bar."
        rows.append(f"""<tr>
<td style="background-color:{PAGE_BG}; padding:16px 24px; font-family:{FONT_STACK}; font-size:14px; color:#3d4f4f; {WRAP}">{_esc(body_text)}</td>
</tr>""")
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
            rows.append(_html_tier_header_row(tier))
            for pick in tier_picks:
                rows.append(_html_card_row(pick, tier))

    rows.append(_html_footer_row(source_health, dropped))

    body = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Buildathon Radar</title>
</head>
<body style="margin:0; padding:0; background-color:{PAGE_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{PAGE_BG};">
<tr>
<td align="center" style="background-color:{PAGE_BG}; padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%; max-width:600px; background-color:{PAGE_BG};">
{body}
</table>
</td>
</tr>
</table>
</body>
</html>"""
