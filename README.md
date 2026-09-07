# Reponnaissance

**Vet a repo before you depend on it.**

An [Agent Skill](https://docs.claude.com/en/docs/agents/skills) that finds the right
GitHub repository for a need and tells you whether to depend on it — with evidence.

Every existing tool in this lane returns a *list* and leaves the judging to you.
This skill returns a **verdict**: search, disqualify the junk cheaply, actually read
the top candidates for fit, then recommend one repo with the evidence attached and a
"what would change my mind" line.

## Why not just sort by stars?

Stars are the metric every tool has and the one that lies most. From the live probe
that motivated this skill: the #3 stars result for nostr relays was archived and
dead; a zero-star fork of `ossf/scorecard` outranked the real one in a plain web
search. Both are one API field away from being caught — this skill reads those
fields. Real adoption comes from dependents counts (deps.dev, ecosyste.ms), which
are printed next to stars so disagreement between them is visible.

## What it does

1. Searches with expanded queries (`gh search repos`, one burst, rate-limit aware)
2. Disqualifies cheaply, every rejection cited: archived, name-squat forks, stale,
   license mismatch, known vulnerabilities (OSV, withdrawn CVEs filtered)
3. Probes survivors: deps.dev metadata + embedded OpenSSF Scorecard + dependents
4. Reads the top 3 — README, entry points, API shape — against *your* need
5. Delivers a verdict: recommendation, head-to-head shortlist, security state,
   and what would change the answer

Security is reported in three states — `vulnerable` (with the GHSA), `hygiene
concerns` (named failed checks), or `not assessed` — never a score, because most
small repos have no Scorecard and pretending otherwise is theatre.

## Install

Copy the skill folder into your skills directory:

```sh
# Claude Code (personal)
cp -r reponnaissance ~/.claude/skills/

# or per-project
cp -r reponnaissance .claude/skills/
```

Requires the `gh` CLI (authenticated raises rate limits; not required). The other
data sources (OSV.dev, deps.dev, ecosyste.ms) are free and unauthenticated.

## Use

Ask your agent things like:

> find me a maintained Rust nostr relay I can build on

> should I depend on foo/bar, or is there something healthier?

The skill triggers on its own inside any agent session. It does not run on a
schedule by itself; pair it with your agent's scheduler if you want periodic scans.

## Honest limits

- It reads **published metadata and documentation, not code**. It is not an audit
  and would not have caught a compromised maintainer (event-stream).
- It cannot see a stranger's Dependabot or code-scanning alerts (GitHub returns
  403 on repos you don't own) — so it never claims to.
- AI-generated-README detection is a flagged heuristic, never an assertion.

## Layout

- `SKILL.md` — the pipeline instructions the agent follows
- `scripts/probe.py` — repo list in; disqualify verdict + deps.dev + OSV +
  provenance JSON out
- `SPEC.md` — the v1 contract this implements
