# repo-discovery — v1 specification

One page. The contract the skill must honor. Evidence behind every constraint:
`RESEARCH/2026-09-07_REPO_DISCOVERY_SKILL_LANE.md` and `_REPO_SECURITY_CHECK.md`
in the authors' workspace (all API claims probed live 2026-09-07).

## The job

Given a need ("a maintained Rust nostr relay", "a library that parses X"), return a
**verdict with evidence** — which repo to use, why, and what would change the answer —
not a search-result list. The two steps nobody else ships are the middle ones:
cheap disqualification before anything expensive, and actually reading the top
candidates for fit. Cut the reading step and this skill has no reason to exist.

## Pipeline

1. **Search, expanded.** 2–4 query variants (topic, keyword, language-qualified) via
   `gh search repos`. Budget: GitHub search is 30 req/min — one burst, then stop
   searching. All later reads come from the 5,000/hr core pool or non-GitHub APIs.
2. **Disqualify pass** (cheap fields, run on every candidate, each rejection cited):
   - `archived: true`
   - `fork: true` with a living parent (name-squat / fork-confusion)
   - stale: `pushed_at` beyond the threshold for the ecosystem (default 18 months)
   - license absent or incompatible with the stated need
   - known vulnerability: OSV.dev query, **filtering `withdrawn_at`** — a withdrawn
     CVE reported as live is the credibility-losing bug
3. **Probe survivors.** One `deps.dev` call each: metadata + the **embedded** OpenSSF
   Scorecard (never the Scorecard API first — it 404s for every project that did not
   opt in). Adoption from ecosyste.ms `dependent_repos_count` / deps.dev
   `dependentCount` — **there is no GitHub dependents API; never scrape the HTML page.**
4. **Read the top 3.** README, entry points, API shape — judged against the stated
   need. This is the moat and the token spend; do not optimize it away.
5. **Verdict.** One recommended repo (or an honest "none qualify"), head-to-head
   table for the shortlist, adoption printed **next to** stars with any disagreement
   called out, and a "what would change my mind" line.

## Security check (rides the pipeline, adds ~zero cost)

- **Three states, never two, never a score:** `vulnerable` (cite the GHSA),
  `hygiene concerns` (name the failed Scorecard checks), `not assessed`.
  On small repos `not assessed` is the common answer — rendering it as "0/10" or
  "no known issues" is worse than no security step.
- Never average Scorecard checks: `-1` means "did not run", and averaging punishes
  well-run repos.
- Never claim to check a stranger's Dependabot or code-scanning alerts — both
  return 403 on repos you don't own. The check is invisible; do not fake it.
- SLSA provenance (`deps.dev slsaProvenances[].verified`): report presence as a
  plus. Never report absence as a minus.
- Hand-rolled file checks (e.g. "has SECURITY.md?") are banned — org-level
  `.github` repos make them false-negative. Scorecard already did it right.

## Non-goals (also the README's honesty section)

- Not a code audit. It reads published metadata and documentation, not code paths.
  It would **not** have caught event-stream.
- AI-generated-README detection ships as a *flag with stated uncertainty*, never an
  assertion. The mechanical slop checks (fork/zero-stars/no-releases) are facts;
  the semantic one is a heuristic.
- No ranking service is reimplemented. deps.dev, OSV and ecosyste.ms are the
  sources; the skill's value is disqualification, reading, and the verdict.

## Interfaces

`gh` (authenticated raises limits; works unauthenticated), OSV.dev and deps.dev and
ecosyste.ms (all unauthenticated, none touch GitHub rate limits). No API keys, no
infrastructure, no state between runs.

## Acceptance

Run the pipeline on a real query where stars mislead (the probe set: nostr relays —
`fiatjaf/khatru` is archived at 139 stars and must be disqualified on sight, and the
`macko76/ossf-scorecard` name-squat must never surface). The verdict must cite every
rejection and print adoption beside stars.
