"""Jev (TypeSafe AI) pre-filter that runs ahead of the claude-sonnet-5 call.

This is a cost/quality pre-filter, never a correctness-critical step. Every
failure path in here fails OPEN: if Jev is unreachable, rate limited, slow,
misconfigured, or returns something unexpected, the affected item is passed
through to Claude exactly as it would have been without triage. Triage can
only ever *reduce* what reaches Claude when it has a confident answer.

Gating is deliberately narrow: only `category` gates, and only for categories
that an existing hard rule in agent.py already rejects outright. Every other
answer is recorded for calibration and gates nothing.

`fit_score` deliberately does NOT gate. A preview over a 120-item live crop
put 59 items within 0.35 of a 2.0 threshold, with 25 of 30 Devpost listings
squeezed into the 1.50-1.75 band: modern Devpost hackathons really are all
somewhat AI-flavoured, so a cut there would be close to arbitrary. It is
logged instead, so a threshold can later be set from real data.

Two questions from the original plan are intentionally absent:

  * `has_real_prize` is asked only when the listing actually carries prize
    text, and never gates. normalise_luma and normalise_cerebralvalley both
    hardcode `"prize": ""`, so gating on it would have dropped ~38% of the
    weekly crop (all Luma, all Cerebral Valley) for lacking a field the
    fetcher never populates.
  * `still_open` is not asked at all. `event_start`/`event_end` are already
    parsed ISO dates on ~92% of items, so `_is_over` answers it exactly in
    code. Jev has no calendar awareness; asking it to do date math would be
    strictly worse than a date comparison we can already make for free.

Every verdict is written to the `triage_log` table in tracker.db so the
thresholds can be evaluated against real data before anything is tightened.
"""

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from dotenv import load_dotenv

from buildathon_radar.tracker_store import DB_FILE, _now_ist

load_dotenv()

# Pinned deliberately. The SDK's own default is "jev-latest" (see
# typesafe_sdk.constants.DEFAULT_MODEL), which would let triage behaviour
# shift under us without a code change.
JEV_MODEL = "jev-1.13.0"

