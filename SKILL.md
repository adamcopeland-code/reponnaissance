---
name: reponnaissance
description: Reconnaissance on GitHub repositories before you depend on them. Use when asked to find a library, package, tool, or repo for a task, to compare candidates, or to check whether a repo is maintained, widely used, and free of known vulnerabilities. Triggers on "find a library for", "which repo should I use", "is this maintained", "is this safe to depend on", "compare these repos", "vet this dependency", "best X library".
---

# Reponnaissance

*Scout the ground before you commit.*

Existing tools search code and return lists. This one returns a verdict. Which repo
to use, why, and what would change the answer. `SPEC.md` is the contract, and this
file is how to run it.

The two steps nobody else ships are the middle ones. Disqualify before you spend,
then actually read the survivors. Cut the reading to save tokens and this skill has
no reason to exist.

## Pipeline

### 1. Search, expanded

Two to four query variants, never one. `probe.py --search` takes several at once and
dedupes them, so the expansion is one command. The person gives you intent; intent is
not a query, and translating it decides whether everything downstream is reading the
right eight repos. Measured: one naive query finds the known answer for 3 of the 7
intents in `scripts/benchmark.py`, the expanded recipe finds all 7.

**Never send the sentence.** Sometimes it returns nothing, which is obvious and
harmless. The dangerous case is when it returns something. "something to make my
python code faster" returns an image classifier at 43 stars and a hand-detection
model at 279 — ordinary-looking results with nothing to do with speed, and nothing
in the output says so. "python profiler" returns `py-spy` at 15,481.

**Write the artifact, not the action.** "markdown to pdf", not "convert markdown to
pdf". "python profiler", not "make my python faster". Descriptions name what a thing
is, rarely what you are trying to do with it.

**Run topic and keyword both, always.** They find different repos and neither is
enough alone. For "make my python code faster", topic search returns `py-spy` and
`scalene`; the keyword search returns neither. For "convert markdown to pdf" it
reverses: keyword finds the right tool, topic drifts to `microsoft/markitdown`,
which converts *to* markdown and is not what was asked.

**Two topics, not one.** A single topic returns whatever is popular nearby rather
than the thing itself. `--topic swiftui` alone returns a menu bar manager;
`--topic swiftui --topic design-system` returns `pixiv/charcoal-ios`.

**`--language` is the implementation language, not the runtime, and it silently
drops the answer.** `nodemailer` is what any Node developer would name: 17,669
stars, topic `email`, actively pushed. Seven strategies missed it -- keyword,
topic pair, smtp keyword, star-sorted -- because every one of them said
`javascript` and GitHub records nodemailer as **TypeScript**. Drop the filter and
`--topic email --sort stars` returns it. Never qualify a runtime ask (node, deno,
bun) by language; for a platform ask, expect both Swift and Objective-C.

**Do not narrow a generic word with `--language` either.** `profiler --language python`
returns `CellProfiler` and `DataProfiler`, which match a name substring and are not
profilers. Qualify a specific phrase, not a generic one: `http library
language:python` returns `psf/requests` first, `http client language:python` never
returns it at all.

**Sort twice.** Best match and `--sort stars` return different top fives and neither
is better. On "swiftui components" only three repos appeared in both. Merge and dedupe.

**When search ranks badly, stop searching and read the curated list.** A category
GitHub cannot rank is usually one a person has already indexed by hand.

```bash
python3 scripts/probe.py --awesome swift chart     # awesome-swift, the Chart section
python3 scripts/probe.py --awesome python debug    # awesome-python, Debugging Tools
```

It finds the highest-starred `awesome-<ecosystem>` list, takes the repos under the
headings matching your words, and probes all of them. "swiftui charts" through the
full recipe puts `AppPear/ChartView` at rank 11 and never returns `ChartsOrg/Charts`
at 28k stars at all; the Chart section lists both, canonical first. The section
headings are the vocabulary you were guessing at.

Two things to hold onto. These lists are alphabetical, so position means nothing --
read the probe verdicts, not the order. And a curated list is a claim, not evidence:
`ScrollableGraphView` sits in that section at 5,284 stars and comes back with
concerns. Check the list's own pushed date before trusting its picks.

**Say which reading you took.** A vague ask has several honest readings and the
pipeline cannot rank across them, because they are not competing. Name the one you
searched and list the others.

```bash
python3 scripts/probe.py --search "python profiler" "--topic profiler --language python" --limit 15
gh search repos "nostr relay" --language rust --limit 20 --json fullName,description,stargazersCount
```

Quoting matters more than it looks. A query that reaches `gh` as one argument is sent
to GitHub quoted, and quoted means exact-phrase, which matches the abandoned long
tail: "tool to convert markdown to pdf" as a phrase returns six repos with zero stars
between them, and split into words returns `markitdown` at 180k. `probe.py` splits
for you; a hand-written `gh` call does not.

GitHub search allows 30 requests per minute. Do one burst, then stop searching.
Everything after this comes from the 5,000/hr core pool or from non-GitHub APIs
that have no shared limit.

### 2 & 3. Disqualify and probe, in one script call

`scripts/probe.py` does both. Feed it every candidate. It returns JSON with a
verdict and the evidence behind it.

