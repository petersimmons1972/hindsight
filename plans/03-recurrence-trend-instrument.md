# PLAN-03 — measure whether recurrence actually drops
Issue: petersimmons1972/hindsight#29 · Status: BLOCKED — founder measurement-input ruling, then serial split · Blocked-by: R3/D2/D4 scope contradiction · Blocks: X4, X6

## 1. CONTEXT YOU DO NOT HAVE

The doctrine spine this repo serves (`~/projects/ops-plans/three-laws.md`) ends on a terminal
question: **"Does mechanizing rules reduce failure, or relocate it?"** Nothing measures the answer,
and with the tools on `main` today nothing *can*: post-hoc matching of a new entry to an old family
runs on a clusterer measured at **1/77** blind-paraphrase recall. This plan builds the instrument.
It is deliberately scheduled early — pre-registration must precede the mechanisms it will judge, or
the analysis is retrofitted, and this repo's own C3 measurement refused exactly that.

## 2. REPO FACTS

```
Repo:        /home/psimmons/projects/hindsight
Branch from: main    Work on: feat/recurrence-trend-instrument
Existing artifacts: pipeline/L2/clusters.jsonl (pinned) · pipeline/L2/recurrence-report.md
                    qa-ledger/actor-results.jsonl · catalog/failure-modes.md
Green baseline: pytest 167, bats 92, guard OK (171 IDs), reconcile COMPLETE 5/5.
```

## 3. GOAL

Ship `pipeline/recurrence_trend.py` plus a **pre-registration committed before any post-period data
exists**, such that the terminal question gets an answer in one of three named directions —
including the negative one.

- **Unit:** a cause family (`c-NNN`, or hand-declared where the clusterer under-reports).
- **Intervention:** a mechanism ship event in `pipeline/recurrence/mechanisms.jsonl` —
  `{family, mechanism_path, ship_commit, ship_date, fire_counter_path}`.
- **Outcome:** new instances per 30 days **per 100 entries logged corpus-wide**, pre vs post.

## 4. DEFINITION OF DONE

- **D1** `pipeline/recurrence/PREREG.md` is committed **before** any post-period data is collected,
  naming: the families under test, one matched comparator family of similar size with no mechanism,
  the exposure proxy, and the decision rule below verbatim.
- **D2** Every mechanism counts its own firings, appended to `pipeline/enforcement/fired.jsonl`.
  **Without this a post-period zero is unfalsifiable** — "prevented it" and "never ran" are
  indistinguishable.
- **D3** A family whose mechanism never fired is **excluded from the numerator and reported as
  UNEXERCISED**, never as a success. Exit 1 if any family under test lacks a fire count.
- **D4** Bypasses are counted too — `--force-*` overrides, disabled steps, `continue-on-error`,
  skips. *A mechanism whose override rate rises while its violation rate falls is relocating
  failure into the override.* This is the only direct evidence the RELOCATED arm will ever have.
- **D5** The report prints **raw count and share-of-corpus together**. Pre-registered reading: **a
  drop in raw count with a flat share is NOT evidence of reduction** — it means logging slowed.
- **D6** Instrument validated before use (FM-153): `pipeline/tests/fixtures/recurrence_trend_synthetic.jsonl`
  carries an injected known drop **and a known-flat family**; the tool must recover **both**. A tool
  that only detects drops will detect one in noise.
- **D7** The report prints its own limitations, as the recurrence report already prints its recall
  limit.

**Decision rule, pre-registered:**
- **REDUCED** — post-period share ≤50% of pre-period for ≥2 test families, over ≥90 days post with
  ≥50 post-period entries, **and** each mechanism fired ≥1 time, **and** the comparator did not drop
  as much.
- **RELOCATED** — the targeted family's share drops while corpus-wide share is flat or rising,
  **and** ≥1 new family appears caused by a mechanism being bypassed or misconfigured.
- **UNDERPOWERED** — neither threshold met, or mechanisms did not fire. **Report the negative with
  the same weight as a positive and do not re-cut the windows.** Re-cutting is fitting the
  evaluation set.

## 5. NON-NEGOTIABLES

*Verbatim from `docs/INVARIANTS.md` §5.*

- **R1 Red first, and prove the red.**
- **R2 Both directions, always.**
- **R3 Ground-truth fixtures are coordinator-authored**, committed before the packet is dispatched.
- **R4 Empty / zero / missing input must FAIL LOUD.** The two zeros must be distinguishable.
- **R5 No exit status through a pipe.**
- **FM-153** Validate the instrument against known-good and known-bad before trusting its count.
- **FM-155** A count must measure units of work PERFORMED, never units merely PRESENT.

## 6. PROHIBITIONS

*Verbatim from `docs/INVARIANTS.md` §6, plus one specific to this plan.*

- **NEVER delete a catalog row or L1 record**; **NEVER regenerate `catalog/id-ledger.txt`.**
- **An `enforcement` value of `null` is a CORRECT answer.** Never invent a test or hook path to fill the field. A fabricated mechanism is worse than an honest gap, because it reads as covered.
- **NEVER relax a test to make a change pass.** **NEVER edit `conf/` or `pipeline/L1/` to pass a check.**
- **NEVER read a command's exit status through a pipe** (CI-17).
- **NEVER modify a file not listed in §7.**
- **NEVER adjust the decision rule, the windows, or the family list after seeing any post-period
  number.** If the rule turns out to be wrong, say so and stop — do not re-cut.

