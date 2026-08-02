# QA model panel — does the model change what QA finds?

*Founder-directed, 2026-08-02: "we should measure the QA effects of other AI models on QA."*

## Design

Five models, **one identical brief** (`briefs/QA-panel-verify.md`), **one identical artifact**, one
rubric. The only variable is the model.

The artifact is not synthetic. It is `bin/similar-causes.py` pinned at commit `c0f8c95` — the state
where it **passed its 27-test acceptance suite and was nonetheless DEFECTIVE**. Its defects were
later found by a three-lens opus verification, documented, and encoded as tests, which gives a
**labelled ground-truth set**:

| id | known defect class |
|---|---|
| K1 | encoding-based exit oracle (`UnicodeEncodeError` on the match path ⇒ exit differs by match) |
| K2 | broken-pipe oracle (`\| head -1` ⇒ exit 120 on match, 0 on no-match) |
| K3 | ANSI/control characters erase the mandated header, forged duplication verdict rendered |
| K4 | newline-forged candidate rows (defeat the cap, invert score order, fake provenance) |
| K5 | silent partial corpus load (309 of 475 records dropped, zero bytes on stderr) |
| K6 | UTF-8 BOM silently discards the first record of a file |

Every lane was blind: none was told what to look for.

## Results

| model | vendor | findings | known classes | novel | protocol |
|---|---|---|---|---|---|
| **opus** | anthropic | 4 | **K1, K3/K4, K5** (3) | `--corpus` echoed on error path | ✅ verdict first |
| **grok** | xai | 4 | K3, K4 (2) | **empty `--corpus=` → cwd (LIVE)**, option-shaped query | ✅ verdict first |
| **codex** | openai | 2 | K3/K4 (1) | header absent on error path (contestable) | ✅ + structured block |
| **sonnet** | anthropic | 2 | **none** (0) | `-h/--help` exits 0 without the header | ❌ prose first |
| **haiku** | anthropic | 1 | K4, weak form (1) | — | ❌ prose first |

Nobody found **K2** (broken-pipe) or **K6** (BOM) in a single lane. Both were originally found by
*specialised* lenses in the three-lens run.

## What the measurement says

**1. Capability tiers separate sharply, and not gracefully.** opus 3 known classes, haiku 1, sonnet
**0**. Sonnet's single HIGH is contract-lawyering — `--help` is a usage path, not a lookup, so the
advisory header's absence there is arguably correct behaviour. A cheap tier did not produce a
*smaller* version of the same review; it produced a review of something else. **Do not tier down
adversarial verification.** Tiering down bounded mechanical work remains fine.

**2. Cross-vendor bought something same-vendor could not.** Grok found `--corpus=` silently ranking
the caller's working directory — exit 0, advisory header printed, decoy rows returned, the real
475-entry corpus never read. **Three opus lenses had already attacked this exact artifact and missed
it.** It was still live on main; confirmed independently, fixed, catalogued as **FM-168**. That is
one real defect attributable to vendor diversity rather than to more effort.

**3. One lane is not three lenses.** The same model (opus) found all six classes when split into
three specialised lenses, and three of six as a single generalist. The *decomposition* was worth
more than the model choice within the same tier.

**4. Reporting discipline tracks capability, and it is load-bearing.** Both Anthropic lanes that
failed to emit `VERDICT:` as a literal first line were the two weakest (sonnet, haiku). The landing
gate matches on that string, so those runs are **unlandable by construction** — the same 16/31
reporting gap measured in the baseline arm, concentrated in the cheap tiers.

**5. Declining to file is a quality signal.** Grok and opus both scoped explicitly — Grok shipped a
"Not filed (checked, no contract break)" section. Neither weak lane showed evidence of having
checked and declined anything, which is what a low finding count *should* look like when it is
honest.

## Honest limitations

- **N = 1 artifact, 1 run per model.** No variance estimate. A second run could reorder the middle.
- **The ground-truth set is opus-derived**, so it is biased toward what opus finds. Grok's live
  find is evidence the set is *incomplete*, not that Grok underperformed on it — the K-scores
  understate any model that finds things opus did not look for.
- **Severity is my judgement**, not a blind rubric. I called sonnet's `--help` finding contestable
  and Codex's error-path finding contestable; a different judge might keep both.
- **The cross-vendor lanes ran through `cli-dispatch`** with a standards floor injected, the Claude
  lanes through the workflow runner. Harness is confounded with vendor. Fixing that needs the same
  harness for all five, which is not currently possible.

## What changes as a result

- Adversarial verification stays on **opus or a cross-vendor lane**. Never sonnet or haiku.
- Keep **≥1 non-Anthropic lane** on any high-stakes verification: it produced the only live defect.
- Prefer **several specialised lenses over one generalist**, within whatever tier is used.
- The verdict-line requirement needs enforcing at dispatch, not requesting in a brief.
