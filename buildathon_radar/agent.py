import json
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8000

ALLOWED_TIERS = {"must_see", "worth_a_look", "radar"}

PERSONA = """You are the filtering engine for Buildathon Radar, a personal AI agent built for an AI product manager based in Bengaluru, India. He builds with Claude and Gemini, cares deeply about AI agents, LLM tooling, and on-device AI, and wants to attend high-signal hackathons, buildathons, and builder showcases.

He has repeatedly missed exactly two kinds of event because discovery was left to chance: prestigious AI-lab or big-tech events held in Bengaluru, and India-wide flagship AI events. He has also personally won a notable global online buildathon before, so prestigious online events matter to him too and must not be buried just for being remote. Your job is to make sure nothing in these classes slips past him again."""

EXCLUSIONS = """Apply these hard exclusions before you score anything. If any of these apply to an event, exclude it completely: do not place it in any tier, and count it toward skipped_count instead. A high theme, host, or prize score never overrides an exclusion below.

1. Student and college-run events. Exclude any event where the host, organizer, or primary sponsor is a university, college, student branch, or student chapter (for example, "IEEE Student Branch," a student chapter of a professional society, or a college tech club), or that is otherwise clearly a student-run college hackathon. This applies regardless of theme, location, or prize money, even for an event that is otherwise well matched and local. Two concrete examples that must be excluded under this rule: "Build with Gemma (Bengaluru AI Sprint)," hosted by IEEE Computer Society, a student-facing chapter, and "Hack On Hills 8.0," a student-run college hackathon.

2. Platforms that are impractical to access from India. Exclude an event if participating requires signing up for or obtaining access to a cloud platform or account that is known to be difficult to get from India. Concrete example: Alibaba Cloud and Qwen Cloud accounts are difficult to obtain from India, so "Global AI Hackathon Series with Qwen Cloud" and similar Alibaba Cloud or Qwen Cloud gated events must be excluded on this basis alone, even if the AI theme otherwise fits.

3. Chip-level, embedded, or hardware AI optimization events. Exclude an event that is fundamentally about hardware, chip, silicon, or embedded-systems AI optimization rather than software, AI agents, LLM-powered products, or applied GenAI, even if it uses the word "AI" prominently. Concrete example: "Arm Create: AI Optimization Challenge" is a chip-level hardware optimization challenge, not a software or product AI event, and must be excluded. This exclusion does NOT cover on-device AI as a software product feature (for example, a hackathon about running a GenAI model as a consumer feature on a phone); that remains in scope under theme fit below. The exclusion is specifically for hardware and silicon engineering challenges."""

RUBRIC = """Score every surviving event (after the exclusions above) from 0 to 100 as the sum of four components. Be honest and specific, do not round up out of enthusiasm.

1. Theme fit (0 to 35): the reader's focus is software, AI agents, LLM-powered products, and applied GenAI, including on-device AI as a software product feature. AI agents, LLMs, Claude, Gemini, or GenAI as the core software theme scores 28 to 35. AI as one track among several scores 15 to 25. Adjacent tech (fintech, web3, IoT) with only a light AI angle scores 5 to 15. No real AI relevance scores 0, and the event should be excluded entirely.

2. Geography (0 to 30): the strong local boost is reserved for corporate or company-hosted in-person Bengaluru events, meaning a company, startup, or AI lab is running or clearly headlining the event, not a student or college co-host (student and college-hosted events are excluded outright under exclusion 1 above, regardless of geography). A corporate-hosted in-person Bengaluru event scores 26 to 30. A corporate-hosted in-person event elsewhere in India scores 14 to 22. Online and open to participants in India (this covers essentially all global online hackathons, since they accept entries worldwide) scores 8 to 14, unless excluded under exclusion 2 above for requiring an India-inaccessible platform. In-person outside India that is not travel-worthy scores 0 to 5. If location is unclear, score at most 8.

3. Host prestige (0 to 25): a major AI lab or big tech company (Anthropic, Google or DeepMind, OpenAI, Meta, Microsoft, an XPRIZE-tier organiser) scores 20 to 25. A major startup, unicorn, or large developer community (Razorpay, MLH tier) scores 12 to 19. An unknown or minor host scores 0 to 8.

4. Scale and signal (0 to 10): a large prize pool, a high registration count, a "managed by Devpost" badge, or verified Devfolio themes each support a score up to 10.

Important note on geography and prestige: theme fit plus host prestige plus scale and signal alone can total up to 70 points with zero geography points. This is intentional. A prestigious global online hackathon (run by a major AI lab or a notable sponsor, and not excluded under exclusion 2) must be able to reach the must_see tier purely on theme, host, and signal. Do not let a modest geography score suppress an event that has clearly earned its tier on the other three components. The geography score is a bonus for local corporate relevance, not a penalty gate on prestigious online events."""

