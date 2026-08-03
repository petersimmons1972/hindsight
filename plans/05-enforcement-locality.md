# PLAN-05 — each repo verifies its own enforcement claims
Issue: petersimmons1972/hindsight#20 · Also closes PR #12 · Status: BLOCKED by 04 · Founder-approved design

## 1. CONTEXT YOU DO NOT HAVE

`hindsight`'s L1 corpus records, per failure mode, an `enforcement` path claimed to prevent it —
paths that live in **13 different source repos**. `--verify-enforcement` tries to check them from
inside hindsight. On CI only 1 of 13 roots resolves and it verifies zero paths, so phantom discovery
runs **nowhere** automatically.

Six rounds (C4a–C4f) tried to close this from inside hindsight and each round's fix moved the bypass
rather than removing it — through **five layers**: data → config → control flow → environment →
scope. **The bypass got shorter each round: 3 config files, then 1 file, then 0 for an honest tree.**
When the bypass shortens, the design is wrong. The structural reason is simple: **hindsight cannot
see another repo's filesystem.** No seventh round fixes that.

**Founder decision 2026-08-02: relocate.** Reach follows context (Law 2). Each source repo verifies
its own claims; hindsight asserts the result exists and is fresh.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight
Branch from: main    Work on: feat/20-enforcement-locality
Depends on:  plan 04's repaired sync channel — it is the transport for the self-check
Relevant:    guard/failure_mode_catalog_guard.py --verify-enforcement · conf/source-roots.conf
             conf/known-phantoms.conf · pipeline/L1/*.jsonl (13 sources)
```

## 3. GOAL

Move the check to where the paths are. Each consumer receives a small self-check that verifies **its
own** claimed enforcement paths and writes a dated, signed-by-content result. hindsight's CI stops
pretending to run the check and instead **fails unless the attestation exists, is fresh, and its
digest matches the working tree.**

## 4. DEFINITION OF DONE

- **D1** `.hindsight/verify-my-enforcement.py` is distributed by plan 04's channel to each consumer;
  it checks only that repo's entries and writes `attestation.json` with timestamp, host, commit,
  measured counts, and a `config_digest` over the exact bytes of every scope-defining input.
- **D2** hindsight gains `--require-attestations --max-age-days N`: exit 1 when any consumer's
  attestation is **missing or stale**. A freshness assertion is a genuine gate; a check that only
  fires where nobody is required to run is not.
- **D3** **The digest covers the config.** Repointing `conf/source-roots.conf` changes the digest, so
  CI demands a fresh real run — which on a populated workstation immediately reports `checked: 0`
  and fails the floor. This is the load-bearing idea; without it the one-file decoy attack returns.
- **D4** Regeneration is **easier than editing the config** (a pre-commit hook). *A gate that is
  painful gets disabled, and then there is no gate.*
- **D5** Floors count units **performed**, never units present (FM-155), and are **monotonic**:
  lowering one requires an explicit flag and a recorded reason.
- **D6** The one-file decoy attack is pinned by a test: repoint all non-SELF roots to non-existent
  decoys → the check must **fail**, in both environments (FM-158).
- **D7** **Deliberate hash forgery is explicitly out of scope and stated as such** in the docs — not
  implied away. The threat being closed is the ordinary edit, the lazy shortcut, the routine
  optimization.
- **D8** PR #12 is closed with the measured evidence **only after this lands**, so the capability
  moves rather than evaporates.

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.** **R2 Both directions, always.**
- **R4 Empty / zero / missing input must FAIL LOUD.** The two zeros must be distinguishable.
- **R5 No exit status through a pipe.** **R6 Undo journal before writing.**
- **R8 Dispatches are serial in this repo.** **R9 No `--apply` against anything real.**
- **FM-155** A floor must count units of work PERFORMED, never units merely PRESENT.
- **FM-158** Every mutation runs in BOTH environments; a result from one environment is not a result.

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6, plus two specific to this history.*

- **NEVER edit `conf/` to make a check pass.** Editing scope-defining config to reach green is the
  documented attack on this exact tool.
- **NEVER edit `pipeline/L1/` to make a check pass.** That is FM-154 — the defect that produced this
  campaign's headline finding.
- **NEVER let the check exit 0 after checking nothing.** If it cannot verify anything real, it must
  **SKIP loudly** and say what it did not check.
- **NEVER delete a catalog row or L1 record**; **NEVER regenerate `catalog/id-ledger.txt`.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER relax a test to make a change pass.**
- **NEVER read a command's exit status through a pipe** (CI-17).
- **NEVER modify a file not listed in §7.** **Do not merge, push to `main`, or open a PR.**

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/guard/failure_mode_catalog_guard.py
/home/psimmons/projects/hindsight/guard/tests/test_attestations.py
/home/psimmons/projects/hindsight/consumer/verify-my-enforcement.py
/home/psimmons/projects/hindsight/attestation/README.md
/home/psimmons/projects/hindsight/.github/workflows/guard.yml
```

## 8. RED-FIRST PROCEDURE

Reproduce the one-file decoy on the current tree: repoint all non-SELF roots in
`conf/source-roots.conf` to non-existent decoys, keep the SELF root so `resolved_count != 0`, and
observe **CI-shape exit 0 with stderr byte-identical to the honest baseline**. **Restore
`conf/source-roots.conf` immediately** via `git checkout --`. Paste both. That is the red.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | `python3 consumer/verify-my-enforcement.py --write /tmp/att.json; echo "exit=$?"` | 0; attestation carries counts + `config_digest` |
| A2 | `python3 guard/failure_mode_catalog_guard.py --require-attestations --max-age-days 14; echo "exit=$?"` | 1 while consumers have none (honest red) |
| A3 | *decoy roots applied* → `--require-attestations` | **exit 1** (D3/D6) |
| A4 | `touch -d '30 days ago' <att>; … --max-age-days 14` | exit 1, names the stale consumer |
| A5 | `git checkout -- conf/ && git status --porcelain conf/` | **empty — config restored** |
| A6 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥181 passed |
| A7 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf` | **empty** |
| A8 | `gh pr view 12 --json state --jq .state` *(only after this lands)* | `CLOSED`, with the measured evidence posted (D8) |
| A9 | `bats guard/tests/*.bats bin/tests/*.bats` | ≥109 ok, 0 failures |

## 10. MUTATION REQUIREMENT

Run each in **both** environments (FM-158):

- **M1** drop `config_digest` from the attestation → D3's test must die.
- **M2** treat a missing attestation as fresh → D2's test must die.
- **M3** let a floor be lowered without the explicit flag → D5's test must die.
- **M4** make the freshness check exit 0 when zero consumers are configured → R4's test must die.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight
git checkout -- conf/ guard/ .github/ && rm -rf consumer/ attestation/
git checkout main && git branch -D feat/20-enforcement-locality
```

## 12. ESCALATE INSTEAD OF GUESSING

- Closing D3 appears to require editing `conf/` as part of the *solution* rather than the test.
- The design needs a consumer repo to be modified before plan 04's channel exists.
- You find a **sixth** bypass layer — report it; that finding is worth more than the fix.
- Any acceptance step would leave `conf/` dirty.

## 13. REPORT FORMAT

First line **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`, then the §8 decoy
reproduction **and its restoration**, §9 actual-vs-expected, §10 both-environment results,
`git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch feat/20-enforcement-locality off main.
Read /home/psimmons/projects/hindsight/plans/05-enforcement-locality.md in full and execute it exactly
as written. It is self-contained. Modify ONLY the five files in section 7.
Six previous rounds failed by patching this check from inside this repo; do not attempt a seventh.
The design is relocation plus a freshness assertion. If the check cannot verify anything real it must
SKIP LOUDLY -- it may never exit 0 after checking nothing. Restore conf/ after the section 8 red.
Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