```bash
python3 scripts/probe.py owner/repo owner/repo2 ...
python3 scripts/probe.py --search "nostr relay" "--topic nostr --topic relay" --limit 15
```

Python 3 standard library only. Needs `gh` on PATH and authenticated. deps.dev,
OSV.dev and ecosyste.ms are unauthenticated public HTTP.

Per repo it returns `state` (`reject` / `concerns` / `ok`) with a cited reason for
every rejection, plus:

| Field | Source | Meaning |
|---|---|---|
| `meta` | `gh api /repos/...` | archived, fork + parent, license, `stale_days` |
| `scorecard_overall`, `failed_security_checks` | deps.dev embedded Scorecard | hygiene, and may be absent |
| `advisories` | OSV.dev | `[]` = checked and clean, `null` = not checked |
| `version.provenance_verified` | deps.dev `slsaProvenances` | artifact cryptographically tied to a source commit |
| `adoption` | ecosyste.ms | dependent repos/packages and percentile rankings |
| `stars_disagree` | derived | set when stars and real adoption diverge, always surface it |

`pct_dependents` and `pct_stars` are rankings inside one registry, so they only
compare candidates from the same ecosystem. Across ecosystems use the raw
`dependent_repos` count instead. axios sits at percentile 0.05 in npm and gin at
0.02 in the Go proxy, yet axios has eight times more dependent repos.

Rejections are automatic on `archived`, fork-with-living-parent, missing license,
or a high or critical unwithdrawn advisory in the current version.

### 4. Read the top 3

For every survivor, read the README, the entry point and the public API shape,
judged against the stated need rather than in the abstract. No scoring service
knows what you are building. This is the only step that does. Report what the API
actually looks like rather than that it exists.

Check the platform claim against `meta.language`, not against topics. Topics are
self-declared and routinely wrong. On "designing an iOS app" the two highest
starred results were `heroui-native` at 3,636 stars, which is TypeScript and
React Native, and `compose-unstyled` at 1,218, which is Kotlin. Both carry the
`ios` topic. A third, `genjutsu` at 333 stars, is tagged `swiftui` and is a
Python collection of creative-coding prompts. Ranking by stars hands back all
three.

### 4b. If the need is vague, say which reading you took

A request like "a repo to help with designing an iOS app" has at least four
honest interpretations: a UI component library, a design-token system, a
reference collection, or an agent skill. The pipeline returns all four kinds and
cannot rank across them, because they are not competing. Name the interpretation
you chose, give the verdict inside it, and list the other readings in one line
each so the person can redirect you. Do not silently pick one and present it as
the answer.

### 5. Verdict

One recommendation, or an honest "none qualify", with a head-to-head table for the
shortlist. Print adoption next to stars and call out any disagreement between them.
Close with a "what would change my mind" line.

## Security check

Three states. Never two, and never a score.

- `vulnerable` means an OSV advisory affects the current version. Cite the GHSA id.
- `hygiene concerns` means naming the failing Scorecard checks. Never a bare number.
- `not assessed` means no Scorecard, or the repo publishes no package, or both.

`not assessed` is the most common answer on exactly the small repos this skill
exists to find. On a five-repo nostr relay set, three had no Scorecard at all,
including the two most-starred. Rendering that as "0/10" or as "no known issues"
is worse than having no security step.

Rules the script enforces, which the write-up must not undo:

- Filter withdrawn advisories. The GitHub feed serves retracted CVEs, and the top
  hit for `express` is one. Reporting a retracted CVE as live is the bug that costs
  the most trust.
- Never average Scorecard checks. A score of `-1` means the check did not run, and
  `express` carries two. Averaging punishes well-run repos.
- Never claim to read a stranger's Dependabot or code-scanning alerts. Both return
  403 on repos you do not own. You cannot see them, so do not pretend to.
- Treat provenance as a positive only. Report `provenance_verified` when it is
  there. Absence is normal and is never a minus.
- Do not hand-roll file checks. Asking "Has SECURITY.md?" returns a false negative
  when the policy lives in an org-level `.github` repo, as express's does. Scorecard
  already gets this right, so take its answer or say `not assessed`.
- Do not query OSV for a package no registry publishes. OSV answers `{}` for a
  package that does not exist, which is byte-identical to clean. The script refuses
  to ask when it cannot resolve a published version, and returns `null` instead.

## Honesty (include this in any output the skill produces)

- It reads published metadata and documentation, not code paths. It is not an
  audit, and it would not have caught event-stream.
- Scorecard data is weeks stale where it exists, and absent on most small repos.
- OSV silence means "not indexed", not "safe".
- On slop detection, the mechanical signals are facts: fork-of, zero stars, no
  releases, no provenance, install script present. "This README looks LLM-written"
  is a heuristic. Flag it with stated uncertainty rather than asserting it. Under a
  security heading, a false positive is an accusation against a real maintainer.

## Checks

```bash
python3 scripts/probe.py --selftest        # pure verdict logic, no network
python3 scripts/probe.py fiatjaf/khatru macko76/ossf-scorecard   # acceptance
```

The acceptance pair is the point of the skill. `fiatjaf/khatru` has 139 stars and
is archived. `macko76/ossf-scorecard` is a stale zero-star fork that surfaces in a
plain search for the real `ossf/scorecard`. Both must be rejected on sight, each
citing its reason. Stars catch neither.
