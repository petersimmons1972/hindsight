# plans/ — index

Each file is **self-contained** and executable by a model with zero conversational context:

```bash
codex exec "$(cat plans/01-enforcement-disclosure.md)"
```

`~/.codex/config.toml` sets `model = "gpt-5.6-terra"`, so no model flag is needed. Each plan's §14 is
a copy-pasteable dispatch prompt if you prefer to hand over the path rather than the contents.

## Ceiling

**Target (advisory): ≤250 lines · ≤12 KB · ≤6 paths in §7 · exactly 1 issue.** Reviewers apply
this as a sizing target; a §7 directory entry authorises its subtree at one line of count, so the
path count is not a hard blast-radius bound. `bin/check-plan-preamble.sh` still checks structure
and warns when the path-count target is exceeded.

Justified by this repo's own record, not by taste: the packets that passed on the first attempt were
single-file, single-contract. The packets that took **five and six rounds** each spanned `guard/` +
`conf/` + `.github/workflows/` at once, and the defect in every round sat at a **seam** between them.
A unit that does not fit is two units, and the split point is usually the seam that would otherwise
have produced the defect.

## The plans

| # | file | issue | status | blocked-by | blocks |
|---|---|---|---|---|---|
| 01 | `01-enforcement-disclosure.md` | #18 | COMPLETE — PR #27 merged; main guard green | — | — |
| 02 | `02-ingest-consults-corpus.md` | #19 | COMPLETE — PR #28 merged; main guard green | — | — |
| 03 | `03-recurrence-trend-instrument.md` | #29 | **WITHDRAWN 2026-08-03** — rejected on validity (Codex) and worth (Grok); `docs/DECISIONS.md` rows 22–26 | — | — |
| 04 | `04-sync-repair-and-distribute.md` | #22 (closes #24) | FOUNDER-BLOCKED — founder ruling on #22 (2026-08-04) sets dry-run-only scope; #24 closed, superseded by the ruling; PR stack (#40/#41/#43/#46) rejected per review at #22 | — | 05 |
| 05 | `05-enforcement-locality.md` | PR #12 | BLOCKED — issue #20 closed with packet 20-1 / PR #52; remaining locality work is held behind 04 | 04 | — |
| 06 | `06-l3-invariant-ledger.md` | #21 | FOUNDER-BLOCKED — coordinator fixture is merged (#63); W1/W2 artifact contract unresolved per #21; no founder ruling recorded on #21 yet | — | — |
| 07 | `07-discriminating-rebuild.md` | #23 | FOUNDER-BLOCKED — founder ruling on #23 (2026-08-04) replaces the withdrawn discriminator with a supported-shape gate; PR #48 rejected, could not discriminate import-only files | — | — |
| 08 | `08-reconcile-partial-is-not-pass.md` | #25 | COMPLETE — PR #26 merged, main green | — | — |

Recommended order is `08 → 01 → 02 → 03 → 04 → 05 → 06 → 07`; the rationale is in `../PLAN.md`.

**Automation:** packets ready for unattended `cli-dispatch` are specified in `AUTOMATION-QUEUE.md`,
with per-packet briefs under `briefs/`. Re-measure before trusting any `Status:` header in this
table — several were found stale on 2026-08-03.
**03 is WITHDRAWN as of 2026-08-03** — skip it; the slot is not refilled.
**Serial only** (R8): one dispatch in flight in this repo at a time, and no writes to the shared
checkout while one is running.

## Every plan has the same 14 sections

Each earns its place against a measured failure in this repo — none is decoration.

| § | section | what it defends against |
|---|---|---|
| 1 | CONTEXT YOU DO NOT HAVE | replaces the conversation the executor never had |
| 2 | REPO FACTS | a mid-tier model that explores burns its budget and then guesses |
| 3 | GOAL | — |
| 4 | DEFINITION OF DONE | every row must have a command in §9 |
| 5 | NON-NEGOTIABLES *(verbatim)* | drift between copies — lint-enforced |
| 6 | PROHIBITIONS *(verbatim)* | inventing an `enforcement:` path to fill a field |
| 7 | FILES YOU MAY TOUCH | blast radius (Law 2) |
| 8 | RED-FIRST PROCEDURE | CI-18, hit three times here |
| 9 | ACCEPTANCE COMMANDS | "verified" as a claim rather than an artifact |
| 10 | MUTATION REQUIREMENT | a green suite that would never go red — measured at 62% mutant survival |
| 11 | UNDO | Law 3 |
| 12 | ESCALATE INSTEAD OF GUESSING | silent scope widening |
| 13 | REPORT FORMAT | 16 of 31 verify actors emitted no verdict line and were unlandable |
| 14 | DISPATCH PROMPT | — |

## Two rules that outrank convenience

**§5 and §6 are copied byte-for-byte from `../docs/INVARIANTS.md`.** Change a rule there, then
re-run the lint and update every plan in the same commit. Decomposition without that lint recreates
this repo's origin story: two copies of a governance artifact, both edited, both drifting.

**A plan is not done because its author says so.** §13's verdict line is what the landing gate
matches on, and §9/§10 are what make the verdict checkable by someone who was not there.