TIERING = """Assign each scored event to a tier:
- must_see: score 70 or above.
- worth_a_look: score 50 to 69.
- radar: score 35 to 49. This tier typically holds notable global online events that did not reach must_see, plus solid but less exceptional local events.
- Below 35: exclude the event entirely and count it in skipped_count. Do not include it in picks.

Keep at most 12 picks in total. If more than 12 events qualify, keep only the 12 highest-scored.

Output only a single JSON object. No markdown code fences, no prose before or after it. The shape is exactly:

{
  "picks": [
    {
      "url": "<copied character for character from the event's URL line>",
      "title": "<the event's title>",
      "tier": "must_see",
      "score": 87,
      "scoring": {"theme": 33, "geo": 28, "host": 19, "signal": 7},
      "why": "One or two sentences on why this matters to the reader."
    }
  ],
  "skipped_count": 41,
  "week_note": "One sentence overview of the week's crop."
}"""

CONSTRAINTS = """CRITICAL CONSTRAINTS:
- Reason ONLY from the events listed in the user message. Do NOT draw on training knowledge.
- Do NOT invent events, hosts, locations, dates, or URLs not explicitly listed.
- Apply the hard exclusion rules before scoring anything; a high theme, host, or prize score never overrides an exclusion.
- Every "url" value MUST be copied character for character from an event's URL line.
  Any URL not present in the input will be programmatically discarded.
- If an event's data is too vague to score a component, score that component low. Never fill gaps by inference.
- Never reference events by their input number. Identify them only by title and url.
- Output raw JSON only: no code fences, no commentary before or after."""

SYSTEM_PROMPT = "\n\n".join([PERSONA, EXCLUSIONS, RUBRIC, TIERING, CONSTRAINTS])


def _format_items(items):
    formatted = ""
    for i, item in enumerate(items):
        themes_str = ", ".join(item.get("themes") or []) or "None listed"
        formatted += f"""
Event {i + 1}:
Source: {item['source']}
Title: {item['title']}
URL: {item['url']}
Host: {item['host']}
Location: {item['location']}
Mode: {item['mode']}
Dates: {item['dates']}
Prize: {item['prize'] or 'Not listed'}
Themes: {themes_str}
Summary: {item['summary']}
---
"""
    return formatted


def _clean_json_text(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json_response(text):
    cleaned = _clean_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def _validate_picks(parsed):
    picks = parsed.get("picks")
    if not isinstance(picks, list):
        return []

    valid_picks = []
    for p in picks:
        if not isinstance(p, dict):
            print(f"  WARNING: dropping non-dict pick: {p}")
            continue
        url = p.get("url")
        title = p.get("title")
        tier = p.get("tier")
        why = p.get("why")

        if not isinstance(url, str) or not url.strip():
            print(f"  WARNING: dropping pick with invalid url: {p}")
            continue
        if not isinstance(title, str) or not title.strip():
            print(f"  WARNING: dropping pick with invalid title: {p}")
            continue
        if tier not in ALLOWED_TIERS:
            print(f"  WARNING: dropping pick with invalid tier: {p}")
            continue
        try:
            score = int(p.get("score"))
        except (TypeError, ValueError):
            print(f"  WARNING: dropping pick with invalid score: {p}")
            continue
        if not isinstance(why, str):
            why = ""

        scoring = p.get("scoring")
        if not isinstance(scoring, dict):
            scoring = {}

        valid_picks.append(
            {
                "url": url.strip(),
                "title": title,
                "tier": tier,
                "score": score,
                "scoring": scoring,
                "why": why,
            }
        )
    return valid_picks


def _call_claude(user_message):
    # Extended thinking is disabled: this is a scoring/JSON task with no need
    # for visible chain-of-thought, and leaving it on caused claude-sonnet-5
    # to spend the entire token budget thinking and return no text at all
    # for larger event batches (confirmed live: 90 items, thinking on,
    # stop_reason=max_tokens, 4000/4000 thinking tokens, zero text blocks).
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": user_message}],
    )
    # response.content may include non-text blocks (e.g. a ThinkingBlock)
    # before the text block, so scan for the first block that has one.
    for block in response.content:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    raise RuntimeError("Claude response contained no text block")


def run_agent(items):
    """Takes the normalised item list, returns {"picks": [...], "skipped_count": int, "week_note": str}."""
    if not items:
        return {"picks": [], "skipped_count": 0, "week_note": "No new events found this week."}

    formatted = _format_items(items)
    user_message = (
        "Here are this week's events. Use ONLY these events. Score, tier, and "
        f"select per your rubric, and return the JSON object only.\n\n{formatted}"
    )

    text = _call_claude(user_message)
    parsed = _parse_json_response(text)

    if parsed is None:
        retry_message = (
            user_message
            + "\n\nYour previous output was not valid JSON. Return only the JSON object."
        )
        text = _call_claude(retry_message)
        parsed = _parse_json_response(text)

    if parsed is None:
        raise RuntimeError("agent returned unparseable output twice")

    picks = _validate_picks(parsed)

    skipped_count = parsed.get("skipped_count", 0)
    if not isinstance(skipped_count, int):
        skipped_count = 0

    week_note = parsed.get("week_note", "")
    if not isinstance(week_note, str):
        week_note = ""

    return {"picks": picks, "skipped_count": skipped_count, "week_note": week_note}
