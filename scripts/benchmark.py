#!/usr/bin/env python3
"""Measure the probe against repos whose answer is known independently.

    python3 scripts/benchmark.py

Reports accuracy per case, wall-clock, and throughput. Exits non-zero if any
case fails, so it can gate a release.

On what this can and cannot prove: `archived`, `fork` and `license` come from the
same GitHub fields the probe reads, so those cases test the plumbing, not the
judgement. The honest measurements here are the vulnerability cases, which use
GHSA ground truth from a different database, and the false-clean cases, which
check that the probe refuses to call something safe when it never looked.
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

    calls = int(before) - int(after) if before and after else 0
    print(f"\n{len(REPOS)} repos in {elapsed:.1f}s ({elapsed/len(REPOS):.2f}s each), "
          f"{calls} GitHub core calls ({calls/len(REPOS):.1f} per repo)")
    print(f"Core budget 5,000/hr, so about {5000*len(REPOS)//max(calls,1):,} repos per hour.")
    print(f"\n{'ALL PASS' if not failed else str(failed) + ' FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
