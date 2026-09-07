#!/usr/bin/env python3
"""Reponnaissance evidence layer: disqualify cheaply, enrich the survivors.

Takes repo slugs (or a search query), returns one JSON object per repo with a
disqualify verdict and the security/adoption evidence behind it. It does not
rank and it does not decide. The calling agent reads the survivors and writes
the verdict. This only makes sure the agent is reading the right three repos.

Auth: `gh` for GitHub. deps.dev and OSV are unauthenticated public HTTP.

    probe.py owner/repo [owner/repo ...]
    probe.py --search "nostr relay implementation" --limit 10
    probe.py --selftest
"""
import json, re, subprocess, sys, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

STALE_DAYS = 550  # ~18mo. ponytail: fixed threshold, make it a flag if anyone argues about it.
UA = {"User-Agent": "repo-scout/0.1 (+https://github.com/)"}

# Manifest file -> (deps.dev system, OSV ecosystem, name extractor)
MANIFESTS = {
    "go.mod":         ("go",       "Go",        lambda t: _re1(r"^module\s+(\S+)", t)),
    "package.json":   ("npm",      "npm",       lambda t: (json.loads(t) or {}).get("name")),
    "Cargo.toml":     ("cargo",    "crates.io", lambda t: _re1(r'^\s*name\s*=\s*"([^"]+)"', t)),
    "pyproject.toml": ("pypi",     "PyPI",      lambda t: _re1(r'^\s*name\s*=\s*"([^"]+)"', t)),
}

# Scorecard checks that are about security posture, not general process hygiene.
# Only these move the verdict. Branch-Protection, Pinned-Dependencies and
# Signed-Releases fail on most well-run small projects (guzzle, symfony/http-client
# and reqwest all score 0 on at least one), so they are reported as evidence but
# never raise a concern. A field that fires on everything teaches people to ignore it.
RISK_CHECKS = ("Dangerous-Workflow", "Token-Permissions", "Binary-Artifacts")
REPORTED_CHECKS = RISK_CHECKS + ("Signed-Releases", "Pinned-Dependencies", "Branch-Protection")

# deps.dev system -> ecosyste.ms registry. deps.dev's own :dependents endpoint
# returns "dependents not found" for Go, so adoption comes from ecosyste.ms,
# which covers all four and adds percentile rankings (lower = more adopted).
REGISTRIES = {"go": "proxy.golang.org", "npm": "npmjs.org",
              "cargo": "crates.io", "pypi": "pypi.org"}


# Manifests we can read the coordinates out of, but whose ecosystem is not wired up
# yet. Naming the ecosystem is the honest answer. Saying "no manifest found" reads as
# "this repo publishes nothing", which is wrong for guzzle, okhttp, feign and symfony.
UNSUPPORTED = {"composer.json": "PHP/Packagist", "pom.xml": "Java/Maven",
               "build.gradle": "Java/Maven", "build.gradle.kts": "Java/Maven",
               "Gemfile": "Ruby/RubyGems", "*.gemspec": "Ruby/RubyGems",
               "*.csproj": "NuGet", "pubspec.yaml": "Dart/pub"}


def _re1(pat, text):
    m = re.search(pat, text, re.M)
    return m.group(1) if m else None


def gh(path, jq=None):
    """One `gh api` call. Returns parsed JSON, or None on any non-zero exit (404/403)."""
    cmd = ["gh", "api", path] + (["--jq", jq] if jq else [])
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.stdout.strip() or None