## 7. FILES YOU MAY TOUCH

```
/home/psimmons/projects/hindsight/pipeline/recurrence_trend.py
/home/psimmons/projects/hindsight/pipeline/recurrence/PREREG.md
/home/psimmons/projects/hindsight/pipeline/recurrence/mechanisms.jsonl
/home/psimmons/projects/hindsight/pipeline/tests/test_recurrence_trend.py
/home/psimmons/projects/hindsight/pipeline/tests/fixtures/recurrence_trend_synthetic.jsonl
```

## 8. RED-FIRST PROCEDURE

Write `test_recurrence_trend.py` against the synthetic fixture **first**; run it and observe every
test fail on absence. Paste that run. Only then implement.

## 9. ACCEPTANCE COMMANDS

| # | command | expected |
|---|---|---|
| A1 | `python3 pipeline/recurrence_trend.py --prereg pipeline/recurrence/PREREG.md; echo "exit=$?"` | per-family pre/post **with denominators and fire counts** |
| A2 | `python3 pipeline/recurrence_trend.py --prereg … --families-missing-fire-count` | exit 1 (D3) |
| A3 | `python3 -m pytest pipeline/tests/test_recurrence_trend.py -q` | all pass; both synthetic families recovered (D6) |
| A4 | `python3 pipeline/recurrence_trend.py --input /dev/null; echo "exit=$?"` | non-zero, names the empty input (R4) |
| A5 | `grep -ci 'limitation\|not causal\|directional' <report>` | ≥1 (D7) |
| A6 | `python3 -m pytest guard/tests/ pipeline/tests/ -q` | ≥167 passed |
| A7 | `git diff --numstat origin/main...HEAD -- pipeline/L1 catalog conf` | **empty** |

## 10. MUTATION REQUIREMENT

- **M1** UNEXERCISED families counted as successes → D3's test must die.
- **M2** share-of-corpus dropped, leaving raw counts only → D5's test must die.
- **M3** the known-flat synthetic family reported as a drop → D6's test must die.

Report survivors explicitly.

## 11. UNDO

```bash
cd /home/psimmons/projects/hindsight && git checkout -- pipeline/ && \
  git checkout main && git branch -D feat/recurrence-trend-instrument
```

## 12. ESCALATE INSTEAD OF GUESSING

- **This packet is BLOCKED pending a founder measurement-input ruling.** Name all four inputs
  before any implementation dispatch: (1) the families under intervention, (2) one
  similar-sized no-mechanism comparator, (3) the authoritative corpus-wide exposure proxy, and
  (4) the real mechanism owners and counter paths permitted to record firings and bypasses.
  `qa-ledger/actor-results.jsonl`, GitHub run counts, and dispatch counts are not authoritative
  exposure evidence merely because they are available.
- **Why this cannot be inferred:** selecting the families, comparator, windows, or denominator
  after observing outcomes retrofits the analysis; `enforcement: null` is an honest result; and
  inventing a counter path would fabricate the direct evidence required for `RELOCATED`. The
  absent `pipeline/enforcement/fired.jsonl` is outside §7, so creating it in this packet violates
  §6 rather than resolving D2/D4.
- **Fixture ownership conflict:** R3 requires the synthetic acceptance fixture to be
  coordinator-authored and committed before implementation dispatch, but §7/§8 currently assign
  that sole fixture to the executor. Do not dispatch this packet under that contradiction.
- **Required serial resolution after the ruling:** first a coordinator-owned preregistration and
  ground-truth-fixture packet; second a counter/bypass-instrumentation packet touching the real
  mechanism owners and ledger; third this analyzer, reduced to consume those committed inputs.
  No post-period data is to be interpreted, and no decision rule re-cut, between those packets.
- The exposure proxy you need is not among `qa-ledger/actor-results.jsonl`, `gh run list` counts, or
  dispatch counts.
- Back-filling `recurrence_of` for pre-existing entries would require judgment calls you cannot
  make from the record alone.
- Any post-period number would change what you want the decision rule to say — **stop and report**;
  that is the exact moment the measurement is at risk.

## 13. REPORT FORMAT

First line **literally** `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`, then baselines, the
red-first run, §9 actual-vs-expected, §10 results, `git diff --stat`.

## 14. DISPATCH PROMPT

```
Work in /home/psimmons/projects/hindsight on branch feat/recurrence-trend-instrument off main.
Read /home/psimmons/projects/hindsight/plans/03-recurrence-trend-instrument.md in full and execute it
exactly as written. It is self-contained. Modify ONLY the five files in section 7. The decision rule
in section 4 is PRE-REGISTERED: you may not alter it, the windows, or the family list at any point.
Complete section 8 first and paste the failing run. Run every command in section 9 verbatim.
Do not merge, push to main, or open a PR.
Your first line of output must be exactly `VERDICT: CONFIRMED_GOOD` or `VERDICT: DEFECTIVE`.
```