# Off by default. This must stay off until a preview run has been eyeballed;
# flipping it needs no redeploy, only an .env edit and a service restart.
ENABLE_JEV_TRIAGE = os.getenv("ENABLE_JEV_TRIAGE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Categories that gate. `student_college` mirrors exclusion 1 in agent.py's
# rubric, which already rejects university, college, student-branch and
# student-chapter events outright regardless of theme, location or prize. So
# this drops only listings Claude is required to throw away anyway: the
# deterministic rule is the ground truth, and Jev is just reaching it sooner.
# In the preview crop this was 37 of 120 listings (~31%).
DROP_CATEGORIES = {"student_college"}

# Only drop on a confident classification. ChoiceAnswer.confidence spreads
# across 8 categories, so a ~0.5 reading is close to a coin flip between two
# of them and is not a safe basis for removing a listing before Claude sees
# it. Below this floor the item is kept, which is the fail-open direction.
# TODO(job): 0.7 is a judgement call, not a measured value. The kept-but-
# -flagged cases are in triage_log with their confidences; revisit once a few
# real runs have accumulated.
MIN_DROP_CONFIDENCE = 0.7

# Not a gate. Score answers are 0-based across the ordered level list, so 2.0
# would be "Good fit"; retained as the reference point the preview script
# uses for its counterfactual and borderline-band reporting.
MIN_FIT_SCORE = 2.0

# Concurrency for the per-item calls. There is no batch endpoint, so a weekly
# crop of ~35 items is ~35 requests. TypeSafe does not publish numeric rate
# limits, so this stays low; 429s are handled by RetryPolicy's retry-after.
MAX_WORKERS = 4

FIT_LEVELS = [
    "No overlap - not about software, AI, or building anything technical",
    "Tangential - software or tech adjacent, but not AI agents, LLM products, or applied GenAI",
    "Good fit - meaningfully involves AI, LLMs, or building real software products",
    "Strong fit - directly about AI agents, LLM-powered products, or applied GenAI",
]

# Criteria derived from the titles actually present in cache.json, not from a
# generic taxonomy. The two dominant noise classes in the real crop are US
# college hackathons (hackmty, warriorhacks, hackwashu, rutgers x elastic) and
# non-build community events (book clubs, magazine launches, pub quizzes), so
# both get their own bucket rather than being smeared into "other".
CATEGORY_CRITERIA = {
    "ai_agents_llm": "Centred on AI agents, LLM-powered products, or applied GenAI.",
    "ai_other": "AI or ML themed, but not about agents or LLM product building (e.g. classical ML, research, chip-level AI).",
    "student_college": "Run by or for a university, college, student branch, or student chapter.",
    "general_swe": "A general software or coding hackathon with no particular AI focus.",
    "fintech": "Centred on fintech, payments, banking, or web3.",
    "hardware_iot": "Centred on hardware, embedded systems, robotics, or IoT.",
    "community_social": "A meetup, talk, book club, launch party, quiz, or social gathering rather than a build event.",
    "other": "None of the above.",
}

TRIAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS triage_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at              TEXT NOT NULL,
    event_id            TEXT,
    url                 TEXT NOT NULL,
    title               TEXT,
    source              TEXT,
    model               TEXT,
    category            TEXT,
    category_confidence REAL,
    fit_score           REAL,
    fit_confidence      REAL,
    is_remote           REAL,
    has_real_prize      REAL,
    is_over             INTEGER,
    passed              INTEGER NOT NULL,
    reason              TEXT NOT NULL,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_triage_run_at ON triage_log(run_at);
"""


def _build_questions(item):
    """Questions for one listing. has_real_prize is only asked when there is
    prize text to judge; asking it of a Luma item would burn a question on a
    field the fetcher hardcodes to ""."""
    from typesafe_sdk import Choice, Noul, Score

    questions = {
        "category": Choice(
            instructions=(
                "Classify what kind of event this listing is. Judge only from "
                "the fields given, and prefer 'other' over guessing."
            ),
            criteria=CATEGORY_CRITERIA,
        ),
        "fit_score": Score(
            instructions=(
                "The reader is an AI product manager in Bengaluru, India. He "
                "cares about AI agents, LLM tooling and LLM-powered products, "
                "applied GenAI, agentic systems, homelab and self-hosted "
                "builds, and RevOps-adjacent automation. How well does this "
                "event match those interests? Judge the subject matter only; "
                "ignore location, prize size, and prestige."
            ),
            criteria=FIT_LEVELS,
        ),
        "is_remote": Noul(
            instructions=(
                "Is this event remote, online, or virtual, meaning it can be "
                "attended without travelling to a venue?"
            ),
        ),
    }

    if (item.get("prize") or "").strip():
        questions["has_real_prize"] = Noul(
            instructions=(
                "Does the stated prize include genuine cash, credits, or "
                "funding, as opposed to only swag, merchandise, or "
                "certificates?"
            ),
        )

    return questions


def _build_state(item):
    """State passed to Jev. Field names follow the normalised item dict from
    fetcher.py: `summary` (not description) and `themes` (not tags)."""
    return {
        "title": item.get("title") or "",
        "summary": item.get("summary") or "",
        "themes": item.get("themes") or [],
        "prize": item.get("prize") or "",
        "dates": item.get("dates") or "",
        "source": item.get("source") or "",
        "location": item.get("location") or "",
        "mode": item.get("mode") or "",
        "host": item.get("host") or "",
    }


def _parse_iso(value):
    if not value or value == "Unknown":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _is_over(item, today=None):
    """Exact, code-side replacement for the `still_open` question.

    Returns True only when the listing definitively ended before today.
    Unknown or unparseable dates return False (treated as still open), which
    keeps the item in the pipeline.
    """
    today = today or date.today()
    end = _parse_iso(item.get("event_end")) or _parse_iso(item.get("event_start"))
    if end is None:
        return False
    return end < today


def _make_client():
    """None when triage cannot run, which the caller treats as fail-open."""
    api_key = os.getenv("TYPESAFE_API_KEY")
    if not api_key:
        print("  WARNING: TYPESAFE_API_KEY unset; skipping Jev triage (fail-open)")
        return None
    try:
        from typesafe_sdk import RetryPolicy, TypeSafeClient

        return TypeSafeClient(
            api_key=api_key,
            model=JEV_MODEL,
            retry=RetryPolicy(max_retries=2, respect_retry_after=True, timeout=20.0),
        )
    except Exception as e:
        print(f"  WARNING: could not build TypeSafe client: {e} (fail-open)")
        return None


def _blank_verdict(item, reason, error=None):
    """A pass-through verdict. Used for every failure and skip path."""
    return {
        "item": item,
        "url": item.get("url", ""),
        "title": item.get("title", ""),
        "source": item.get("source", ""),
        "model": None,
        "category": None,
        "category_confidence": None,
        "fit_score": None,
        "fit_confidence": None,
        "is_remote": None,
        "has_real_prize": None,
        "is_over": _is_over(item),
        "passed": True,
        "reason": reason,
        "error": error,
    }


def triage_item(client, item):
    """Triage one listing. Never raises: any failure returns a passing verdict."""
    if client is None:
        return _blank_verdict(item, "skipped: no client")

    try:
        response = client.system_one(_build_state(item), _build_questions(item))
    except Exception as e:
        # Deliberately broad. Rate limits, timeouts, connection errors, auth
        # failures and validation errors all mean the same thing here: we
        # learned nothing, so the item goes to Claude untouched.
        return _blank_verdict(
            item, f"fail-open: {type(e).__name__}", error=str(e)[:500]
        )

    try:
        answers = response.answers
        category = answers["category"]
        fit = answers["fit_score"]
        remote = answers.get("is_remote")
        prize = answers.get("has_real_prize")

        fit_score = float(fit.score)
        name = category.choice
        confidence = float(category.confidence)

        if name in DROP_CATEGORIES and confidence >= MIN_DROP_CONFIDENCE:
            passed = False
            reason = f"dropped: category {name} (confidence {confidence:.2f})"
        elif name in DROP_CATEGORIES:
            # Right category to drop, not enough certainty to act on it.
            passed = True
            reason = (
                f"kept: category {name} but confidence {confidence:.2f}"
                f" < {MIN_DROP_CONFIDENCE}"
            )
        else:
            passed = True
            reason = f"kept: category {name}"

        return {
            "item": item,
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "model": getattr(response, "model", None),
            "category": name,
            "category_confidence": confidence,
            "fit_score": fit_score,
            "fit_confidence": float(fit.confidence),
            "is_remote": float(remote.noul) if remote is not None else None,
            "has_real_prize": float(prize.noul) if prize is not None else None,
            "is_over": _is_over(item),
            "passed": passed,
            "reason": reason,
            "error": None,
        }
    except Exception as e:
        return _blank_verdict(
            item, f"fail-open: unreadable response ({type(e).__name__})", error=str(e)[:500]
        )


def log_verdicts(verdicts, db_path=None, run_at=None):
    """Append verdicts to triage_log. Logging failures never break a run."""
    if not verdicts:
        return
    run_at = run_at or _now_ist()
    try:
        from buildathon_radar.fetcher import derive_event_id

        conn = sqlite3.connect(db_path or DB_FILE, timeout=5)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(TRIAGE_SCHEMA)
        rows = []
        for v in verdicts:
            try:
                event_id = derive_event_id(v["item"])
            except Exception:
                event_id = None
            rows.append(
                (
                    run_at,
                    event_id,
                    v["url"],
                    v["title"],
                    v["source"],
                    v["model"],
                    v["category"],
                    v["category_confidence"],
                    v["fit_score"],
                    v["fit_confidence"],
                    v["is_remote"],
                    v["has_real_prize"],
                    int(bool(v["is_over"])),
                    int(bool(v["passed"])),
                    v["reason"],
                    v["error"],
                )
            )
        conn.executemany(
            """INSERT INTO triage_log (
                   run_at, event_id, url, title, source, model, category,
                   category_confidence, fit_score, fit_confidence, is_remote,
                   has_real_prize, is_over, passed, reason, error
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  WARNING: could not write triage_log: {e}")


def triage_items(items, enabled=None, db_path=None, log=True):
    """Pre-filter the normalised item list ahead of the Claude call.

    Returns (survivors, verdicts). When triage is disabled or wholly
    unavailable, survivors is `items` unchanged. Fails open per item.
    """
    enabled = ENABLE_JEV_TRIAGE if enabled is None else enabled
    if not enabled or not items:
        return items, []

    client = _make_client()
    if client is None:
        return items, []

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            verdicts = list(pool.map(lambda it: triage_item(client, it), items))
    except Exception as e:
        print(f"  WARNING: Jev triage failed wholesale: {e} (fail-open)")
        return items, []

    if log:
        log_verdicts(verdicts, db_path=db_path)

    survivors = [v["item"] for v in verdicts if v["passed"]]
    scored = sum(1 for v in verdicts if v["fit_score"] is not None)
    failed = len(verdicts) - scored
    print(
        f"  Jev triage ({JEV_MODEL}): {len(survivors)}/{len(items)} passed to Claude"
        f" ({scored} scored, {failed} failed open)"
    )
    return survivors, verdicts
