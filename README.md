<img src="assets/logo.svg" width="76" align="right" alt="">

# Reponnaissance

[![live-check](https://github.com/adamcopeland-code/reponnaissance/actions/workflows/live-check.yml/badge.svg)](https://github.com/adamcopeland-code/reponnaissance/actions/workflows/live-check.yml)

Reponnaissance is an [agent skill](https://code.claude.com/docs/en/skills) that picks
which GitHub repository you should depend on and shows the evidence for the pick. It
searches, drops the dead and the unlicensed, checks the survivors against OSV and the
OpenSSF Scorecard, then reads the top three and writes a verdict. It runs inside
Claude Code or any agent that loads Agent Skills.

[Install](#install) | [Use](#use) | [A real run](#a-real-run) | [Limitations](#limitations)

MIT licensed.

## What it checks instead of stars

Stars are the metric every tool has and the one that lies most. From the live probe
that motivated this skill, the third stars result for nostr relays was archived and
dead, and a zero-star fork of `ossf/scorecard` outranked the real one in a plain web
search. Both are one API field away from being caught, and this skill reads those
fields. Real adoption comes from dependents counts (deps.dev, ecosyste.ms), printed
next to stars so you can see when the two disagree.

## What it does

1. Searches with expanded queries (`gh search repos`, one burst, rate-limit aware)
2. Disqualifies cheaply and cites every rejection. Archived, name-squat forks, stale,
   license mismatch, known vulnerabilities (OSV, with withdrawn CVEs filtered out)
3. Probes the survivors for deps.dev metadata, the embedded OpenSSF Scorecard, and
   dependents
4. Reads the top three (README, entry points, API shape) against *your* need
5. Delivers a verdict. Recommendation, head-to-head shortlist, security state, and
   what would change the answer

Security comes back in three states, `vulnerable` (with the GHSA), `hygiene concerns`
(naming the failed checks), or `not assessed`. Never a single number. Most small repos
have no Scorecard at all, so a score would be mostly invented.

## Install

Copy the skill folder into your skills directory.

```sh
# Claude Code (personal)
cp -r reponnaissance ~/.claude/skills/

# or per-project
cp -r reponnaissance .claude/skills/
```

Requires the `gh` CLI, authenticated (`gh auth login`). Without a token `gh api`
returns nothing and every repo reads as not found. The other data sources
(OSV.dev, deps.dev, ecosyste.ms) are free and need no account.

## Use

Ask in plain words.

> find me a maintained Rust nostr relay I can build on

> should I depend on foo/bar, or is there something healthier?

The skill triggers on its own inside any agent session. It does not run on a schedule
by itself, so pair it with your agent's scheduler if you want periodic scans.

## A real run

Asked for a nostr relay to self host, on 7 September 2026. Twelve candidates went
in and four were rejected before anything was read. The probe emits one JSON object
per repo. What follows is that output summarised, which is what the agent does with
it before it reads a single line of anyone's code.

```
fiatjaf/khatru                reject     archived, so no patches will ship
fiatjaf/nostr-relay-registry  reject     archived, no license
mattn/nostr-relay             reject     no license, not safe to depend on
BlockChainCaffe/Nostr-Rel...  reject     no license, no push in 1284 days
Yonle/bostr                   concerns   vulnerable, GHSA-5cf7-cxrf-mq73
hoytech/strfry                ok         not assessed, no package manifest
cameri/nostream               ok         not assessed, not published on npm
mikedilger/chorus             ok         no known issues
```

Then the reading step, which is the part metadata cannot do.
`permissionlesstech/georelays` cleared every filter at 131 stars and a push the same
day, and its security line read `not assessed` because it publishes no manifest to
check. No filter missed it. Every mechanical signal was either clean or absent. It is
not a relay. It is an HTML page listing other people's relays and where they are.

The verdict was strfry, pushed three days earlier and the most actively maintained
of the survivors. Its `not assessed` means the repo publishes no package, so OSV has
nothing to look up. It does not mean clean. `khatru` is the useful rejection, because it is the name most people
reach for and it has been archived since September 2025.

## Limitations

- It reads published metadata and documentation, not code. It is not an audit and
  would not have caught a compromised maintainer (event-stream).
- It cannot see a stranger's Dependabot or code-scanning alerts, because GitHub
  returns 403 on repos you do not own, so it never claims to.
- AI-generated-README detection is a flagged heuristic and never an assertion.

## Layout

- `SKILL.md`, the pipeline instructions the agent follows
- `scripts/probe.py`, takes a repo list in and returns the disqualify verdict plus
  deps.dev, OSV and provenance data as JSON
- `SPEC.md`, the v1 contract this implements