def http(url, payload=None):
    """GET, or POST when payload is given. None on any failure, because absence is data here."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def days_since(ts):
    if not ts:
        return None
    from datetime import datetime, timezone
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - d).days


# --- evidence gathering -----------------------------------------------------

def coordinates(owner, repo):
    """repo -> (deps.dev system, OSV ecosystem, package name). One listing call, then one read."""
    root = gh(f"/repos/{owner}/{repo}/contents")
    if not isinstance(root, list):
        return None
    present = {f["name"] for f in root if f.get("type") == "file"}
    for fname, (system, ecosystem, extract) in MANIFESTS.items():
        if fname not in present:
            continue
        blob = gh(f"/repos/{owner}/{repo}/contents/{fname}")
        if not isinstance(blob, dict) or not blob.get("content"):
            continue
        import base64
        try:
            text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
            name = extract(text)
        except Exception:
            name = None
        if name:
            return system, ecosystem, name
        return None, None, f"{fname} names no package (private root manifest, likely a monorepo)"
    for fname, eco in UNSUPPORTED.items():
        hit = (fname in present if "*" not in fname
               else any(f.endswith(fname[1:]) for f in present))
        if hit:
            return None, None, f"{eco} package ({fname}), ecosystem not supported yet"
    return None, None, "no recognised package manifest at the repo root"


def scorecard(owner, repo):
    """deps.dev project. Returns (project_dict, scorecard_or_None). Absent != failing."""
    pid = urllib.parse.quote(f"github.com/{owner}/{repo}", safe="")
    proj = http(f"https://api.deps.dev/v3alpha/projects/{pid}") or {}
    return proj, proj.get("scorecard")


def default_version(system, name):
    d = http(f"https://api.deps.dev/v3alpha/systems/{system}/packages/{urllib.parse.quote(name, safe='')}")
    if not d:
        return None
    for v in d.get("versions", []):
        if v.get("isDefault"):
            return v["versionKey"]["version"]
    return None


def version_facts(system, name, version):
    """isDeprecated + SLSA provenance for the default version."""
    if not version:
        return {}
    d = http(f"https://api.deps.dev/v3alpha/systems/{system}/packages/"
             f"{urllib.parse.quote(name, safe='')}/versions/{urllib.parse.quote(version, safe='')}")
    if not d:
        return {}
    prov = [p for p in (d.get("slsaProvenances") or []) if p.get("verified")]
    return {"deprecated": d.get("isDeprecated") or False,
            "deprecated_reason": d.get("deprecatedReason") or None,
            "provenance_verified": bool(prov),
            "provenance_commit": prov[0].get("commit") if prov else None}


def adoption(system, name):
    """Real usage, not stars. Percentiles are 0-100, lower = more adopted."""
    reg = REGISTRIES.get(system)
    if not reg:
        return {}
    d = http(f"https://packages.ecosyste.ms/api/v1/registries/{reg}/packages/"
             f"{urllib.parse.quote(name, safe='')}")
    if not d:
        return {}
    r = d.get("rankings") or {}
    return {"dependent_repos": d.get("dependent_repos_count"),
            "dependent_packages": d.get("dependent_packages_count"),
            "downloads": d.get("downloads"),
            "pct_dependents": r.get("dependent_repos_count"),
            "pct_stars": r.get("stargazers_count")}


def advisories(ecosystem, name, version):
    """OSV by package coordinates. Withdrawn advisories are filtered, because the feed carries them."""
    pkg = {"name": name, "ecosystem": ecosystem}
    body = {"package": pkg, "version": version} if version else {"package": pkg}
    d = http("https://api.osv.dev/v1/query", payload=body)
    if d is None:
        return None  # query failed: unknown, not clean
    out, seen = [], set()
    for v in d.get("vulns", []):
        if v.get("withdrawn"):
            continue
        # The same vulnerability appears once per database. GO-2021-0052 and
        # GHSA-h395-qcrw-5vmq are one bug; without this the count is inflated.
        ids = {v["id"]} | set(v.get("aliases") or [])
        if ids & seen:
            continue
        seen |= ids
        out.append({"id": v["id"], "summary": (v.get("summary") or "")[:120],
                    "severity": _severity(v)})
    return out


def _severity(v):
    """GitHub's rating is the only one OSV ships in usable form. Anything else is unknown.

    OSV puts a CVSS *vector* in severity[].score, not a base score, so there is no
    number to read without implementing the CVSS formula. Go-database entries carry
    no rating at all. Calling those "low" would quietly downgrade a real bug.
    """
    s = ((v.get("database_specific") or {}).get("severity") or "").lower()
    return s if s in ("critical", "high", "moderate", "medium", "low") else "unknown"


# --- evidence gathering -----------------------------------------------------

def coordinates(owner, repo):
    """repo -> (deps.dev system, OSV ecosystem, package name). One listing call, then one read."""
    root = gh(f"/repos/{owner}/{repo}/contents")
    if not isinstance(root, list):
        return None
    present = {f["name"] for f in root if f.get("type") == "file"}
    for fname, (system, ecosystem, extract) in MANIFESTS.items():
        if fname not in present:
            continue
        blob = gh(f"/repos/{owner}/{repo}/contents/{fname}")
        if not isinstance(blob, dict) or not blob.get("content"):
            continue
        import base64
        try:
            text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
            name = extract(text)
        except Exception:
            name = None
        if name:
            return system, ecosystem, name
        return None, None, f"{fname} names no package (private root manifest, likely a monorepo)"
    for fname, eco in UNSUPPORTED.items():
        hit = (fname in present if "*" not in fname
               else any(f.endswith(fname[1:]) for f in present))
        if hit:
            return None, None, f"{eco} package ({fname}), ecosystem not supported yet"
    return None, None, "no recognised package manifest at the repo root"


def scorecard(owner, repo):
    """deps.dev project. Returns (project_dict, scorecard_or_None). Absent != failing."""
    pid = urllib.parse.quote(f"github.com/{owner}/{repo}", safe="")
    proj = http(f"https://api.deps.dev/v3alpha/projects/{pid}") or {}
    return proj, proj.get("scorecard")


def default_version(system, name):
    d = http(f"https://api.deps.dev/v3alpha/systems/{system}/packages/{urllib.parse.quote(name, safe='')}")
    if not d:
        return None
    for v in d.get("versions", []):
        if v.get("isDefault"):
            return v["versionKey"]["version"]
    return None


def version_facts(system, name, version):
    """isDeprecated + SLSA provenance for the default version."""
    if not version:
        return {}
    d = http(f"https://api.deps.dev/v3alpha/systems/{system}/packages/"
             f"{urllib.parse.quote(name, safe='')}/versions/{urllib.parse.quote(version, safe='')}")
    if not d:
        return {}
    prov = [p for p in (d.get("slsaProvenances") or []) if p.get("verified")]
    return {"deprecated": d.get("isDeprecated") or False,
            "deprecated_reason": d.get("deprecatedReason") or None,
            "provenance_verified": bool(prov),
            "provenance_commit": prov[0].get("commit") if prov else None}


def adoption(system, name):
    """Real usage, not stars. Percentiles are 0-100, lower = more adopted."""
    reg = REGISTRIES.get(system)
    if not reg:
        return {}
    d = http(f"https://packages.ecosyste.ms/api/v1/registries/{reg}/packages/"
             f"{urllib.parse.quote(name, safe='')}")
    if not d:
        return {}
    r = d.get("rankings") or {}
    return {"dependent_repos": d.get("dependent_repos_count"),
            "dependent_packages": d.get("dependent_packages_count"),
            "downloads": d.get("downloads"),
            "pct_dependents": r.get("dependent_repos_count"),
            "pct_stars": r.get("stargazers_count")}


def advisories(ecosystem, name, version):
    """OSV by package coordinates. Withdrawn advisories are filtered, because the feed carries them."""
    pkg = {"name": name, "ecosystem": ecosystem}
    body = {"package": pkg, "version": version} if version else {"package": pkg}
    d = http("https://api.osv.dev/v1/query", payload=body)
    if d is None:
        return None  # query failed: unknown, not clean
    out, seen = [], set()
    for v in d.get("vulns", []):
        if v.get("withdrawn"):
            continue
        # The same vulnerability appears once per database. GO-2021-0052 and
        # GHSA-h395-qcrw-5vmq are one bug; without this the count is inflated.
        ids = {v["id"]} | set(v.get("aliases") or [])
        if ids & seen:
            continue
        seen |= ids
        out.append({"id": v["id"], "summary": (v.get("summary") or "")[:120],
                    "severity": _severity(v)})
    return out


def _severity(v):
    """GitHub's rating is the only one OSV ships in usable form. Anything else is unknown.

    OSV puts a CVSS *vector* in severity[].score, not a base score, so there is no
    number to read without implementing the CVSS formula. Go-database entries carry
    no rating at all. Calling those "low" would quietly downgrade a real bug.
    """
    s = ((v.get("database_specific") or {}).get("severity") or "").lower()
    return s if s in ("critical", "high", "moderate", "medium", "low") else "unknown"


def _cvss_band(sev):
    m = re.search(r"/?(\d+\.\d+)$", str(sev.get("score", "")))
    if not m:
        return None
    s = float(m.group(1))
    return "critical" if s >= 9 else "high" if s >= 7 else "medium" if s >= 4 else "low"


def _db_severity(v):
    gh_sev = ((v.get("database_specific") or {}).get("severity") or "").lower()
    return gh_sev or None


# --- verdict (pure, self-tested) --------------------------------------------

def verdict(ev):
    """Cheap disqualify pass. Returns (state, reasons). Pure function of gathered evidence."""
    reject, concern = [], []
    m = ev.get("meta") or {}

    if m.get("archived"):
        reject.append("archived, so no patches will ship")
    if m.get("fork") and m.get("parent"):
        reject.append(f"fork of {m['parent']}, evaluate the parent instead")
    if not m.get("license"):
        reject.append("no license, not safe to depend on")

    advs = ev.get("advisories") or []
    bad = [a["id"] for a in advs if a.get("severity") in ("critical", "high")]
    unknown = [a["id"] for a in advs if a.get("severity") == "unknown"]
    rest = len(advs) - len(bad) - len(unknown)
    if bad:
        reject.append(f"unpatched advisory in current version, {', '.join(bad[:3])}")
    if unknown:
        concern.append(f"advisory with no published severity, judge it yourself, "
                       f"{', '.join(unknown[:3])}")
    if rest:
        concern.append(f"{rest} lower-severity advisor{'y' if rest == 1 else 'ies'}")

    d = m.get("stale_days")
    if d is not None and d > STALE_DAYS and not m.get("archived"):
        concern.append(f"no push in {d} days")
    if (ev.get("version") or {}).get("deprecated"):
        concern.append("package marked deprecated upstream")

    failed = ev.get("failed_security_checks") or []
    if failed:
        concern.append("scorecard: " + ", ".join(f"{k} {v}" for k, v in failed))

    state = "reject" if reject else ("concerns" if concern else "ok")
    return state, reject + concern


def security_state(ev):
    """Three states, never two. `not assessed` is the honest answer on most small repos.

    A null advisories field means the vulnerability check never ran, so the result
    cannot be "no known issues" no matter how much other evidence exists. React,
    guzzle and symfony/http-client all have a Scorecard and no resolvable package,
    and every one of them read as clean before this branch was ordered correctly.
    """
    if ev.get("advisories"):
        return "vulnerable"
    if ev.get("advisories") is None:
        return "not assessed"
    if ev.get("failed_security_checks"):
        return "hygiene concerns"
    return "no known issues"


# --- per-repo orchestration -------------------------------------------------

def probe(slug):
    owner, _, repo = slug.partition("/")
    ev = {"repo": slug}

    r = gh(f"/repos/{owner}/{repo}")
    if not isinstance(r, dict):
        return {"repo": slug, "state": "error", "reasons": ["repo not found or gh unauthenticated"]}
    ev["meta"] = {
        "stars": r.get("stargazers_count"), "forks": r.get("forks_count"),
        "archived": r.get("archived"), "fork": r.get("fork"),
        "parent": (r.get("parent") or {}).get("full_name"),
        "license": (r.get("license") or {}).get("spdx_id"),
        "pushed_at": r.get("pushed_at"), "stale_days": days_since(r.get("pushed_at")),
        "description": r.get("description"), "watchers": r.get("subscribers_count"),
    }

    proj, sc = scorecard(owner, repo)
    if sc:
        ev["scorecard_overall"] = sc.get("overallScore")
        ev["scorecard_date"] = sc.get("date")
        # -1 means the check did not run. Never average, never treat as zero.
        failed = [(c["name"], c["score"]) for c in sc.get("checks", [])
                  if c["name"] in REPORTED_CHECKS and 0 <= c.get("score", -1) < 5]
        ev["failed_security_checks"] = [f for f in failed if f[0] in RISK_CHECKS]
        ev["scorecard_notes"] = [f for f in failed if f[0] not in RISK_CHECKS]
    else:
        ev["scorecard_overall"] = None
        ev["scorecard_date"] = None
        ev["failed_security_checks"] = []
        ev["scorecard_notes"] = []

    coords = coordinates(owner, repo) or (None, None, "could not list the repo root")
    system, ecosystem, name = coords
    if system:
        version = default_version(system, name)
        ev["package"] = {"system": system, "ecosystem": ecosystem, "name": name, "version": version}
        ev["version"] = version_facts(system, name, version)
        ev["adoption"] = adoption(system, name)
        # No default version means the manifest names a package no registry
        # publishes. OSV answers {} for an unknown package, identical to
        # "clean". Refusing to ask is the only way to avoid a false all-clear.
        ev["advisories"] = advisories(ecosystem, name, version) if version else None
        if not version:
            ev["package_reason"] = f"{name} is not published on {ecosystem}"
    else:
        ev["package"] = None      # publishes no package: OSV has no opinion
        ev["package_reason"] = name
        ev["version"] = {}
        ev["adoption"] = {}
        ev["advisories"] = None   # None = unknown. [] = checked and clean.

    a = ev.get("adoption") or {}
    ps, pd = a.get("pct_stars"), a.get("pct_dependents")
    if ps is not None and pd is not None and abs(ps - pd) > 10:
        ev["stars_disagree"] = (
            f"stars percentile {ps:.1f} vs dependents percentile {pd:.1f}, "
            + ("more starred than used" if ps < pd else "more used than starred"))

    ev["state"], ev["reasons"] = verdict(ev)
    ev["security"] = security_state(ev)
    return ev


def search(query, limit):
    p = subprocess.run(["gh", "search", "repos", query, "--limit", str(limit),
                        "--json", "fullName"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"gh search failed: {p.stderr.strip()}")
    return [r["fullName"] for r in json.loads(p.stdout)]


# --- self-check -------------------------------------------------------------

def selftest():
    ok = {"meta": {"license": "MIT", "stale_days": 10}, "advisories": [], "scorecard_date": "x"}
    assert verdict(ok)[0] == "ok", verdict(ok)

    arch = {"meta": {"license": "MIT", "archived": True, "stale_days": 900}, "advisories": []}
    st, why = verdict(arch)
    assert st == "reject" and "archived" in why[0], (st, why)
    # archived must not also report staleness. One reason, not two for the same fact
    assert not any("no push" in r for r in why), why

    fork = {"meta": {"license": "MIT", "fork": True, "parent": "a/b", "stale_days": 1}, "advisories": []}
    assert verdict(fork)[0] == "reject" and "a/b" in verdict(fork)[1][0]

    crit = {"meta": {"license": "MIT", "stale_days": 1},
            "advisories": [{"id": "GHSA-x", "severity": "critical"}]}
    assert verdict(crit)[0] == "reject" and "GHSA-x" in verdict(crit)[1][0]

    low = {"meta": {"license": "MIT", "stale_days": 1},
           "advisories": [{"id": "GHSA-y", "severity": "low"}]}
    assert verdict(low)[0] == "concerns", verdict(low)

    nolic = {"meta": {"stale_days": 1}, "advisories": []}
    assert verdict(nolic)[0] == "reject"

    stale = {"meta": {"license": "MIT", "stale_days": 900}, "advisories": []}
    assert verdict(stale)[0] == "concerns" and "900 days" in verdict(stale)[1][0]

    # -1 checks must never be reported as failures (express carries two)
    ev = {"scorecard_overall": 8.5,
          "failed_security_checks": [(n, s) for n, s in
                                     [("Signed-Releases", -1), ("Token-Permissions", 0)]
                                     if 0 <= s < 5]}
    assert ev["failed_security_checks"] == [("Token-Permissions", 0)]

    # three security states
    assert security_state({"advisories": [{"id": "x"}]}) == "vulnerable"
    assert security_state({"advisories": [], "failed_security_checks": [("a", 0)]}) == "hygiene concerns"
    assert security_state({"advisories": None, "scorecard_date": None}) == "not assessed"
    assert security_state({"advisories": [], "scorecard_date": "2026-08-17",
                           "failed_security_checks": []}) == "no known issues"
    # A Scorecard does not make an unchecked package clean. This read "no known
    # issues" for React, guzzle and symfony until the branches were reordered.
    assert security_state({"advisories": None, "scorecard_date": "2026-08-17",
                           "failed_security_checks": []}) == "not assessed"

    # OSV ships a CVSS vector, not a score, so only GitHub's rating is readable.
    assert _severity({"database_specific": {"severity": "CRITICAL"}}) == "critical"
    assert _severity({"severity": [{"score": "CVSS:3.1/AV:N/AC:L/C:H/I:H/A:H"}]}) == "unknown"
    assert _severity({}) == "unknown"

    # An unrated advisory must be named, never folded into a "lower-severity" count.
    unk = {"meta": {"license": "MIT", "stale_days": 1},
           "advisories": [{"id": "GO-2021-0052", "severity": "unknown"}]}
    st, why = verdict(unk)
    assert st == "concerns" and "GO-2021-0052" in why[0], (st, why)
    assert "lower-severity" not in " ".join(why), why

    # Hygiene-only scorecard failures must not raise a concern on their own.
    assert verdict({"meta": {"license": "MIT", "stale_days": 1}, "advisories": [],
                    "scorecard_notes": [("Branch-Protection", 0)]})[0] == "ok"

    # The false-clean gate: OSV returns {} for a package no registry publishes,
    # which is byte-identical to "clean". Unresolvable version => never ask.
    assert security_state({"advisories": None, "scorecard_date": None,
                           "package": {"version": None}}) == "not assessed"

    print("selftest ok")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if args[0] == "--selftest":
        return selftest()
    if args[0] == "--search":
        limit = 10
        if "--limit" in args:
            limit = int(args[args.index("--limit") + 1])
        slugs = search(args[1], limit)
    else:
        slugs = args
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(probe, slugs))
    json.dump(results, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
