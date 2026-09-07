# Reponnaissance: v1 specification

One page. The contract the skill must honor. Every API claim below was probed
live against the real endpoints on 2026-09-07. The failure modes named here are
ones we hit, not ones we anticipated.

## The job

Given a need ("a maintained Rust nostr relay", "a library that parses X"), return a
verdict with evidence: which repo to use, why, and what would change the answer.
Not a search-result list. The two steps nobody else ships are the middle ones,
cheap disqualification before anything expensive and actually reading the top
candidates for fit. Cut the reading step and this skill has no reason to exist.

## Pipeline

1. **Search, expanded.** Two to four query variants (topic, keyword,
   language-qualified) via `gh search repos`. Budget: GitHub search allows 30
   requests a minute, so run one burst and stop searching. All later reads come
   from the 5,000/hr core pool or non-GitHub APIs.
2. **Disqualify pass.** Cheap fields, run on every candidate, each rejection cited:
   - `archived: true`
   - `fork: true` with a living parent (name-squat or fork-confusion)
   - stale: `pushed_at` beyond the threshold for the ecosystem (default 18 months)
   - license absent or incompatible with the stated need
   - known vulnerability: OSV.dev query, filtering `withdrawn_at`. Reporting a
     withdrawn CVE as live is the bug that costs the skill its credibility.
3. **Probe survivors.** One `deps.dev` call each: metadata plus the embedded OpenSSF
   Scorecard. Never call the Scorecard API first. It 404s for every project that did
   not opt in. Adoption comes from ecosyste.ms (`dependent_repos_count` plus
   percentile rankings, with registry names `npmjs.org`, `proxy.golang.org`,
   `crates.io`, `pypi.org`). deps.dev `dependentCount` fails for Go modules, the same
   partial-coverage trap as Scorecard. There is no GitHub dependents API. Never
   scrape the HTML page.
4. **Read the top 3.** README, entry points, API shape, judged against the stated
   need. This is the moat and the token spend. Do not optimize it away.
5. **Verdict.** One recommended repo, or an honest "none qualify". A head-to-head
   table for the shortlist. Adoption printed next to stars, with any disagreement
   between them called out. A "what would change my mind" line.

## Security check (rides the pipeline, adds almost no cost)

- Three states, never two, never a score: `vulnerable` (cite the GHSA),
  `hygiene concerns` (name the failed Scorecard checks), `not assessed`.
  On small repos `not assessed` is the common answer. Rendering it as "0/10" or
  as "no known issues" is worse than having no security step at all.
- Never average Scorecard checks. A `-1` means the check did not run, and
  averaging punishes well-run repos.
- Never claim to check a stranger's Dependabot or code-scanning alerts. Both
  return 403 on repos you don't own. The check is invisible, so do not fake it.
- SLSA provenance (`deps.dev slsaProvenances[].verified`): report presence as a
  plus. Never report absence as a minus.
- Hand-rolled file checks ("has SECURITY.md?") are banned. Org-level `.github`
  repos make them false-negative. Scorecard already did it right.
- The OSV empty-object trap: OSV returns `{}` for a package no registry
  publishes, byte-identical to a clean result. Never query without a resolvable
  published version. An unpublished repo is `not assessed`, not clean. We hit
  this live in the first build, and this line is why it stays caught.

## Non-goals (also the README's honesty section)

- Not a code audit. It reads published metadata and documentation, not code paths.
  It would not have caught event-stream.
- AI-generated-README detection ships as a flag with stated uncertainty, never an
  assertion. The mechanical slop checks (fork, zero stars, no releases) are facts.
  The semantic one is a heuristic.
- No ranking service is reimplemented. deps.dev, OSV and ecosyste.ms are the
  sources. The skill's value is disqualification, reading, and the verdict.

## Interfaces

`gh` (works unauthenticated, and authenticating raises the limits), OSV.dev, deps.dev and
ecosyste.ms (all unauthenticated, none touch GitHub rate limits). No API keys, no
infrastructure, no state between runs. The probe helper is Python 3 stdlib only.
Five JSON APIs in bash would mean a `jq` dependency, and Python keeps the verdict
logic a pure function testable offline (`probe.py --selftest`).

## Acceptance

Run the pipeline on a real query where stars mislead. The probe set is nostr
relays: `fiatjaf/khatru` is archived at 139 stars and must be disqualified on
sight, and the `macko76/ossf-scorecard` name-squat must never surface. The
verdict must cite every rejection and print adoption beside stars.
