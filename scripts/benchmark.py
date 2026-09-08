#!/usr/bin/env python3
"""Measure the probe against repos whose answer is known independently.

    python3 scripts/benchmark.py

Reports accuracy per case, search recall, wall-clock, and throughput. Exits non-zero if any
case fails, so it can gate a release.

On what this can and cannot prove: `archived`, `fork` and `license` come from the
same GitHub fields the probe reads, so those cases test the plumbing, not the
judgement. The honest measurements here are the vulnerability cases, which use
GHSA ground truth from a different database, and the false-clean cases, which
check that the probe refuses to call something safe when it never looked. The
search cases below measure the half that was never measured: whether the right
repo is in the candidate set at all, against answers known before the search ran.

Search costs 18 of GitHub's 30 requests per minute, so do not loop this.
"""
import json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import probe

# (repo, expected state, expected security, why we know)
REPOS = [
    ("fiatjaf/khatru",           "reject",   None,            "archived, 139 stars: stars hide it"),
    ("pagekit/vue-resource",     "reject",   None,            "archived"),
    ("aspnet/HttpClientFactory", "reject",   None,            "archived"),
    ("macko76/ossf-scorecard",   "reject",   None,            "fork of a living ossf/scorecard"),
    ("snoyberg/http-client",     "reject",   None,            "no license"),
    ("expressjs/express",        "ok",       "no known issues", "maintained, licensed, 1.8M dependents"),
    ("seanmonstar/reqwest",      None,       None,            "healthy: must not be rejected"),
    ("uber-go/zap",              None,       None,            "vanity import path go.uber.org/zap"),
    ("ossf/scorecard",           None,       None,            "the real one, must outrank its fork"),
    ("hoytech/strfry",           None,       "not assessed",  "C++, publishes no package"),
    ("guzzle/guzzle",            None,       "not assessed",  "Packagist: unsupported, must not read clean"),
    ("facebook/react",           None,       "not assessed",  "monorepo, private root manifest"),
]

# Pinned versions with advisories confirmed in the GitHub Advisory Database.
VULNS = [
    ("npm", "npm",  "event-stream", "3.3.6", "critical", "GHSA-mh6f-8j2x-4483"),
    ("go",  "Go",   "github.com/gin-gonic/gin", "1.6.0", "high", "GHSA-h395-qcrw-5vmq"),
]
# Current versions of healthy packages: must come back empty, not unknown.
CLEAN = [("npm", "npm", "express", None), ("go", "Go", "go.uber.org/zap", None)]


# --- search recall: does the pipeline find the answer at all? ----------------
#
# The probe judges a repo it has been handed. Nothing measured that until now, so
# a search that never surfaces the right repo scores a clean sheet. These cases
# are intents phrased the way someone actually asks, each with an answer that was
# known before the search ran (an established repo any developer in that field
# would name), and each run twice: once as a single naive query, once as the
# union of variants the SKILL.md recipe asks for.
#
# floor = the best result must clear this star count. That is the quiet-garbage
# guard: a search can return ten real repos that nobody uses, and nothing in a
# name or description says the field is weak. See the phrase trap below for the
# way we produced that failure on demand.
#
# (intent, naive query, expanded queries, one-of these must appear, star floor, why we know)
SEARCH_CASES = [
    ("designing an iOS app",
     "designing an iOS app",
     ["ios design system language:swift", "--topic ios --topic design-system"],
     ["Skyscanner/backpack-ios", "salesforce-ux/design-system-ios", "pixiv/charcoal-ios"],
     50, "shipped design systems from Skyscanner, Salesforce and pixiv"),

    ("a terminal UI in Go",
     "terminal ui go",
     ["--topic tui --language go", "tui framework language:go"],
     ["charmbracelet/bubbletea", "rivo/tview"],
     10000, "bubbletea at 44k is the canonical answer and the naive query cannot see it"),

    ("convert markdown to pdf",
     "tool to convert markdown to pdf",
     ["markdown to pdf", "--topic markdown --topic pdf"],
     ["alanshaw/markdown-pdf", "microsoft/markitdown", "realdennis/md2pdf"],
     1000, "markitdown and md-to-pdf; the same sentence quoted returns six 0-star repos"),

    ("make http requests from python",
     "library for making http requests in python",
     ["http library language:python", "--topic http-client --language python"],
     ["psf/requests", "encode/httpx"],
     10000, "requests at 54k; the naive sentence returns ten repos and none is it"),

    ("parse command line arguments in rust",
     "command line argument parser rust",
     ["clap language:rust", "--topic cli --topic argument-parser"],
     ["clap-rs/clap"],
     10000, "naive already works here: the expanded recipe must not lose it"),

    ("add charts to a react app",
     "react charts",
     ["chart library language:typescript", "--topic react --topic charts"],
     ["recharts/recharts", "plouc/nivo"],
     10000, "recharts at 27k; the topic union adds nivo and victory, which keywords miss"),
]


def stars(slug):
    r = probe.gh(f"/repos/{slug}", jq=".stargazers_count")
    return int(r) if r is not None else 0


