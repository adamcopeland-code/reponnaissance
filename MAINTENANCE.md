# Maintenance

This repo is instructions plus one stdlib script. Almost nothing here can rot on
its own. What can rot is everything it points at, so maintenance is a detection
problem, not a scheduling problem.

## What can break, in likelihood order

1. **deps.dev.** The probe uses the `v3alpha` endpoint, and alpha means the shape
   can change without notice. This is the most likely failure.
2. **The acceptance fixtures.** `fiatjaf/khatru` could be unarchived or deleted,
   and the `macko76/ossf-scorecard` fork could vanish. The fixtures are real
   repos on purpose, which means they age like real repos.
3. **ecosyste.ms and OSV** response shapes, and `gh` CLI output.
4. **Ecosystem coverage.** Packagist, Maven, NuGet and RubyGems are genuinely
   unreachable through the current probe (found in adversarial testing, not
   guessed). Adding one is real work with its own registry quirks, so each lands
   as a deliberate change with its own tests, not a quick patch. Until then,
   repos in those ecosystems read `not assessed`, which is the honest answer.
   Swift is its own case: no vulnerability database covers Swift packages at
   all (deps.dev 404s, OSV's Swift ecosystem is empty), so on Apple work the
   probe gives maintenance, license and archive signal only, and says so.
   Adoption is now read for these ecosystems, by looking the repository URL up
   on ecosyste.ms: Alamofire reports 29,917 dependent repos through CocoaPods
   and guzzle 357,489 through Packagist. Security stays `not assessed`, because
   adoption is not safety. What is still missing for Apple work is only the
   vulnerability source, and none exists to wire up.
5. **The trigger description** in `SKILL.md` frontmatter. This one improves with
   use rather than breaking. When the skill fails to trigger on a phrasing it
   should catch, add the phrasing.

## How breakage is detected

`.github/workflows/live-check.yml` runs the offline selftest and the live
acceptance pair on every push and on the 3rd of each month. A red run means an
upstream API drifted or a fixture aged out. Both are usually a ten minute fix.
There is no other monitoring and none is needed.

## Response policy

- A red live-check gets diagnosed within days, not weeks. If an upstream API is
  gone for good, the probe drops that signal honestly (`not assessed`) rather
  than faking it.
- Issues and pull requests are welcome. Small fixes merge fast. Anything that
  changes what the verdict claims gets the same scrutiny as the original build:
  every constraint in `SPEC.md` exists because we hit the failure it prevents.

## Releases

Tag a release when behavior changes, not on a schedule. Docs-only changes do not
get a tag.
