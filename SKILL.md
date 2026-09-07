---
name: reponnaissance
description: Reconnaissance on GitHub repositories before you depend on them. Use when asked to find a library, package, tool, or repo for a task, to compare candidates, or to check whether a repo is maintained, widely used, and free of known vulnerabilities. Triggers on "find a library for", "which repo should I use", "is this maintained", "is this safe to depend on", "compare these repos", "vet this dependency", "best X library".
---

# Reponnaissance

*Scout the ground before you commit.*

Existing tools search code and return lists. This one returns a **verdict**: which
repo to use, why, and what would change the answer. `SPEC.md` is the contract;
this file is how to run it.

The two steps nobody else ships are the middle ones — **disqualify before you
spend, then actually read the survivors**. The reading step is the moat. Cut it to
save tokens and this skill has no reason to exist.

## Pipeline

### 1. Search, expanded

Two to four query variants, not one keyword. Topic, plain keyword, and
language-qualified:

```bash
gh search repos "nostr relay" --language rust --limit 20 --json fullName,description,stargazersCount
gh search repos --topic nostr --topic relay --limit 20 --json fullName
```

**Budget: GitHub search is 30 requests/minute.** One burst, then stop searching.
Everything after this comes from the 5,000/hr core pool or from non-GitHub APIs
that have no shared limit.

### 2 & 3. Disqualify and probe — one script call

`scripts/probe.py` does both. Feed it every candidate; it returns JSON with a
verdict and the evidence behind it.

```bash
python3 scripts/probe.py owner/repo owner/repo2 ...
python3 scripts/probe.py --search "nostr relay implementation" --limit 15
```

Python 3 standard library only. Needs `gh` on PATH and authenticated; deps.dev,
OSV.dev and ecosyste.ms are unauthenticated public HTTP.

Per repo it returns `state` (`reject` / `concerns` / `ok`) with a cited reason for
every rejection, plus:

| Field | Source | Meaning |
|---|---|---|
| `meta` | `gh api /repos/…` | archived, fork + parent, license, `stale_days` |
| `scorecard_overall`, `failed_security_checks` | deps.dev embedded Scorecard | hygiene; **may be absent** |
| `advisories` | OSV.dev | `[]` = checked and clean · `null` = **not checked** |
| `version.provenance_verified` | deps.dev `slsaProvenances` | artifact cryptographically tied to a source commit |
| `adoption` | ecosyste.ms | dependent repos/packages and percentile rankings |
| `stars_disagree` | derived | set when stars and real adoption diverge — always surface it |

Rejections are automatic on: `archived`, fork-with-living-parent, missing license,
or a high/critical unwithdrawn advisory in the current version.

### 4. Read the top 3

For every survivor: README, the entry point, the public API shape — judged against
the **stated need**, not in the abstract. No scoring service knows what you are
building; this is the only step that does. Report what the API actually looks like,
not that it exists.

### 5. Verdict

One recommendation (or an honest "none qualify"), a head-to-head table for the
shortlist, **adoption printed next to stars with any disagreement called out**, and
a closing "what would change my mind" line.

## Security check

Three states. Never two, never a score.

- **`vulnerable`** — an OSV advisory affects the current version. Cite the GHSA id.
- **`hygiene concerns`** — name the failing Scorecard checks. Never a bare number.
- **`not assessed`** — no Scorecard, or the repo publishes no package, or both.

`not assessed` is the *most common* answer on exactly the small repos this skill
exists to find. On a five-repo nostr relay set, three had no Scorecard at all —
including the two most-starred. Rendering that as "0/10" or as "no known issues"
is worse than having no security step.

Rules the script enforces, which the write-up must not undo:

- **Withdrawn advisories are filtered.** The GitHub feed serves retracted CVEs —
  the top hit for `express` is one. Reporting it as live is the credibility-losing bug.
- **Never average Scorecard checks.** `-1` means the check did not run; `express`
  carries two. Averaging punishes well-run repos.
- **Never claim to read a stranger's Dependabot or code-scanning alerts.** Both
  return 403 on repos you do not own. The check is invisible; do not fake it.
- **Provenance is plus-only.** Report `provenance_verified` as a positive.
  Absence is normal and is never a minus.
- **No hand-rolled file checks.** "Has SECURITY.md?" is false-negative when the
  policy lives in an org-level `.github` repo — as `express`'s does. Scorecard
  already did it right; take its answer or say `not assessed`.
- **No unpublished-package queries.** OSV answers `{}` for a package that does not
  exist, byte-identical to clean. The script refuses to ask when it cannot resolve
  a published version, and returns `null` instead.

## Honesty section — belongs in any output this skill produces

- It reads **published metadata and documentation, not code paths**. It is not an
  audit and **would not have caught event-stream**.
- Scorecard data is weeks stale where it exists and absent on most small repos.
- OSV silence means "not indexed", not "safe".
- Slop detection: the mechanical signals (fork-of, zero stars, no releases, no
  provenance, install script present) are facts. "This README looks LLM-written"
  is a **heuristic** — flag it with stated uncertainty, never assert it. Under a
  security heading a false positive is an accusation against a real maintainer.

## Checks

```bash
python3 scripts/probe.py --selftest        # pure verdict logic, no network
python3 scripts/probe.py fiatjaf/khatru macko76/ossf-scorecard   # acceptance
```

The acceptance pair is the point of the skill: `fiatjaf/khatru` has 139 stars and
is archived; `macko76/ossf-scorecard` is a stale zero-star fork that surfaces in a
plain search for the real `ossf/scorecard`. Both must be rejected on sight, each
citing its reason. Stars catch neither.