def search_bench():
    """Recall of one naive query vs the union of variants. Returns (fails, lines)."""
    print("\nSearch recall (vague intent -> known answer, naive query vs expanded recipe)")
    fails = 0
    naive_hits = expanded_hits = 0
    for intent, naive, expanded, wanted, floor, why in SEARCH_CASES:
        got_naive = probe.search(naive, 10)
        got_exp = probe.search_all(expanded, 10)
        hit_n = [s for s in wanted if s in got_naive]
        hit_e = [s for s in wanted if s in got_exp]
        naive_hits += bool(hit_n)
        expanded_hits += bool(hit_e)
        # The floor is only meaningful on the set we would actually hand to the probe.
        best = max((stars(s) for s in got_exp[:6]), default=0)
        ok = bool(hit_e) and best >= floor
        fails += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {intent}")
        print(f"        naive     {naive!r:<45} {'found ' + hit_n[0] if hit_n else 'MISS':>34}"
              f"  ({len(got_naive)} results)")
        print(f"        expanded  {str(expanded):<45} {'found ' + hit_e[0] if hit_e else 'MISS':>34}"
              f"  ({len(got_exp)} results, best {best:,} stars)")
        if not ok:
            print(f"        -> {'no known answer surfaced' if not hit_e else f'best result {best:,} stars, under the {floor:,} floor'}")
        print(f"        ground truth: {why}")
    n = len(SEARCH_CASES)
    print(f"\n  recall: naive {naive_hits}/{n}, expanded {expanded_hits}/{n}")
    return fails + phrase_trap()


def phrase_trap():
    """A query in one argv entry reaches GitHub quoted, and quoted means exact phrase.

    This is the same root cause as the qualifier bug, wearing different clothes.
    A beginner's sentence as a phrase matches only repos whose text contains that
    sentence, which is the abandoned long tail: six results, zero stars between
    them. Split into words it is an AND over relevance and returns microsoft/
    markitdown at 180k. The split lives in probe._argv; this proves it still bites
    if anyone undoes it, using the shipped code path in both directions.
    """
    q = "tool to convert markdown to pdf"
    phrase = max((stars(s) for s in probe.search(f'"{q}"', 6)), default=0)
    words = max((stars(s) for s in probe.search(q, 6)), default=0)
    ok = phrase < 1000 <= words
    print(f"\nPhrase trap (one argv entry = exact-phrase match, the silent-junk path)")
    print(f"  {'PASS' if ok else 'FAIL'}  {q!r}: "
          f"as a phrase, best result {phrase:,} stars; split into words, {words:,}")
    return not ok


def check(row):
    slug, want_state, want_sec, _ = row
    r = probe.probe(slug)
    fails = []
    if want_state and r["state"] != want_state:
        fails.append(f"state {r['state']!r}, wanted {want_state!r}")
    if want_state is None and r["state"] == "reject":
        fails.append(f"rejected a healthy repo: {'; '.join(r['reasons'])}")
    if want_sec and r.get("security") != want_sec:
        fails.append(f"security {r.get('security')!r}, wanted {want_sec!r}")
    return slug, fails, r


def main():
    print("Reponnaissance benchmark\n")
    before = subprocess.run(["gh", "api", "/rate_limit", "--jq", ".resources.core.remaining"],
                            capture_output=True, text=True).stdout.strip()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(check, REPOS))
    elapsed = time.time() - t0
    after = subprocess.run(["gh", "api", "/rate_limit", "--jq", ".resources.core.remaining"],
                           capture_output=True, text=True).stdout.strip()

    failed = 0
    for (slug, fails, r), row in zip(results, REPOS):
        mark = "PASS" if not fails else "FAIL"
        failed += bool(fails)
        print(f"  {mark}  {slug:<26} {r['state']:<9} {str(r.get('security')):<16} {row[3]}")
        for f in fails:
            print(f"        -> {f}")

    print("\nVulnerability detection (GHSA ground truth, pinned versions)")
    for _, eco, name, ver, want_sev, want_id in VULNS:
        advs = probe.advisories(eco, name, ver) or []
        hit = next((a for a in advs if a["id"] == want_id), None)
        ok = hit and hit["severity"] == want_sev
        failed += not ok
        got = f"{hit['severity']}" if hit else "not found"
        print(f"  {'PASS' if ok else 'FAIL'}  {name}@{ver:<8} {want_id} expected {want_sev}, got {got} "
              f"({len(advs)} distinct advisories)")

    print("\nFalse-clean guard (current versions must be empty, never null)")
    for sysname, eco, name, _ in CLEAN:
        ver = probe.default_version(sysname, name)
        advs = probe.advisories(eco, name, ver)
        ok = advs == []
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}@{ver} -> {advs if advs != [] else 'clean'}")

    failed += search_bench()

    calls = int(before) - int(after) if before and after else 0
    print(f"\n{len(REPOS)} repos in {elapsed:.1f}s ({elapsed/len(REPOS):.2f}s each), "
          f"{calls} GitHub core calls ({calls/len(REPOS):.1f} per repo)")
    print(f"Core budget 5,000/hr, so about {5000*len(REPOS)//max(calls,1):,} repos per hour.")
    print(f"\n{'ALL PASS' if not failed else str(failed) + ' FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
