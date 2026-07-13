# CONTRIBUTING.md

Conventions for working on buildathon-radar, whether by hand or through
Claude Code.

## Documentation naming

All doc-set files at the repo root are UPPERCASE: `README.md`, `SPEC.md`,
`ROADMAP.md`, `LEARNINGS.md`, `CLAUDE.md`, `CONTRIBUTING.md`. Archived or
reference material that is not part of the active doc set lives in `docs/`.

Each file has one purpose:

- **README**: public overview. What this is, how to set it up and run it.
- **SPEC**: the tech stack, architecture, and data contracts. The
  get-up-to-speed reference for how the system actually works today.
- **ROADMAP**: forward-looking. Status of what shipped, and what comes next.
- **LEARNINGS**: accumulated gotchas, incidents, and the fixes that came out
  of them.
- **CLAUDE**: operational guide for Claude Code sessions working in this repo.
- **CONTRIBUTING**: this file.

## Prose style

No em dashes anywhere, in docs or in prose written by an assistant. Plain,
direct writing. Short sentences over long ones with several clauses.

## Workflow

Design and decisions are settled before code is written. A prompt to Claude
Code should carry both the intent (what and why) and the guardrails (what not
to touch, what invariants to preserve). Prefer surgical, scoped edits over
rewrites. State explicitly what is out of scope for a given change; do not
assume it is obvious.

## Commits

Claude Code commits and pushes verified, non-breaking work by default. It
pauses and flags for human review before pushing anything that touches the
send/delivery path, the systemd scheduler or timer, or secrets and `.env`.
For this project, "breaking prod" means the scheduled Sunday email failing,
misfiring, or double-sending, so those are the paths that get an extra pause.
Everything else (docs, tests, the digest template, the scoring rubric) is
safe to commit once the test suite is green and a `--dry-run` passes.

## Testing

The Claude API call is mocked in every test; no test makes a live network or
API call. `--dry-run` fetches live and calls Claude for real, but prints the
digest instead of sending it, and neither reads nor writes `cache.json`.
Verify both, a green test suite and a clean `--dry-run`, before committing.
