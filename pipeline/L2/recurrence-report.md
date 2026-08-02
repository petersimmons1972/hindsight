# Recurrence report

## Summary

Corpus: **484** entries; **192** clusters; **113** clusters with more than one member.
Most repeated root cause: **The live running container's effective config differs from what the declared manifest / deploy script / IaC source-of-tr** (**22** occurrences).

Limitation: this wording-based partition under-reports recurrence. It cannot group records that share only an abstract cause shape rather than wording (measured blind-paraphrase recall: 1 of 77). A singleton is therefore not evidence that a cause never recurred.

## Recurrence table

| Label | Count | Member IDs | Source repos | First seen | Last seen | Span (days) |
| --- | ---: | --- | --- | --- | --- | ---: |
| The live running container's effective config differs from what the declared manifest / deploy script / IaC source-of-tr | 22 | ccx-FM-016, ccx-FM-021, ccx-FM-023, fleet-COM-2, hc-FM-100, hc-FM-101, hc-FM-102, hc-FM-103, hc-FM-107, hc-FM-108, hc-FM-109, hc-FM-114, hc-FM-115, hc-FM-119, hc-FM-120, hc-FM-122, hc-FM-125, hc-FM-35, hc-FM-78, hc-FM-86, hc-FM-88, hc-FM-97 | claude-codex, fleet, hindsight | 2026-06-18 | 2026-07-06 | 18 |
| A terminal SUCCESS signal was treated as proof the work succeeded | 13 | ccx-FM-001, dm-04, dm-10, dm-14, fleet-OPS-11, fleet-OPS-16, fleet-OPS-18, fleet-OPS-21, fleet-OPS-23, fleet-OPS-28, fleet-orch-OPS-11, hc-FM-164, hc-FM-87 | claude-codex, duramind, fleet, hindsight | 2026-06-12 | 2026-07-25 | 43 |
| For aifleet issue #590 (validate-fleet | 11 | fleet-CI-1, fleet-CI-12, fleet-CI-13, fleet-ORC-2, fleet-orch-CI-1-FM5, fleet-orch-CI-1-FM7, fleet-orch-CI-1-FM8, fleet-orch-CI-12, fleet-orch-CI-13, fleet-orch-ORC-2, hc-FM-83 | fleet, hindsight | 2026-07-10 | 2026-07-19 | 9 |
| A plan-only completion report written as free prose above the structured report was never relayed because the poller onl | 10 | ccx-FM-007, ccx-FM-008, ccx-FM-017, ccx-FM-022, fleet-COM-1, hc-FM-104, hc-FM-65, hc-FM-66, hc-FM-79, hc-FM-84 | claude-codex, fleet, hindsight | 2026-06-12 | 2026-07-01 | 19 |
| A codex harness dispatch (fix-default-branch-v2) stalled and crashed mid-run with a confirmed-complete, uncommitted impl | 10 | fleet-CI-16, fleet-OPS-13, fleet-OPS-36, fleet-OPS-38, fleet-OPS-41, fleet-OPS-42, fleet-OPS-45, fleet-OPS-7, fleet-OPS-8, hc-FM-162 | fleet, hindsight | 2026-07-14 | 2026-07-29 | 15 |
| Dispatch runs terminate with failure_class='producer_answer_delivery'; the schema enumerates this as a distinct, DB-enfo | 10 | fd-artifact_transport, fd-auth_failure, fd-capability_preflight, fd-crash_timeout, fd-missing_substrate, fd-missing_tool, fd-producer_answer_delivery, fd-protocol_violation, fd-provider_quota, fd-reference_resolution | fleet-dispatch | unknown | unknown | unknown |
| All 26 items the v9 classifier labeled 'missing_recall' actually have their gold-answer sessions present in the haystack | 9 | eng-case5-8e91e7d9, eng-json-raw, eng-patternA, eng-sec4-partial-correct-masks-arithmetic-gap, eng-taxo-in_context_all, eng-taxo-missing_recall, eng-taxo-partial_context, eng-taxo-scorer_disagrees, eng-taxo-wrong_rank | engram-go | 2026-05-19 | 2026-05-19 | 0 |
| Haystack contamination: a different synthetic user's session ('finished The Nightingale on January 25th') coexists with  | 8 | eng-H4-user-identity-scoping, eng-H5-session-date-injection, eng-case1-92a0aa75, eng-case3-2d58bcd6, eng-case6-d6585ce8, eng-patternC, eng-patternD, eng-sec4-chronosort-insufficient | engram-go | 2026-05-19 | 2026-05-19 | 0 |
| A finding's dedup key included `category`, so the same defect reported by security/spec-violation/edges lenses got 3 dif | 7 | fleet-CI-10, fleet-ORC-1, fleet-orch-CI-10, fleet-orch-ORC-1, fleet-orch-ORC-1a, fleet-orch-ORC-1b, fleet-orch-ORC-1c | fleet | 2026-07-13 | 2026-07-19 | 6 |
| A trust/allowlist check matched the string `github | 7 | fleet-CI-2, fleet-orch-CI-2, hc-FM-130, hc-FM-131, hc-FM-132, hc-FM-133, hc-FM-134 | fleet, hindsight | 2026-07-10 | 2026-07-10 | 0 |
| Lease dir unreadable/unwritable (e | 7 | hc-FM-135, hc-FM-136, hc-FM-138, hc-FM-142, hc-FM-144, hc-FM-145, hc-FM-74 | hindsight | unknown | unknown | unknown |
| A codex-rescue bridge run doing a pure-review task failed at startup with `failed to initialize in-process app-server cl | 6 | ccx-FM-004, fleet-COM-5, fleet-OPS-22, hc-FM-38, hc-FM-61, hc-FM-69 | claude-codex, fleet, hindsight | 2026-06-12 | 2026-07-24 | 42 |
| `cli-dispatch start --harness grok | 6 | fleet-MDL-18, fleet-OPS-24, fleet-OPS-30, fleet-OPS-35, fleet-ORC-10, fleet-ORC-16 | fleet | 2026-07-24 | 2026-07-30 | 6 |
| A throughput-sized num_predict=256 reused for a quality benchmark truncated a thinking-mode model's answer inside <think | 6 | fleet-CI-8, fleet-MDL-2, fleet-orch-CI-8, fleet-orch-MDL-2-FM14, fleet-orch-MDL-2-FM16, fleet-orch-MDL-2-FM19 | fleet | 2026-07-18 | 2026-07-19 | 1 |
| A GitHub issues | 6 | ccx-FM-009, ccx-FM-010, ccx-FM-014, fleet-COM-13, fleet-COM-8, fleet-COM-9 | claude-codex, fleet | 2026-06-18 | 2026-06-18 | 0 |
| aifleet's per-role olla routing commit encoded GPU role into the --alias (bge-m3-live, bge-m3-reembed); engram-go read t | 6 | hc-FM-01, hc-FM-02, hc-FM-03, hc-FM-127, hc-FM-22, hc-case-1 | hindsight | 2026-06-12 | 2026-06-12 | 0 |
| Homepage pod showed Running and the service returned HTTP 200, but every widget on the rendered page displayed "API Erro | 5 | k8s-001, k8s-002, k8s-003, k8s-008, k8s-011 | kubernetes | 2025-11-24 | 2025-12-20 | 26 |
| A per-test timing profile and a '72% faster' A/B result were presented as properties of current code, but the working tr | 5 | fleet-OPS-1, fleet-OPS-47, fleet-OPS-50, hc-FM-82, hc-FM-93 | fleet, hindsight | 2026-07-14 | 2026-07-30 | 16 |
| dispatch/test/helpers | 5 | fleet-OPS-44, fleet-OPS-48, fleet-ORC-13, fleet-ORC-6, hc-FM-128 | fleet, hindsight | 2026-07-20 | 2026-07-30 | 10 |
| Repeated ONCE=1 canary runs kept claiming stale test items from prior failed runs (e4daa9c2, 6b41b54d, f40a9457) instead | 5 | ccx-FM-003, ccx-FM-018, fleet-COM-15, fleet-COM-4, hc-FM-166 | claude-codex, fleet, hindsight | 2026-06-12 | 2026-06-18 | 6 |
| A Holm-significant cross-vendor gap (Sol > Opus 4 | 5 | fleet-MDL-10, fleet-MDL-11, fleet-MDL-16, fleet-MDL-8, fleet-MDL-9 | fleet | 2026-07-20 | 2026-07-24 | 4 |
| During a poller cutover from leviathan to codex | 5 | ccx-FM-002, fleet-COM-3, hc-FM-139, hc-FM-44, hc-FM-62 | claude-codex, fleet, hindsight | 2026-06-12 | 2026-06-12 | 0 |
| A coordinator wrote three workflow lanes in which the same agent both implemented a fix and merged its own PR, relying o | 4 | fleet-CI-14, fleet-CI-3, fleet-ORC-14, fleet-orch-CI-3 | fleet | 2026-07-10 | 2026-07-30 | 20 |
| grok-4 | 4 | fleet-OPS-40, fleet-OPS-9, fleet-orch-OPS-9, hc-FM-68 | fleet, hindsight | 2026-07-11 | 2026-07-27 | 16 |
| Background/worktree-spawned agents auto-deny interactive Bash (ssh) permission prompts, burning a full agent spawn per a | 4 | fleet-OPS-10, fleet-ORC-7, fleet-orch-OPS-10, hc-FM-75 | fleet, hindsight | 2026-07-11 | 2026-07-20 | 9 |
| A scoring agent for F4_feasicore:L2/haiku attempt-1 returned `instrument_error_count: 2` with notes citing scoring-side  | 4 | fleet-MDL-13, fleet-OPS-25, fleet-OPS-26, fleet-OPS-27 | fleet | 2026-07-21 | 2026-07-25 | 4 |
| A network partition dropped node A's heartbeats to the notifier while node A was still alive and working its claimed iss | 4 | ccx-FM-015, fleet-COM-14, hc-FM-143, hc-FM-80 | claude-codex, fleet, hindsight | 2026-06-18 | 2026-06-18 | 0 |
| The campaign's 8-lever matrix frames the problem as retrieval-vs-generation, but roughly 41% of failures (aggregation +  | 4 | eng-H1-arithmetic-prompt, eng-sec5-sonnet-regression, eng-sec5-three-component-gap, hc-FM-76 | engram-go, hindsight | 2026-05-19 | 2026-05-19 | 0 |
| engram-go PR #1405 round 1: a review instruction told the implementer to apply distinct-dated-occurrence dedup to both ` | 4 | fleet-CI-6, fleet-CI-7, fleet-orch-CI-6, fleet-orch-CI-7 | fleet | 2026-07-11 | 2026-07-11 | 0 |
| adversarial-loop | 4 | fleet-CI-9, fleet-ORC-3, fleet-orch-CI-9, fleet-orch-ORC-3 | fleet | 2026-07-19 | 2026-07-19 | 0 |
| Team Lead broadcast HALT to all 14 commanders during Operation Multi-Variant Deployment; after resolving the blocker, ag | 4 | gen-01, gen-06, gen-07, gen-09 | generals | unknown | unknown | unknown |
| No quality gate failures occurred in Operation Multi-Variant Deployment (100% pass rate across all 3 gates); the documen | 4 | gen-02, gen-03, gen-04, gen-10 | generals | unknown | unknown | unknown |
| The codex poller service had three compounding install-layout bugs: ExecStart referenced codex-poll | 4 | hc-FM-04, hc-FM-05, hc-FM-10, hc-case-2 | hindsight | 2026-06-12 | 2026-06-12 | 0 |
| During Qwen2 | 4 | hc-FM-121, hc-FM-89, hc-FM-90, hc-FM-91 | hindsight | unknown | unknown | unknown |
| Value resolved on host at apply time (DNS lookup, IP) diverges from what the container sees at runtime → silent mismatch | 4 | hc-FM-42, hc-FM-43, hc-FM-55, hc-FM-58 | hindsight | unknown | unknown | unknown |
| cloudflared pod routes to dashboard-configured origin (https://resume | 4 | hc-inc-003, hc-inc-004, hc-inc-005, hc-inc-006 | homelab-config | 2026-01-28 | 2026-01-28 | 0 |
| Merging two fully-green branches (each passing its own tests) produced three collisions invisible on either branch alone | 3 | fleet-OPS-39, fleet-OPS-43, fleet-OPS-5 | fleet | 2026-07-14 | 2026-07-29 | 15 |
| Three of six independent cross-vendor review lanes (Claude, Grok, Codex) all concluded a QA panel would have passed a ca | 3 | dm-09, fleet-ORC-11, fleet-ORC-9 | duramind, fleet | 2026-07-27 | 2026-07-30 | 3 |
| queue-agent --agent hermes tried to route a consult by naming an agent that had no corresponding GitHub label; GitHub re | 3 | ccx-FM-005, fleet-COM-6, hc-FM-67 | claude-codex, fleet, hindsight | 2026-06-12 | 2026-06-12 | 0 |
| The host-side issue-body prefetch used `gh | 3 | ccx-FM-006, fleet-COM-7, hc-FM-64 | claude-codex, fleet, hindsight | 2026-06-15 | 2026-06-15 | 0 |
| codex-github list-issues --limit N returned fewer than N issues via REST fallback because GitHub's /issues endpoint mixe | 3 | ccx-FM-011, cdx-004, fleet-COM-10 | claude-codex, codex, fleet | 2026-06-18 | 2026-06-18 | 0 |
| Docker volume backed by NFS (`truenas:/mnt/zp1/ai-models`) occasionally returns "connection refused" at `docker compose  | 3 | ccx-FM-019, fleet-COM-16, hc-FM-92 | claude-codex, fleet, hindsight | 2026-06-18 | 2026-06-18 | 0 |
| Follow-up hardening found: (1) a command chaining two producer\|base64 -d\|shell pipelines only had its first pipeline dec | 3 | cdx-009, cdx-010, hc-FM-29 | codex, hindsight | unknown | unknown | unknown |
| `PreferenceRecallQuery` strips the recommendation verb and appends fixed tokens ('like dislike use avoid'); for generic  | 3 | eng-H2-preference-np-extraction, eng-case2-75832dbd, eng-patternB | engram-go | 2026-05-19 | 2026-05-19 | 0 |
| A GB10 decode benchmark computed effective memory bandwidth as decode_tok/s x bytes_per_token using ollama /api/ps's res | 3 | fleet-MDL-1, fleet-orch-MDL-1, mdl-002 | fleet, spark | 2026-07-18 | 2026-07-18 | 0 |
| C2's honesty test asserted the report disclosed its recall limitation by searching all of stdout for any of ('limitation | 3 | fleet-OPS-49, hc-FM-169, hc-FM-170 | fleet, hindsight | 2026-07-30 | 2026-07-30 | 0 |
| An eval/measurement harness scored its own artifacts instead of the system under test: a probe that selected from saniti | 3 | fleet-ORC-5, fleet-orch-ORC-5, hc-902 | fleet, hindsight | 2026-07-13 | 2026-07-13 | 0 |
| agent-send command invoked xh binary from /home/linuxbrew/ | 3 | hc-FM-07, hc-FM-158, pub-fm-07 | hindsight, substack | 2026-07-21 | 2026-07-21 | 0 |
| First-pass diagnoses were wrong in both directions this session: optimistically (phantom blockers declared that did not  | 3 | hc-FM-105, hc-FM-106, hc-FM-70 | hindsight | unknown | unknown | unknown |
| In factvault cmd/api | 3 | hc-FM-111, hc-FM-112, hc-FM-126 | hindsight | unknown | unknown | unknown |
| `emit_strike()` called AFTER successful requeue, not before attempt → a failed requeue (e | 3 | hc-FM-137, hc-FM-141, hc-FM-73 | hindsight | unknown | unknown | unknown |
| hindsight 2026-08-01: ARC scalesets are per-repo (10 exist, each with its own githubConfigUrl); the new repo had none, s | 3 | hc-FM-149, hc-FM-150, hc-FM-151 | hindsight | unknown | unknown | unknown |
| Host leases live on the VM filesystem; container leases live inside a Docker volume — separate stores, so `lease_reclaim | 3 | hc-FM-39, hc-FM-40, hc-FM-63 | hindsight | unknown | unknown | unknown |
| Device-flow token persists on a volume as crown-jewel: concurrent-write corruption; recovery tied to a human ceremony | 3 | hc-FM-46, hc-FM-53, hc-FM-54 | hindsight | unknown | unknown | unknown |
| gmail-tracker ran as a Deployment executing `while true; do job; sleep 12h; done`, but its liveness probe checked for /a | 3 | hc-les-01, hc-les-03, hc-les-05 | homelab-config | 2026-01-25 | 2026-01-25 | 0 |
| The Cloudflare API token used by cert-manager for DNS-01 challenges had an IP whitelist scoped to the homelab external n | 3 | hc-les-06, hc-les-07, hc-les-08 | homelab-config | 2026-01-25 | 2026-01-25 | 0 |
| Two draft rows matched one article title, causing push-draft to fail closed (correct) but stalling in the idempotency gu | 3 | pub-fm-03, pub-fm-04, pub-fm-06 | substack | 2026-07-21 | 2026-07-21 | 0 |
| Secrets were committed to the public GitHub repository because no pre-commit scanning existed to block staged files cont | 2 | hc-les-11, pub-001 | clearwatch, homelab-config | 2026-01-18 | 2026-03-23 | 64 |
| `git check-ignore -v <path>` printed a matching rule that looked like a gitignore hit, but the rule was actually a negat | 2 | fleet-OPS-3, fleet-OPS-34 | fleet | 2026-07-14 | 2026-07-26 | 12 |
| health-check | 2 | hc-inc-007, hc-les-10 | homelab-config | 2026-01-13 | 2026-01-25 | 12 |
| An automated recovery step backfilled errored rows by appending corrected rows rather than replacing the erroring ones,  | 2 | fleet-MDL-19, fleet-OPS-14 | fleet | 2026-07-22 | 2026-07-29 | 7 |
| A scorer repair for taskF2_retrytax round 1 required exact==len(cases) for 'correct', making a coupled 0 | 2 | fleet-MDL-17, fleet-ORC-12 | fleet | 2026-07-24 | 2026-07-30 | 6 |
| If fleet-notifier's HMAC (webhook path) or per-node token (consult path) validation is absent or misconfigured, an unaut | 2 | ccx-FM-012, fleet-COM-11 | claude-codex, fleet | 2026-06-18 | 2026-06-18 | 0 |
| A bulk enqueue of ~50 issues rapidly emitted 50 issues | 2 | ccx-FM-013, fleet-COM-12 | claude-codex, fleet | 2026-06-18 | 2026-06-18 | 0 |
| Of four impl-grok prose-review jobs (~3KB-~260KB), one ~3KB job succeeded while another ~3KB job of similar size failed  | 2 | ccx-FM-020, fleet-COM-17 | claude-codex, fleet | 2026-07-01 | 2026-07-01 | 0 |
| make install exposed a stale command with no remaining Cargo source, and a Cargo-declared command was missing from insta | 2 | cdx-001, cdx-006 | codex | 2026-07-15 | 2026-07-15 | 0 |
| The codex-github wrapper called gh with --json for subcommands that do not support it (gh pr create, gh pr checks, gh pr | 2 | cdx-002, cdx-003 | codex | unknown | unknown | unknown |
| An agent/validator used `curl -sv` (or another verbose HTTP flag) against an authenticated endpoint, writing a raw `Auth | 2 | cdx-005, hc-FM-96 | codex, hindsight | unknown | unknown | unknown |
| Session cleanup took hindsight from 43 worktrees to 1 | 2 | cdx-008, hc-FM-171 | codex, hindsight | unknown | unknown | unknown |
| A fatal ±11pp statistic in the paper, a fix-plan that repeated the same error, and a wrong estimand (measuring σ instead | 2 | dm-01, dm-07 | duramind | unknown | unknown | unknown |
| Exploring a maximalist $50-200k+team version of the study first was what revealed that the honest first-win was actually | 2 | dm-06, k8s-012 | duramind, kubernetes | unknown | unknown | unknown |
| The v1 determinism fix-plan re-committed the same flip-rate-vs-accuracy conflation it was meant to fix, and also mis-spe | 2 | dm-08, dm-11 | duramind | unknown | unknown | unknown |
| A scorer fix resolving one model's false-fail (redundant_wildcard vs grant ambiguity) by forcing one convention passed t | 2 | dm-13, fleet-MDL-14 | duramind, fleet | 2026-07-21 | 2026-07-21 | 0 |
| A drift check was written as `kubectl diff -f m | 2 | dm-15, fleet-OPS-31 | duramind, fleet | 2026-07-26 | 2026-07-26 | 0 |
| The `#PlankChallenge` session was present in the haystack but never retrieved for a temporal-ordering question; its only | 2 | eng-case4-68e94287, eng-patternE | engram-go | 2026-05-19 | 2026-05-19 | 0 |
| 9 of 11 preference items in Exp 09 were PARTIALLY_CORRECT or INCORRECT despite 100 retrieved blocks, showing that increa | 2 | eng-sec4-preference-not-retrieval-depth, eng-sec4-topk-noise | engram-go | 2026-05-19 | 2026-05-19 | 0 |
| adversarial-loop | 2 | fleet-CI-11, fleet-orch-CI-11 | fleet | 2026-07-19 | 2026-07-19 | 0 |
| A `bats` test run was piped into `tail -30` and its exit code read via `$ | 2 | fleet-CI-17, hc-FM-81 | fleet, hindsight | 2026-07-30 | 2026-07-30 | 0 |
| PR #20 changed a predicate from `conclusion == "SUCCESS"` to `conclusion | 2 | fleet-CI-4, fleet-orch-CI-4 | fleet | 2026-07-10 | 2026-07-10 | 0 |
| cli-dispatch issues #13/#17/#11 involved honoring untrusted control input as authoritative: run/cwd read from a repo's c | 2 | fleet-CI-5, fleet-orch-CI-5 | fleet | 2026-07-10 | 2026-07-10 | 0 |
| Codex's provider-side cyber content-filter refused authorized first-party defensive security QA on our own measurement s | 2 | fleet-MDL-15, hc-FM-57 | fleet, hindsight | 2026-07-21 | 2026-07-21 | 0 |
| A GB10 L1 prefill-vs-length scaling sweep built prompts by repeating a fixed paragraph to reach N tokens, making build_p | 2 | fleet-MDL-3, fleet-orch-MDL-3 | fleet | 2026-07-19 | 2026-07-19 | 0 |
| A GB10 Q2 quantization-quality-knee experiment for qwen3:8b was designed to sweep a full 7-point quant ladder, but 4 of  | 2 | fleet-MDL-4, fleet-orch-MDL-4 | fleet | 2026-07-19 | 2026-07-19 | 0 |
| In the GB10 campaign, hand-authored 'quick/throwaway' benchmark harness scripts (campaign 1) later FAILED the repo's she | 2 | fleet-OPS-12, fleet-orch-OPS-12 | fleet | 2026-07-18 | 2026-07-18 | 0 |
| A model-eval-suite pin written into an isolated CODEX_HOME/config | 2 | fleet-OPS-15, fleet-OPS-20 | fleet | 2026-07-23 | 2026-07-23 | 0 |
| Coordinator dispatches N individually-queued Codex issues for a batch of tasks in the same repo without grouping by file | 2 | fleet-OPS-2, hc-FM-113 | fleet, hindsight | 2026-07-14 | 2026-07-14 | 0 |
| An eval task (harness/corpus/taskSFA_typed | 2 | fleet-OPS-32, fleet-orch-OPS-32 | fleet | 2026-07-26 | 2026-07-26 | 0 |
| A merged PR (factvault #231) listed C-conformance fixes (feeds | 2 | fleet-OPS-4, hc-FM-124 | fleet, hindsight | 2026-07-14 | 2026-07-14 | 0 |
| aifleet PR #602 modified `controller/deploy/hosts/oblivion | 2 | fleet-ORC-15, hc-FM-17 | fleet, hindsight | 2026-07-30 | 2026-07-30 | 0 |
| The instinct subsystem's false_positive_rate metric read 0 identically whether the system was healthy, broken (judge 404 | 2 | fleet-ORC-4, fleet-orch-ORC-4 | fleet | 2026-07-13 | 2026-07-13 | 0 |
| A # pragma: no cover live binding (live_run_py) shipped a NameError (stripped 'import pathlib') because a formatter Post | 2 | fleet-orch-meta-rule, hc-FM-110 | fleet, hindsight | unknown | unknown | unknown |
| substack-scheduler NetworkPolicy (allow-github-egress / allow-substack-egress) and GHCR pull Secret were applied/edited  | 2 | hc-FM-116, hc-FM-117 | hindsight | unknown | unknown | unknown |
| C4: cross-repo enforcement check reported 15 phantom paths that existed in their own repos | 2 | hc-FM-12, hc-FM-152 | hindsight | unknown | unknown | unknown |
| `~/bin/add-failure-mode | 2 | hc-FM-123, hc-FM-146 | hindsight | unknown | unknown | unknown |
| The vendor target docs/failure-modes | 2 | hc-FM-147, hc-FM-148 | hindsight | unknown | unknown | unknown |
| Running Homepage on the `:latest` image tag silently pulled v1 | 2 | hc-FM-15, k8s-006 | hindsight, kubernetes | 2025-11-24 | 2025-11-24 | 0 |
| C4d cut real coverage 33 to 23 and set the floor to 23 -- the anti-regression mechanism used to record the regression | 2 | hc-FM-155, hc-FM-157 | hindsight | unknown | unknown | unknown |
| `codex-poll | 2 | hc-FM-18, hc-FM-23 | hindsight | unknown | unknown | unknown |
| Releasing chunk claims without verifying embedding endpoint health | 2 | hc-FM-26, hc-FM-27 | hindsight | unknown | unknown | unknown |
| Repeated attempts to tunnel to the fleet-dispatch ClusterIP via `kubectl port-forward` exited 144 (reaped by the agent s | 2 | hc-FM-28, hc-FM-36 | hindsight | unknown | unknown | unknown |
| routing a Go + testcontainers TDD task to a node with no Go and no Docker would have produced unverified code (TDD Proto | 2 | hc-FM-30, hc-FM-31 | hindsight | unknown | unknown | unknown |
| Missing `[unix_http_server]` block → `supervisorctl` healthcheck always unhealthy; k8s restarts fire constantly | 2 | hc-FM-37, hc-FM-50 | hindsight | unknown | unknown | unknown |
| Installer missing `set -e` → deploys stale image after failed build step; no signal, no abort (cross-ref: FM-18 — same f | 2 | hc-FM-47, hc-FM-52 | hindsight | unknown | unknown | unknown |
| Host PATH/runtime vars (PROJECTS_ROOT, CODEX_POLL_STATE_DIR) leaked via copied env-file → non-root container crash (path | 2 | hc-FM-48, hc-FM-59 | hindsight | unknown | unknown | unknown |
| `env_file required:false` → container boots without secrets; partial-credential run with no error surfaced | 2 | hc-FM-49, hc-FM-51 | hindsight | unknown | unknown | unknown |
| Lease-owner vs report-actor identity mismatch: post-verify guard compared report actor (hardcoded "codex") to lease owne | 2 | hc-FM-60, hc-FM-71 | hindsight | unknown | unknown | unknown |
| Infrastructure spans two distinct IP ranges — homelab external (192 | 2 | hc-FM-95, hc-les-09 | hindsight, homelab-config | 2026-01-25 | 2026-01-25 | 0 |
| `longmemeval | 2 | hc-FM-98, hc-FM-99 | hindsight | unknown | unknown | unknown |
| Three deployments (uss-constitution 369 restarts, uss-enterprise 547 restarts, uss-tang 369 restarts) stuck in rolling u | 2 | hc-inc-010, hc-inc-011 | homelab-config | 2026-02-17 | 2026-02-17 | 0 |
| `kubernetes | 2 | k8s-007, k8s-009 | kubernetes | 2025-11-24 | 2025-11-24 | 0 |
| GLM-5 | 2 | mdl-001, mdl-003 | spark | unknown | unknown | unknown |
| GLM-4 | 2 | mdl-004, mdl-006 | spark | 2026-07-02 | 2026-07-02 | 0 |
| Article 091 failed to publish at 09:00 ET and scheduler logged ERROR every 30 minutes for ~a day without alerting anyone | 2 | pub-fm-01, pub-fm-05 | substack | 2026-07-21 | 2026-07-21 | 0 |

## Per-cluster detail

### c-013: The live running container's effective config differs from what the declared manifest / deploy script / IaC source-of-tr

- `ccx-FM-016` — grok.env was provisioned with the coordinator-impl FLEET_DISPATCH_TOKEN (node=coordinator-impl, consumes=["plan"]) instead of the grok consumer token (consumes=["impl-grok"]); grok-attach's /claim calls correctly returned {"empty":true} forever since no plan items existed, and the container stayed running and healthy with zero error output, starving silently.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `ccx-FM-021` — Five review-capability items (a8e97eed, f2ee6323, b10075b1, 01b7d02e, 18ca5cdc) sat in state:queued with lease_holder:"" and retries:0 for more than two hours with no claim-then-fail signature at all, indicating a missing/misbound live consumer for that capability with no alert surfacing the starvation.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `ccx-FM-023` — Items 3b140900 (codex#153) and c8d4e365 (codex#152) each completed and committed real work then reported needs-input, but fleet-dispatch's §6.3.1 validation found the question empty after trimming (the parser had read failure_reason: and ignored the protocol's needs: field, and codex-attach copied result_ref into question without validating it was non-empty), so the item was downgraded and re-queued, causing the node to re-execute the entire work step from scratch until retries exhausted while a container healthcheck also false-tripped UNHEALTHY on the resulting long-running (6-9 min) active work step.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `fleet-COM-2` — A wrong bearer token (consumes:["plan"] instead of ["impl-grok"]) made every /claim correctly return {"empty":true} forever with no alarm, since the server behaved correctly for the wrong token it received; separately five review-capability items sat state:"queued" with lease_holder:"" for 2+ hours with no consumer ever claiming them and no alert.
  Source: `fleet/FAILURE-MODES.md`
- `hc-FM-100` — A fix (delivery-mode / artifact-gate downgrade to `comment_only`) was applied to the Go `fleet-attach` consumer but not mirrored to the sibling bash `codex-attach` consumer — the same bug persisted on the unpatched path, silently. Root cause: sibling consumers share a contract but not a code path; a patch to one does not propagate to the other. (2026-06-19, fleet-dispatch)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-101` — Attach service shows `active`/polling, zero auth errors, but every claimed item fails on a local precondition (dirty working tree / missing branch) — the service passes all liveness and status checks while doing zero real work. Because liveness probes only verify the process, not the work-execution path, the failure is invisible until a round-trip canary times out. (2026-06-19, codex-attach.service)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-102` — Fleet-dispatch capability strings are free-form text gated only by token Produces/Consumes lists. A typo (`impl-grook` instead of `impl-grok`) or a newly-registered capability that no consumer declares is silently never claimed: the item sits in `queued` indefinitely with no error surfaced to the producer. Detection requires polling the item status manually. (2026-06-19)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-103` — `ATTACH_TOKENS` is a single JSON object keyed by live bearer hex strings. Any edit (add/remove/rotate a token) requires a full read-merge-write cycle. A JSON syntax error during that cycle (malformed merge, trailing comma, copy-paste mistake) corrupts the entire map and returns 401 to ALL consumers simultaneously — the fleet closes hard with no partial fallback. One bad token rotation can silently kill the entire dispatch bus. (2026-06-19, fleet-dispatch)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-107` — Codex and Hermes both consume the `consult` capability. Codex claims consult items and either 422s (its coordinator token does not produce/consult-emit correctly) or runs `gh issue view placeholder/placeholder#0` (fleet-consult.sh uses a placeholder repo) and dead-letters. The fence/retry mechanism eventually recovers via Hermes, but routing is non-deterministic and recovery time is unbounded. (fleet-dispatch, 2026-06-20)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-108` — A `review`-capability item whose prompt asks for plan feedback (not a code artifact) causes the Codex CLI to parse implementation cues, create a local `agent/codex/*` branch with commits, then fail because `git push` is allow-list-blocked → dead-letter with a preserved unpushed worktree. The failure is not surfaced until the dead-letter reason is inspected manually. (fleet-dispatch, 2026-06-20)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-109` — POST /item/{id}/cancel returns 409 when the item is in dead-letter state. Dead-letter items cannot be cleaned up via the standard cancel path, leaving them in the queue and any preserved consumer worktrees unreclaimed. The cancel endpoint should be idempotent across all terminal states (done, dead-letter, cancelled). (fleet-dispatch, 2026-06-20)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-114` — Enqueuing a fleet-dispatch item with bare repo name (e.g., `--repo factvault`) instead of full slug (`--repo petersimmons1972/factvault`). The enqueue command SUCCEEDS and returns an enqueue ID, giving false confidence. The codex-attach consumer requires refs in `[HOST/]OWNER/REPO` format; a bare name produces a malformed ref. Consumer cannot resolve it, item never claims, queue reaper dead-letters it within seconds. GitHub issue label stays `agent/codex/queued` (cosmetic), masking the failure. Compounding: discovered alongside a dead consumer (codex-agent container down ~10h); consumer downtime hid the slug bug because items dead-lettered for "no consumer" reasons instead of malformed ref. When consumer restarted, items STILL failed with "expected [HOST/]OWNER/REPO format, got factvault". Cost: hours of apparent "queued but idle" state; two false-start re-enqueue rounds. Introduced: 2026-06-23 — factvault #210/#211/#213/#216/#217 re-enqueue after OOBE batch rebases.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-115` — The codex-attach consumer (Docker container codex-agent) died and stayed dead ~10 hours. Nothing alerted. The queue kept accepting enqueues; ~50 items dead-lettered silently, and GitHub issue labels stayed cosmetically `agent/codex/queued`. Discovered only by manual inspection after PRs sat idle. Root cause: no automated detection for "consumer alive but not consuming" or "consumer dead." Three missing detection layers: (1) Consumer liveness — no per-capability last-claim heartbeat + staleness alert; (2) Queue health — no alert on items queued > N min unclaimed, no dead-letter-rate alert (50 dead-letters accumulated with zero notification); (3) End-to-end canary — no scheduled synthetic item proving the pipeline completes work. Compounding: GitHub labels are cosmetic and lie (stay `queued`); the fleet-dispatch /items API is the only truth source for actual queue state. Cost: ~10h pipeline outage undetected; multiple false-start re-enqueues; manual diagnosis. Observed: 2026-06-23 — codex-agent container dead during factvault OOBE rebase cycle, items dead-lettered in silence.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-119` — Queued items for capability `impl-grok` sat indefinitely with `retries=0`, `lease_holder:""`. Consumer container healthy (uptime + healthcheck pass), fleet-dispatch server healthy, no error surfaced anywhere. Compound root causes: (1) `deploy-grok-machine.sh:~51` defaults `FLEET_TOKEN_FILE` to `token-impl` (Codex token) instead of `token-impl-grok`; server returns `{empty:true}` on every `/claim` because that token's `consumes` set lacks the target capability — silently; (2) `deploy-grok-machine.sh:~127` always writes `GROK_ATTACH_ENABLED=0`, disabling claiming on every redeploy regardless of prior state; (3) no alert fires on "items queued with no lease for N minutes" or "consumer token `consumes` does not include its target capability." Burned a multi-step diagnostic cycle (poll → k8s health → host docker → token-sha comparison) before isolating the cause. (Bug: petersimmons1972/claude-codex#316)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-120` — The live running container's effective config differs from what the declared manifest / deploy script / IaC source-of-truth would produce. Hand-fixes to the running host (sed-editing a live `.env`, `kubectl patch` on a secret) appear applied but are silently reverted on the next deploy or by ESO reconciliation; conversely, deploy scripts overwrite intended runtime state (e.g. resetting an enable gate to 0) on every run. "What's running" ≠ "what's declared," and nothing flags the gap. Root causes: (1) Deploy script writes authoritative values that overwrite operationally-critical runtime state on every redeploy (`deploy-grok-machine.sh:~127` forces `GROK_ATTACH_ENABLED=0`); (2) Operators hand-patch live state to work around it (sed on `.env`), creating drift the next deploy silently reverts; (3) ESO-managed k8s secrets (`fleet-dispatch-tokens`) have their source of truth in Infisical; direct `kubectl patch` looks applied but is reverted on next sync; (4) No drift detection comparing running effective config to the declared manifest / IaC source. Each layer (enable gate, consumer token, server-side `consumes` registration) gets patched at the LIVE container instead of at the source of truth, so it re-breaks on the next reconcile/deploy. Cost: this session — a hand-edited gate and a proposed k8s-secret patch would each have been reverted; compounded the FM-119 diagnostic chase. Related: FM-119, petersimmons1972/claude-codex#316.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-122` — A running container or host-installed artifact is ahead of its source-of-truth: a `cp`/hand-edit applied to a live container without the identical change committed to source + image; a deployment rolled to an image tag the repo manifest does not pin; a `kubectl apply` of a change not yet on `main`. On the next rebuild, restart, or GitOps reconcile the running state silently regresses — symptom appears hours or days later with no clear cause. Observed: fleet-dispatch overnight runs #76/#78 (in-container `git pull`+`cp` of codex-poll NFF+lint patches); any `kubectl set image` outside a PR cycle.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-125` — CONFIRMED (1): `codex exec --ephemeral` reads the rotated OAuth refresh token but never persists it back to auth.json (mtime frozen at last login while atime advances) → next call returns `refresh_token_invalidated`. Observer-effect confirmed: exercising any OAuth-backed CLI (`codex exec`, `grok --single`) or restarting the consumer container rotates/rewrites the shared auth.json and can destabilize other sessions. CONFIRMED (2): `docker exec grok-agent grok --single` co-runs a second grok in the same container as the live daemon, racing on one auth.json; no-TTY loser hangs indefinitely on device-code flow. UNCONFIRMED (demoted): rolling single-use token mutual revocation across leviathan/host/container stores — NOT verified; ChatGPT OAuth normally supports concurrent device sessions. Detection: `refresh_token_invalidated` / device-code prompt on a relay call; auth.json mtime frozen while atime advances. Resolution: STAY ON OAUTH. Drop `--ephemeral` from relay + poller. Never co-run the Grok relay while its daemon is live. Do not exercise OAuth CLIs for diagnostics. API-key cutover plan DROPPED. (fleet-dispatch, grok-agent, codex-attach, 2026-06-26)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-35` — The fleet-dispatch canary could not fire: `fleet-dispatch.petersimmons.com` resolves only on the consumer node (codex, `/etc/hosts` shim — fleet-dispatch#6), so a producer on any other host gets `no such host`. The producer client + live endpoint both existed; the path was un-exercisable from the build host purely due to name resolution.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-78` — Direct kubectl apply/edit of a k8s Secret managed by External Secrets Operator (e.g. fleet-dispatch-tokens) is silently reverted on the next ESO sync — the change looks applied then vanishes. Source of truth is the external store (Infisical), not the k8s Secret.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-86` — `kubectl patch`/`kubectl replace` on a k8s Secret managed by ExternalSecrets Operator (ESO) silently succeeds (rc=0, resourceVersion bumps) but ESO reconciles the change back within seconds — observed on `fleet-dispatch-tokens` in `ai-fleet`. Additionally, ATTACH_TOKENS was injected as an env var (not a volume mount), so a pod restart is required after every update; restarting before ESO finishes writing the Secret loads the old value into the new pods (race condition independently identified by Codex and Hermes during fleet-plan dry run, 2026-06-18).
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-88` — Used the **diagnostics-only `ssh` path for agent coordination** (running Grok/Codex/Hermes reviews, prompt-TDD, and collab via `ssh … docker exec … <agent> --single/-q`) instead of the sanctioned **ssh-free fleet-dispatch** path (`scripts/fleet-consult.sh`, `scripts/fleet-enqueue.sh`). The operating directive is explicit: *"ssh is DIAGNOSTICS ONLY; never for coordination."* Worse than a style violation: ssh-bypassing the queue **masks whether the real capability works** — I kept getting answers via ssh, which hid that the fleet `impl-grok` path was broken and turned the fix (PR #248) into theater, because I never exercised the thing I was fixing (2026-06-19).
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-97` — After rotating `ATTACH_TOKENS`, the fleet-dispatch pod was restarted but only one consumer (Hermes or Codex) was cycled. The un-cycled consumer continued authenticating with the old token — receiving 401 on every claim attempt — stalling work silently for hours until the consumer was manually restarted. Root cause: Codex and Hermes each hold an independent copy of their bearer credential (Codex: `~/.config/fleet-dispatch/token` on the codex node; Hermes: an env-var/Secret mount). Neither is hot-reloaded; both must be cycled in the same rotation window.
  Source: `hindsight/catalog/failure-modes.md`

### c-001: A terminal SUCCESS signal was treated as proof the work succeeded

- `ccx-FM-001` — Codex/Hermes wrote the consult answer as free prose above the CODEX REPORT ("Posted below is the assessment to send as the #54 comment") and reported status:done, but the poller only reads structured fields and still demanded a PR for a plan-only task; post-verify saw no PR and no recoverable field, so it applied agent/codex/stalled and the answer never reached issue #54.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `dm-04` — A run printed "COMPLETE" but had actually loaded 0 items (a silent-empty run); this was only caught because the run.log was read directly for the "N ingest entries loaded" line instead of trusting the summary status, avoiding a wasted ~10 GPU-hour scale-up.
  Source: `duramind/docs/campaign/DETERMINISM-CAMPAIGN-LESSONS.md`
- `dm-10` — A run used per-run unique run-ids that matched no ingested memory, so it silently loaded 0 items while still exiting/reporting success — the same failure class as the fleet FM-B7 atom-build embed footgun (a pipeline exiting 0 having done nothing).
  Source: `duramind/docs/campaign/DETERMINISM-CAMPAIGN-LESSONS.md`
- `dm-14` — The harness exited reporting "COMPLETE" having actually loaded 0 items, due to a wrong run-id or a missing ingest checkpoint.
  Source: `duramind/docs/campaign/DETERMINISM-CAMPAIGN-LESSONS.md`
- `fleet-OPS-11` — An 8.5h atom-build exited 0 having embedded 0 of 16,792 atoms because the embed URL silently defaulted to a non-embedder (404 on every call); a relaunch repeated the same silent zero; separately a bare `codex exec` ran ~1h51m with zero CPU time and zero output — a process-liveness check alone would have called it 'running.'
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-16` — A subagent running a long background sweep, forced to emit its StructuredOutput report before the driver finished, produced two distinct wrong-state reports: one undercounted completed rows (claimed 1/12 runs done when results.csv already showed 2 completed cleanly), and another claimed 6 runs still 'confirmed running' when all 6 processes had actually died silently with no exit code ever written.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-18` — Measurement runs launched from a dying orchestration context got SIGKILLed mid-flight but left results-shaped artifacts (out.txt, workdir, session JSONL) that were scoreable; scoring 6 killed runs yielded exactly the task's pre-existing baseline (3/23, byte-identical workdirs), which read as 'model floor at xhigh/max effort' when it actually measured 'process killed at ~60s.'
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-21` — Three same-day Grok-bridge runs reported completion-shaped messages with no deliverable: a build run narrated 'Implementing the full module…' ~16 times for 23 minutes then exited 1 with nothing written; a review run printed 'Grok finished.' having written nothing; a second review run wrote only a 66-byte VERDICT-PENDING skeleton and died. A sibling Codex `task --resume-last` repair executed read-only ('a writable session is required') or failed with a 2-line empty log.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-23` — Two independent bridge jobs using `codex … --resume-last` logged only 'Starting Codex Resume.' and nothing else despite sufficient wall-clock time, because the headless/bridge invocation never sees the interactive TUI that makes resume usable on a local terminal; an earlier same-session resume-based validation run showed identical behavior.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-28` — A dispatched agent task ran silently for 8+ hours with no output; at the ~6h mark it was deemed dead and relaunched, and the replacement's output (proposal-gpt56.md, commit a1c657e) was consumed into synthesis work. ~18.6 hours after the original launch, the original agent actually finished and its commit (0e8bf2a) attempted to overwrite the same file with late-arriving, potentially stale text, clobbering the already-consumed canonical artifact.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-orch-OPS-11` — An 8.5h atom-build job exited 0 having embedded 0 of 16,792 atoms because the embed URL silently defaulted to the --llm-url (a non-embedder), 404-ing on every call; a relaunched extraction again 'progressed' while storing 0, and a ledger arm ran clean but its ledger was empty -- exit 0/'DONE' was read as proof of success when it only proved the process ended.
  Source: `fleet/CODING-INVARIANTS.md`
- `hc-FM-164` — reconcile_l1.py hardcoded /home/psimmons/projects, so on CI all five sources were absent, the else-100.0 branch fired, and the step printed COMPLETE exit 0 for every run of its existence
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-87` — A terminal SUCCESS signal was treated as proof the work succeeded. A fleet-dispatch `impl-grok` review task was enqueued, the Grok consumer claimed the lease (`lease_holder: grok`) and reported `state: done` — and that was announced as "fully wired, end-to-end confirmed." But the job produced nothing usable: the consumer never injected the referenced GitHub issue body (Grok's own reasoning said "I need to find what article they're referring to"), the stored result was truncated to exactly **1024 bytes** of opening reasoning, and no comment was mirrored to the issue. `done` described the queue lifecycle, not the deliverable (2026-06-18).
  Source: `hindsight/catalog/failure-modes.md`

### c-044: For aifleet issue #590 (validate-fleet

- `fleet-CI-1` — A QA gate's condition tested `ran_ok===false` instead of `!==true` in creation-loop.js, and separately a `hashFiles()` call inside a job-level `if:` made a GH Actions workflow unparseable so it never appeared in `gh pr checks` at all — both cases read as pass when the check never truly ran or errored.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-CI-12` — A QA stage reported `ran_ok=true, passed=true` after receiving only criteria text, not the concrete artifact locator, so it could have graded a green suite against the wrong path, a stale version, or invented helpers (creation-loop.js).
  Source: `fleet/FAILURE-MODES.md`
- `fleet-CI-13` — A coordinator's unverified hypothesis about a live failure's cause ('network flake') was built into a task brief; QA built a real (not mocked) reproduction around that imagined cause, the loop passed and the PR landed, and the real failure (an HTTP 500 from a controller pod) recurred minutes later (aifleet#590 /registry retry).
  Source: `fleet/FAILURE-MODES.md`
- `fleet-ORC-2` — cli-dispatch's documented 'exits 0 even on failure' contract meant a greenfield repo with no remote made `cli-dispatch start` exit 128 fetching origin, and a naive `start && next` chain would have treated the no-op as success.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-orch-CI-1-FM5` — cli-dispatch #10: a command printed a failure status in its JSON output but still exited 0, so a naive `cmd && next` chain proceeded past a failed run because only the output channel encoded failure, not the exit status.
  Source: `fleet/CODING-INVARIANTS.md`
- `fleet-orch-CI-1-FM7` — creation-loop.js's QA gate used `if (!verdict || verdict.ran_ok === false) escalate`, so a verdict with `passed:true` and no `ran_ok` field at all (schema not enforced, or a looser custom schema) fell through to the pass branch — a green-looking result that never actually asserted it ran.
  Source: `fleet/orchestration/FAILURE-MODES.md`
- `fleet-orch-CI-1-FM8` — The 'instinct' self-improving subsystem's mistral judge dependency 404'd for three consecutive weeks; the except/catch path returned a substantive domain verdict ('reject') for each error instead of an abstain, so false_positive_rate kept reporting 0 while the judge was actually unreachable the whole time.
  Source: `fleet/CODING-INVARIANTS.md`
- `fleet-orch-CI-12` — creation-loop.js's IMPLEMENT step returned `file_path` but the loop discarded it before QA, so QA received only the acceptance criteria (not the concrete artifact locator) — QA could write a green suite against the wrong path, a stale version, or invented helpers and still report ran_ok=true, passed=true.
  Source: `fleet/orchestration/FAILURE-MODES.md`
- `fleet-orch-CI-13` — For aifleet issue #590 (validate-fleet.sh's /registry check failing intermittently in CI), the coordinator's task assumed a transient network flake and had QA build a mock-server reproduction of that hypothesis; QA's test passed cleanly (ran_ok=true, passed=true, 0 replans) and the retry-loop PR landed, but CI failed again with the same symptom ~5s later — the real cause was the controller pod silently losing its K8s API connection (HTTP 500, stale route after 15 days uptime), unrelated to network timing, which the retry loop could not fix.
  Source: `fleet/orchestration/FAILURE-MODES.md`
- `fleet-orch-ORC-2` — cli-dispatch start (the mandated cross-model review channel) fetches origin first and exits 128 when a repo has no remote, but `start` is documented to exit 0 even on failure — a naive `start && next` chain on a greenfield repo would treat the no-op as success.
  Source: `fleet/orchestration/FAILURE-MODES.md`
- `hc-FM-83` — A dispatched runner was built with the wrong invocation contract — a one-shot CLI tool requiring --report-url args — while the deployment entrypoint runs it as a self-contained no-args poll-loop daemon. It passed its own unit tests but crash-looped immediately on deploy (claude-codex hermes-attach #176).
  Source: `hindsight/catalog/failure-modes.md`

### c-007: A plan-only completion report written as free prose above the structured report was never relayed because the poller onl

- `ccx-FM-007` — A proposed fix treated the shape 'status=done + notes + no PR + no commits' as proof of a plan-only deliverable, but red-team review (Hermes) showed that exact shape is indistinguishable from an impl run that narrated intent but produced nothing — inferring success from absence of an artifact would silently promote real failures to success.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `ccx-FM-008` — fleet_run_once routed delivery to deliver_plan_only only if the GitHub issue carried the agent/codex/plan-only label, but items enqueued via fleet-dispatch's capability-keyed path (capability=review) never set that label, so a valid done+notes result hit the no-artifact guard and was discarded.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `ccx-FM-017` — fleet-enqueue.sh's build_request_body() had no expected_delivery parameter, so it never sent expected_delivery=comment_only for impl-grok/impl-opencode items; every done report from those comment-only consumers hit fleet-dispatch's artifact gate and was rejected with HTTP 422 'done/needs-input report must include branch and head_sha', failing on every retry.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `ccx-FM-022` — fleet-dispatch's validateArtifactWithDelivery only exempts branch/head_sha inside case DispositionDone (queue.go:1615-1623); case DispositionNeedsInput (queue.go:1624-1631) never reads expectedDelivery and unconditionally requires branch/head_sha, so item f94a06c4-4d5b-4247-9d8a-1b4fba6926b0 (a comment_only-style consult reporting needs-input with a text-only clarifying question) was forced to carry a fabricated branch/head_sha.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `fleet-COM-1` — A plan-only completion report written as free prose above the structured report was never relayed because the poller only reads structured fields; separately delivery was gated on a GitHub label the producing path was never required to set; every impl-grok/impl-opencode 'done' report 422'd because expected_delivery=comment_only was never sent by the enqueue script; and the comment_only exemption, once added, covered disposition=done but not needs-input, forcing a comment-only agent to fabricate a branch/head_sha to ask a clarifying question.
  Source: `fleet/FAILURE-MODES.md`
- `hc-FM-104` — Items enqueued before `expected_delivery` was a required field (or enqueued via a producer that omitted it) hit the fleet-dispatch artifact gate on `/report` with HTTP 422, because the server requires `expected_delivery` to determine terminal disposition. The item was `comment_only`-intended but the gate cannot confirm that without the field — it fails closed. (2026-06-19, fleet-dispatch)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-65` — Inferring a SUCCESS deliverable from the ABSENCE of an artifact: routing `done + notes + no-PR + no-commits` to plan-only delivery promotes a missing-artifact FAILURE (a run that narrated intent but produced nothing) to success — it is the identical shape (Hermes red-team, 2026-06-15, claude-codex#132)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-66` — The runner's delivery/routing decision is gated on a signal the producer/queue never sets: fleet-dispatch items are keyed by CAPABILITY, but plan-only delivery was gated on a GitHub `PLAN_ONLY_LABEL` → legitimate plan/review deliverables hit the no-artifact guard and were discarded (2026-06-15, claude-codex#132)
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-79` — fleet-dispatch enforced an artifact gate (terminal done requires branch+head_sha) that the codex-attach client never sent, so every successful run got 422 on /report then re-claim then dead-letter, silently losing completed work while claim+execute looked healthy.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-84` — A dispatched client passed its own unit tests but violated the SERVER wire contract, because neither the issue spec nor the generated tests pinned the contract: it sent `priority` as a string when `enqueueReq.priority` is an int (→ 400) and omitted the required `expected_delivery:comment_only` signal (→ artifact-gate fail-loud). Green tests gave false confidence; the bug only surfaced against the live API (claude-codex fleet-consult #180, fixed #181/#182).
  Source: `hindsight/catalog/failure-modes.md`

### c-049: A codex harness dispatch (fix-default-branch-v2) stalled and crashed mid-run with a confirmed-complete, uncommitted impl

- `fleet-CI-16` — A worktree harness whose .git gitdir pointer follows back to the shared parent repo committed its leaked output directly into that shared repo instead of leaving it dirty in the working tree; a clean-tree/no-new-uncommitted-delta leak check saw no delta and reported no leak because the leak was already committed, not sitting dirty. Found by adversarial review of fleet PR #66, where the PR's own 'leak detection works' test fixture was mechanically identical in shape to the attack it should have caught.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-13` — The coordinator committed directly in a shared repo checkout while a dispatched lane had it checked out on branch feat/phase-d6-fm11; the commit landed on the lane's branch, sweeping the lane's uncommitted work into an unrelated commit and stranding the coordinator's change off main. Caught by the lane agent pre-push, who split the entangled commit via reset --soft.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-36` — Two independent subagents told to append failure-mode entries to fleet/FAILURE-MODES.md and commit locally did everything right (correct files, explicit git add <path>, no push) except land on the intended branch — both commits ended up on sf-axis-sfa-probe, an unrelated in-flight experiment branch the repo happened to be checked out on, nine commits from main, because neither brief specified a target branch.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-38` — A Codex dispatch returned status: agent-failed, leak: true because two files in the shared checkout (.gitignore, dispatch/cli-dispatch) had been modified — but those modifications were timestamped 06:24/06:25, inside the dispatch window, and belonged to a different live session's in-flight work, continuous with that session's own 06:17 commit; the dispatched agent's own branch showed no commits touching either file.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-41` — With ~8 concurrent `cli-dispatch start` calls running against ~/projects/fleet, each with its own dedicated worktree/branch, the shared checkout itself ended up with two uncommitted tracked-file modifications matching two different concurrently-running tasks' actual work (a dispatch/cli-dispatch diff matching one task's requested fix, and a 5-line ledger.jsonl append matching another task's audition-writing behavior) — caught only because a third, unrelated task's own leak check compared pre/post snapshots and refused to autocommit.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-42` — A codex harness dispatch (fix-default-branch-v2) stalled and crashed mid-run with a confirmed-complete, uncommitted implementation (the exact requested fix plus new bats tests across 7 files) sitting in the worktree; because git commit had never run, a recovery agent invoked `cli-dispatch abort` per a 'nothing useful, clean up' fallback, and abort's cmd_abort() does an unconditional `git worktree remove --force` with no uncommitted-changes check, no stash, no backup — the work was permanently lost (git fsck --unreachable found no dangling objects matching it, since it was never git add-ed).
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-45` — 4+ concurrent subagents were dispatched to the same working tree on branch sf-axis-sfa-probe in the same window; one agent's git add swept up another agent's staged-but-uncommitted files, and one agent's corrective git reset moved HEAD past a commit a different agent had landed mid-operation — recovered with no content lost, but authorship of docs/AUDITION-RETROSPECTIVE-2026-07-26.md's initial version was misattributed to the coverage agent's commit (b59eadf) instead of the retrospective agent.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-7` — `cli-dispatch land` removed a dispatch worktree along with `.dispatch/agent.log` — the only artifact that could say what the agent actually ran — right before an anomaly (18 unattributed reformatted files in a shared checkout) surfaced 2 hours later.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-8` — 52 uncommitted files sitting dirty for days plus 18 more reformatted mid-session in a shared checkout were assumed to be corruption or an escaped agent, but were actually a concurrent live session committing every ~60s and running a job into results/ (duramind lme-b4 campaign).
  Source: `fleet/FAILURE-MODES.md`
- `hc-FM-162` — E1 stage 1: coordinator committed catalog rows and created a test file in the shared checkout mid-dispatch, tripping the protect-set baseline. Run aborted at 0 commits with agent-failed, though the agent's work was correct and self-contained
  Source: `hindsight/catalog/failure-modes.md`

### c-043: Dispatch runs terminate with failure_class='producer_answer_delivery'; the schema enumerates this as a distinct, DB-enfo

- `fd-artifact_transport` — Dispatch runs terminate with failure_class='artifact_transport'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-auth_failure` — Dispatch runs terminate with failure_class='auth_failure'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-capability_preflight` — Dispatch runs terminate with failure_class='capability_preflight'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-crash_timeout` — Dispatch runs terminate with failure_class='crash_timeout'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-missing_substrate` — Dispatch runs terminate with failure_class='missing_substrate'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-missing_tool` — Dispatch runs terminate with failure_class='missing_tool'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-producer_answer_delivery` — Dispatch runs terminate with failure_class='producer_answer_delivery'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-protocol_violation` — Dispatch runs terminate with failure_class='protocol_violation'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-provider_quota` — Dispatch runs terminate with failure_class='provider_quota'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`
- `fd-reference_resolution` — Dispatch runs terminate with failure_class='reference_resolution'; the schema enumerates this as a distinct, DB-enforced failure category.
  Source: `fleet-dispatch/migrations/0017_failure_class.sql`

### c-040: All 26 items the v9 classifier labeled 'missing_recall' actually have their gold-answer sessions present in the haystack

- `eng-case5-8e91e7d9` — Classifier marked 'total number of siblings' (gold: 4) as missing_recall because gold '4' has zero word-overlap with any hypothesis, but both source facts ('I have a brother' and 'I come from a family with 3 sisters') were present in the haystack; the actual failure is cross-session aggregation — the model (Qwen3) answered '2 items', apparently counting sibling-mentioning sessions rather than summing the stated counts.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-json-raw` — Machine-generated eval dump of 135 non-CORRECT LongMemEval v9 items (per-question class label, gold, hypothesis, overlap score) underlying the v9-failure-taxonomy.md summary. Not expanded per extraction instructions — treat as one raw-data source, see v9-failure-taxonomy.md and research-notes-failure-patterns.md for the derived analysis.
  Source: `engram-go/results/v9-failure-taxonomy.json`
- `eng-patternA` — All 26 items the v9 classifier labeled 'missing_recall' actually have their gold-answer sessions present in the haystack; the classifier used short/numeric gold strings as a missing-data proxy, a category error. Every one is a cross-session counting question (e.g. doctor visits, fitness classes, siblings) requiring retrieval of ALL relevant sessions plus summation — an 'aggregation_failure' class (per Engram's own memory_feedback vocabulary) that none of the 8 campaign levers addresses; a 19-point block sits entirely outside the optimization surface.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-sec4-partial-correct-masks-arithmetic-gap` — Qwen3's hedged answer 'you attended 3 art-related events' against a gold of 4 is scored PARTIALLY_CORRECT, masking that the model is off-by-one; the PARTIALLY_CORRECT-to-CORRECT gap for numeric answers requires exact arithmetic, not better retrieval, and the scoring category obscures this.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-taxo-in_context_all` — 72 of 135 non-CORRECT v9 items (53%) had gold content already present among the 100 retrieved blocks, but the generator (Qwen3) failed to extract or synthesize the gold signal — e.g. for Q 031748ae_abs the model answered 'You lead 4 engineers' when retrieval held the gold but the model missed it.
  Source: `engram-go/results/v9-failure-taxonomy.md`
- `eng-taxo-missing_recall` — Classifier labeled 26 of 135 items (19%) as gold-never-ingested data gaps, using 'gold answer is empty or too short to analyze' (short/numeric answers like '2','3','4') as the trigger. research-notes-failure-patterns.md Pattern A later shows this label is wrong for all 26 — the real cause is cross-session aggregation failure, not missing data.
  Source: `engram-go/results/v9-failure-taxonomy.md`
- `eng-taxo-partial_context` — 2 of 135 items (1%) had partial gold context retrieved and the model extracted some but not all of the gold answer (53% and 62% word match), e.g. Q gpt4_59c863d7 model-kit count and Q gpt4_d6585ce8 concert ordering.
  Source: `engram-go/results/v9-failure-taxonomy.md`
- `eng-taxo-scorer_disagrees` — 5 of 135 items (4%) had hypotheses with 100% word overlap with the gold answer yet were scored non-CORRECT, indicating scorer noise/formatting mismatch rather than a genuine model or retrieval failure (e.g. Q 51c32626, gpt4_213fd887).
  Source: `engram-go/results/v9-failure-taxonomy.md`
- `eng-taxo-wrong_rank` — 30 of 135 items (22%) had gold content ingested but not surfaced in the top-K retrieved set (low word overlap, e.g. 25-50%), indicating a ranking/relevance-scoring problem rather than a missing-data or generation problem.
  Source: `engram-go/results/v9-failure-taxonomy.md`

### c-038: Haystack contamination: a different synthetic user's session ('finished The Nightingale on January 25th') coexists with 

- `eng-H4-user-identity-scoping` — No ingest or recall path (cmd/longmemeval/ingest.go, internal/longmemeval/engram.go Recall()) tags or filters blocks by source-user identity, so a wrong block from a different synthetic user can outrank/outcompete the correct block for temporal-ordering questions (as in Case 3); none of the 8 levers touches session identity or block provenance filtering.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-H5-session-date-injection` — The session date is available at ingest time (haystack_dates) but is not necessarily embedded into the stored block content string itself (cmd/longmemeval/ingest.go), so when a block contains a backward reference to an earlier event with no explicit date, the model has no reliable in-block anchor and may use the wrong session's date, as in Case 6; the existing chrono-sort lever reorders blocks but does not inject dates into content.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-case1-92a0aa75` — For 'how long have I been in my current role' the gold answer (1yr 5mo) is the arithmetic difference of two values in two different retrieved sessions ('3yr9mo' minus '2yr4mo'); Sonnet had both sessions in context but hallucinated an unrelated persona ('recent MBA graduate job-searching') instead of attempting the subtraction. Classifier labeled this in_context_all/generator-failed, missing that the real cause is implicit multi-hop arithmetic with no single block containing the gold string.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-case3-2d58bcd6` — Haystack contamination: a different synthetic user's session ('finished The Nightingale on January 25th') coexists with the correct user's session ('finished Nightingale last weekend'); both were retrieved and Sonnet picked the explicit-but-wrong-user date over the correct relative-time answer, answering 'The Nightingale was finished first' when gold was 'The Hate U Give'. Classifier called this wrong_rank but the correct memory was actually in context — the failure is in generation-stage contradiction resolution, not ranking.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-case6-d6585ce8` — For a 5-event concert-ordering question, Sonnet placed 'Billie Eilish' (actual session date Mar 18) after an 'outdoor series' event (Mar 25) because a later session (Apr 8) contained a backward reference ('like the Billie Eilish show') with no explicit date, and the model anchored to that backward mention instead of the earlier session's own date header, despite `temporalGenerationPrompt` instructing use of 'Session date' headers.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-patternC` — Items like 92a0aa75 (role duration) and ba358f49 (age at wedding) are classified in_context_all/generator-failed, but the gold answer requires subtracting or adding values from two different sessions; the generation prompt's instruction to 'answer in one sentence using only the facts directly required' does not instruct the model to perform cross-block arithmetic, so Sonnet hedges or hallucinates instead of computing.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-patternD` — The LME haystack contains shared/ultrachat sessions where different synthetic users make factually incompatible statements about the same events; when two retrieved blocks give contradictory explicit dates for the 'same' event, Sonnet selects the more specific/explicit date even when it belongs to a different user's session, because neither the prompt nor the retrieval pipeline signals which block belongs to which user identity.
  Source: `engram-go/results/research-notes-failure-patterns.md`
- `eng-sec4-chronosort-insufficient` — Exp 06 already tested chrono-sort; remaining temporal failures after chrono-sort trace to backward-reference confusion and missing sessions, not block ordering — sorting correct blocks chronologically does not help when a wrong cross-user block outcompetes the correct one.
  Source: `engram-go/results/research-notes-failure-patterns.md`

### c-045: A finding's dedup key included `category`, so the same defect reported by security/spec-violation/edges lenses got 3 dif

- `fleet-CI-10` — A cross-lens dedup unit test fed uniform mock inputs (same category label from two 'different' lenses) and passed, while the real code — which keys on the field the mock kept uniform — was broken.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-ORC-1` — A finding's dedup key included `category`, so the same defect reported by security/spec-violation/edges lenses got 3 different keys and never collapsed; separately a key included timestamp/UUID so 43,078 events produced 43,078 distinct hashes with zero collisions; separately an opt-in fingerprint escape hatch added to fix under-merging instead over-merged in reverse once more than one lens phrased the same bug differently (4 phrasings of one paginate.js:5 bug reported as 4 separately 'confirmed' findings).
  Source: `fleet/FAILURE-MODES.md`
- `fleet-orch-CI-10` — The original cross-lens dedup unit test used the SAME category label for both simulated lenses, so it passed even though the real code (which keyed dedup on category) was broken — the mock fixture encoded the implementer's assumption instead of modeling that real lenses assign different categories to the same defect.
  Source: `fleet/orchestration/FAILURE-MODES.md`
- `fleet-orch-ORC-1` — The instinct subsystem's repetition/toil detector hashed `tool:args:timestamp` as its dedup key across 43,078 logged events, producing 43,078 distinct hashes with zero collisions -- the identity key included the timestamp (per-occurrence variable data), so repetition was structurally undetectable.
  Source: `fleet/CODING-INVARIANTS.md`
- `fleet-orch-ORC-1a` — adversarial-loop.js's defaultFindingKey keyed dedup identity on `location|category`; the same defect flagged by the security, spec-violation, and edges lenses got three different keys because each lens used a different category, so duplicates never collapsed. First run against 3 planted defects reported confirmed_count:12 and ran to the round cap (~1M tokens) instead of terminating dry.
  Source: `fleet/orchestration/FAILURE-MODES.md`
- `fleet-orch-ORC-1b` — defaultFindingKey's location-only dedup key over-merges two distinct defects sharing one line, and suffers 'reject-poison': a rejected claim's key enters `seen` before verification, so it can block a later correct claim at the same line.
  Source: `fleet/orchestration/FAILURE-MODES.md`
- `fleet-orch-ORC-1c` — In Phase D's Adversarial smoke test (smoke-adversarial-worktree.js) against one planted off-by-one defect at paginate.js:5, codex and grok independently invented 4 different free-text fingerprints for the same bug; the FM-9 fingerprint escape hatch let these differing tags split what should have collapsed, so the loop reported confirmed_count:5 for one real defect (a 4x overcount) and dryStreak never advanced because each restated claim looked novel.
  Source: `fleet/orchestration/FAILURE-MODES.md`

### c-051: A trust/allowlist check matched the string `github

- `fleet-CI-2` — A URL/host trust check matched a trusted substring anywhere in the string, so `https://evil.example/github.com/owner/x` (substring in path) and `https://github.com@evil.com/...` (in userinfo) both passed as trusted (PR #19).
  Source: `fleet/FAILURE-MODES.md`
- `fleet-orch-CI-2` — A trust/allowlist check matched the string `github.com[:/]owner/repo` anywhere in a URL instead of parsing the host — an attacker-controlled host embedding the trusted string in its path (https://evil.example/github.com/petersimmons1972/x.git) or userinfo (https://github.com@evil.com/...) was wrongly trusted, enabling RCE/privilege escalation. Codex reproduced it live (PR #19, wrote a PWNED file); Codex and grok-4.5 independently reproduced the same substring bug plus a related ssh-port parse bug (ssh://...:22/owner parsed owner as '22').
  Source: `fleet/CODING-INVARIANTS.md`
- `hc-FM-130` — Two processes shared one token: a stale systemd `codex-attach.service` had been 401ing since 2026-06-25 alongside the container consumer. Its retry loop never exited, so `Restart=on-failure` never fired and systemd remained `active`; the unit also had no `WatchdogSec` or `OnFailure`. Observed in the 2026-07-03 audit ([claude-codex#362](https://github.com/petersimmons1972/claude-codex/issues/362)).
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-131` — A transient Postgres failure at report time can discard an otherwise completed LLM run: the Hermes consumer makes one `/report` attempt ([fleet-dispatch#133](https://github.com/petersimmons1972/fleet-dispatch/issues/133)), while Codex retries for only about 15 seconds. Structurally certain in the 2026-07-03 audit ([claude-codex#362](https://github.com/petersimmons1972/claude-codex/issues/362)).
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-132` — Canary items can enqueue indefinitely when no consumer claims their capability, so the canary certifies nothing while the queue grows ([fleet-dispatch#140](https://github.com/petersimmons1972/fleet-dispatch/issues/140)); identified in the 2026-07-03 audit ([claude-codex#362](https://github.com/petersimmons1972/claude-codex/issues/362)).
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-133` — In the opencode incident, an attach consumer crash-looped at startup because a required credential was missing. `ai-fleet-watcher` monitored model containers only, not attach consumers, so the failure was silent. The 2026-07-03 audit record ([claude-codex#362](https://github.com/petersimmons1972/claude-codex/issues/362)) is the sole incident reference supplied.
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-134` — A `comment_only` report can be syntactically valid yet semantically empty and still reach `done`, because that lane has neither an artifact gate nor a semantic deliverable check; structurally certain at the `/report` acceptance boundary in the 2026-07-03 audit ([claude-codex#362](https://github.com/petersimmons1972/claude-codex/issues/362)).
  Source: `hindsight/catalog/failure-modes.md`

### c-117: Lease dir unreadable/unwritable (e

- `hc-FM-135` — Issue labeled `in-progress` + lease exists but expired + different owner
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-136` — Second reconciler sees same lease generation, re-queues already-recovered issue
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-138` — 403 on label write silently releases a live lease, orphaning the work
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-142` — Dead projector means in-progress label stale while lease store is correct
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-144` — Lease dir unreadable/unwritable (e.g. systemd `ProtectHome=read-only` with default `CODEX_POLL_LEASE_DIR=${HOME}/.cache/...` not overridden to a ReadWritePath); reconciler scans empty store → classifies EVERY in-progress issue as `ORPHAN_NO_LEASE` → mass force-requeue of all live work
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-145` — `reconcile_label_missing()` second pass re-asserts `in-progress` on a completed+CLOSED issue whose lease hasn't expired (closed issues absent from `--state open` first pass) every sweep until TTL → misleading label + API-hammer loop
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-74` — Reconciler first pass only scans issues WITH the in-progress label; a poller that holds a live lease but whose in-progress label was silently dropped (race/API error) is never re-asserted
  Source: `hindsight/catalog/failure-modes.md`

### c-004: A codex-rescue bridge run doing a pure-review task failed at startup with `failed to initialize in-process app-server cl

- `ccx-FM-004` — Inside the codex exec sandbox (bwrap workspace-write), network egress was blocked and the worktree's linked .git backing store was read-only, so an Engram auth health check failed (codex-doctor ok=false) and git commit failed with '.git/index.lock: Read-only file system' even though the task required both capabilities.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `fleet-COM-5` — `codex exec` under workspace-write blocked egress and made the .git backing store read-only, failing both an Engram health check and a commit — capabilities the task required but the sandbox default never granted (PR #72).
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-22` — A codex-rescue bridge run doing a pure-review task failed at startup with `failed to initialize in-process app-server client: Read-only file system (os error 30)` because `--sandbox read-only` is too restrictive for codex's own app-server bootstrap, not just the task's writes — the run never got the prompt. Separately, a prompt opening with a leading `---` line (e.g. markdown frontmatter) was parsed by the CLI as an option token, corrupting the invocation before codex saw the intended text.
  Source: `fleet/FAILURE-MODES.md`
- `hc-FM-38` — Inner bwrap sandbox needs userns/seccomp; naive privilege probes invert on modern kernels → crash loop
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-61` — Codex CLI inner bwrap sandbox cannot create a user namespace inside a cap-dropped/no-new-privileges container → workspace-write tasks fail silently; no draft PR
  Source: `hindsight/catalog/failure-modes.md`
- `hc-FM-69` — A documented mitigation exists as a FLAG but is not threaded into the invocation: `CODEX_INNER_SANDBOX=off` is set in the image (per FM-61) but the `--dangerously-bypass-approvals-and-sandbox` it is meant to gate was not actually passed to `codex exec`, so impl tasks still hit the bwrap namespace failure ~20min in (2026-06-15, claude-codex#134)
  Source: `hindsight/catalog/failure-modes.md`

### c-063: `cli-dispatch start --harness grok

- `fleet-MDL-18` — Two independent subagents told to dispatch to Codex/Grok via cli-dispatch, collect the resulting critique, judge it, and report it instead launched the dispatch and terminated, describing future intent ('I'll report back once it lands', 'I'll wait for the completion notification') rather than producing a deliverable. Both underlying dispatches were in fact still running and healthy; the failure was silent and looked like a calm, plausible success message on both agents independently in the same turn.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-24` — A log-watcher agent monitoring bridge job task-mrzjz5mh-4oj4v5 reported it as the Codex review it was asked about, when the job's .json metadata (title: 'Grok Build Delegate') showed it was actually a Grok delegate running through a different state directory; the mislabel was caught only because the emitted verdict vocabulary (CONCUR-SOUND) didn't match the Codex review vocabulary (REJECT/NO-REJECT) the watcher expected.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-30` — Two subagents dispatched in parallel to the local Grok /imagine image CLI cross-contaminated: a 'Falling Barometer' render job came back with a 'Control Blank No. 0' plate — the sibling job's subject entirely, none of its own briefed botanicals — while file path, exit status, and the agent's own report all looked normal. Detected only because the subagent compared its output against its own brief; a coordinator trusting the returned path would have published the wrong plate.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-OPS-35` — `cli-dispatch start --harness grok ... --expect-files CRITIQUE.md` returned agent_exit: 0, status: committed-no-pr, leak: false, and a passing --expect-files assertion, but the produced CRITIQUE.md was a single byte containing the character 'x' — Grok's headless path silently truncated/failed on a long inline `-p` prompt with no error, while an otherwise-identical run using --brief-file produced a genuine 18,218-byte critique. A parallel hole in orchestration/src/harness-adapters.js's makeGrokAgent bypassed all of cli-dispatch's fixes by using the same inline -p argv channel with no length ceiling, until fixed 2026-07-30.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-ORC-10` — A bridge subagent (codex:codex-rescue / grok-build:grok-delegate) returned `status: completed` with a result string that actually said the work 'started in the background as <run-id>' — tool_uses:1 and duration in tens of seconds for a 15-30-call brief, while the plugin job JSON still read 'running' with no completedAt and the briefed output file didn't exist. Confirmed across 4 dispatches (2 Codex, 2 Grok), all notified completed within 21-57s while jobs were still running and output directories empty.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-ORC-16` — A subagent was dispatched to interview the founder with a batched question set, but subagents have no AskUserQuestion tool and their output is never surfaced to the user — the questions were emitted into a transcript no human read, and the agent reported the task complete.
  Source: `fleet/FAILURE-MODES.md`

### c-055: A throughput-sized num_predict=256 reused for a quality benchmark truncated a thinking-mode model's answer inside <think

- `fleet-CI-8` — A corruption-detection canary tested a correlated but different property (arithmetic ability), so a healthy 0.5B model too small for arithmetic failed the canary for a reason unrelated to corruption; a reasoning model separately failed by being pushed past its token window.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-MDL-2` — A throughput-sized num_predict=256 reused for a quality benchmark truncated a thinking-mode model's answer inside <think>, scoring the highest-fidelity (longest-reasoning) quant as least accurate; separately max_tokens=64 against 32k prompts made wall-clock prefill-dominated so aggregate_tok_s read flat (~5.85) across concurrency 1-64 while real per-stream decode swung 18x; separately a fixed budget of 1024 starved the hard tier of a tiered eval, leaving it most-truncated and least-supported (n=12/20 vs 19/20 easy).
  Source: `fleet/FAILURE-MODES.md`
- `fleet-orch-CI-8` — A GB10 benchmark campaign gated every model load with an arithmetic canary ('17+18'='35') meant to catch corrupt/degenerate output; a 0.5B model and qwen3 thinking-mode models failed this canary for benign reasons (too small to compute it; reasoning tokens pushed '35' past the token window) even though their throughput data was valid, conflating output correctness/capability with output corruption.
  Source: `fleet/CODING-INVARIANTS.md`
- `fleet-orch-MDL-2-FM14` — A GB10 quality x speed benchmark reused num_predict=256 (tuned for throughput measurement) to grade answer accuracy of qwen3:8b (thinking-mode); the model spent the whole budget inside <think> and never emitted an answer, scoring as degenerate/incorrect -- and this hit FP16 more often than Q4/Q8 (FP16 reasoned longer), making the highest-fidelity quant falsely appear least accurate.
  Source: `fleet/CODING-INVARIANTS.md`
- `fleet-orch-MDL-2-FM16` — A GB10 S1 context x concurrency serving benchmark ran max_tokens=64 against prompts up to 32k tokens; the headline aggregate_tok_s metric stayed flat (~5.7-5.95 tok/s) across concurrency 1/4/16/32/64 at 32k context despite per-stream decode rate varying ~18x (40.3->2.18 tok/s) and TTFT varying ~37x (9.6s->353.6s), because wall-clock was dominated by prefill/TTFT rather than decode with such a short generation window.
  Source: `fleet/CODING-INVARIANTS.md`
- `fleet-orch-MDL-2-FM19` — A GB10 Q2 tiered (easy/medium/hard) quality eval used one fixed num_predict=1024 budget for a thinking-mode model across all tiers; the hard tier (the one the experiment was designed to discriminate on) got truncated and excluded far more than easy: fp16 scored only 12/20 hard items and 16/20 medium vs 19/20 easy, so the hardest tier ended up with the thinnest evidence (n=12-13 vs planned 20) exactly where the clearest finding was reported.
  Source: `fleet/CODING-INVARIANTS.md`

### c-008: A GitHub issues

- `ccx-FM-009` — A GitHub issues.labeled webhook delivery failed silently (Ingress down, DNS gap, or notifier pod crash), so fleet-notifier never emitted a wake to the target node's SSE stream; the node fell back to waiting up to 30 minutes for the systemd timer with no alert firing on the gap.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `ccx-FM-010` — fleet-notifier pushed a wake to a node's SSE stream at the exact moment the node's connection was reconnecting; SSE has no guaranteed replay, so the wake was permanently lost and not recoverable from the stream on reconnect.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `ccx-FM-014` — When fleet-notifier is scaled to 0 or crashed, an SSE failure handler could incorrectly disable the fallback 30-min systemd timer (e.g. calling systemctl stop on reconnect failure), turning a bus outage that should only regress latency into an indefinite work-stoppage.
  Source: `claude-codex/docs/integration-failure-modes.md`
- `fleet-COM-13` — If an SSE reconnect-failure handler were to call something like systemctl stop on the fallback timer, a notifier outage would stop being a latency regression and become a full work-stoppage.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-COM-8` — A dropped webhook meant a node got no fast-path wake, but the 30-minute fallback timer absorbed it silently — no work was lost but nothing alerted that the fast path was down, so latency regressed indefinitely with no visible signal.
  Source: `fleet/FAILURE-MODES.md`
- `fleet-COM-9` — An SSE wake pushed while the subscriber was mid-reconnect was lost with no replay, since SSE is fire-and-forget.
  Source: `fleet/FAILURE-MODES.md`

## Singletons appendix

79 singleton clusters. A singleton is not proof of non-recurrence, only of non-detection.

## Provenance

Backend: `http`; threshold: `0.2`; linkage: `average`; input entry count: `484`.
