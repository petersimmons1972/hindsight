#!/usr/bin/env python3
"""One-shot build script for the plan-06 seed L3 ledger (hindsight#21).

This is the persisted spool the 2026-08-22 founder ruling permits at
pipeline/L3/work/ (docs/DECISIONS.md row 27). It is NOT re-run by CI or by
validate_l3.py -- it is the record of how pipeline/L3/invariants.jsonl's
initial 12 rows were derived, so the synthesis is reproducible and auditable
rather than a hand-typed ledger with no traceable path back to L2.

Scope, disclosed in docs/L3.md: this is a SEED ledger, not the full plan-06
W1 (four-family agent fanout) + W2 (global synthesis) pipeline. It covers the
12 of 51 multi-repo clusters in pipeline/L2/clusters.jsonl that are thematically
coherent enough for one honest invariant + procedural substitute each. The
remaining ~39 multi-repo clusters, and the three large but topically-mixed
clusters (c-058, c-059, c-061 -- wording-clustered grab-bags per the L2
clustering's own documented 1/77 blind-paraphrase recall limitation), are
named in docs/L3.md as follow-up scope rather than forced into one invariant
apiece.

Every `kind` in this seed ledger is `judgment`: no member of any of the 12
clusters below carries a non-null L1 `enforcement` field that resolves to a
path inside THIS repo (the only kind of path validate_l3.py --assert-paths-exist
can check without inventing cross-repo path resolution machinery plan-06 does
not specify -- see docs/L3.md's "why no machine rows yet" note).
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CLUSTERS_PATH = os.path.join(REPO_ROOT, "pipeline", "L2", "clusters.jsonl")
OUT_PATH = os.path.join(REPO_ROOT, "pipeline", "L3", "invariants.jsonl")

# Coordinator judgment: cluster_id -> (invariant, procedural_substitute).
# Grounded in each cluster's member `check` fields (pipeline/L1/*.jsonl); the
# prose is synthesis, the provenance (source_repos, members, first/last_seen)
# is read straight from pipeline/L2/clusters.jsonl by this script, never typed
# by hand.
SEED = {
    "c-001": (
        "Never accept a terminal/exit status alone as evidence a dispatched task, "
        "check, or run succeeded; verify the declared deliverable artifact.",
        "Before marking any dispatched task, job, or gate complete, verify the "
        "declared deliverable artifact directly (file exists with expected "
        "content or row count, PR present, live round-trip fetch) rather than "
        "trusting exit code, HTTP 200, a 'done' label, or a bridge exit message "
        "alone; re-verify liveness by artifact growth/stability, not by process "
        "or harness exit signals.",
    ),
    "c-004": (
        "A sandboxed task that needs network access or writes outside the "
        "sandbox default must have that capability explicitly granted and "
        "probed before it is relied on.",
        "When a task needs network access or write access outside the sandbox "
        "default, grant it explicitly in the sandbox config (network_access, "
        "writable_roots) and run a post-deploy in-sandbox health probe that "
        "exercises the granted capability end-to-end before depending on it in "
        "the real task.",
    ),
    "c-007": (
        "A task's delivery/routing decision must read one explicit, "
        "producer-set signal, never be inferred from report shape or a "
        "side-channel label.",
        "Route a task's delivery/disposition off one explicit, producer-set "
        "field (e.g. expected_delivery) recorded at enqueue time; never infer "
        "delivery mode from report prose shape or a side-channel label the "
        "producing path did not itself set.",
    ),
    "c-014": (
        "A dispatch capability must be validated against a known registry at "
        "enqueue time, bound to exactly one intended consumer, and its "
        "credential identity verified by fingerprint after any provisioning "
        "change.",
        "Validate a dispatch capability against a known-capability registry at "
        "enqueue time (reject unknowns with a structured error, e.g. HTTP 422); "
        "assign each capability exactly one intended consumer; verify "
        "token/credential identity by fingerprint against the secrets source "
        "after any provisioning change, confirmed by a canary claim against a "
        "known non-empty queue.",
    ),
    "c-033": (
        "N-lane or N-reviewer agreement is not independent corroboration unless "
        "each lane used an independent prompt, objective, and vendor identity.",
        "Before crediting N-lane or N-reviewer agreement as independent "
        "corroboration, confirm each lane used an independent prompt/objective "
        "and a distinct vendor/harness identity that fails closed rather than "
        "borrowing an ambient credential; reviewers that share a vendor, model, "
        "or cite the same secondary artifact count as N=1, not N.",
    ),
    "c-036": (
        "A process check must never match on a pattern the checking command's "
        "own invocation can itself satisfy.",
        "Match a process for kill or liveness check by PID, or by a token "
        "guaranteed absent from the checking command's own invocation, never by "
        "a substring/pattern (pkill -f, grep, pgrep -f) that can match the "
        "checker's own command line; corroborate a negative liveness result "
        "with a second signal (e.g. log growth) before acting on it.",
    ),
    "c-051": (
        "A gate must assert on structured status and its own tested artifact "
        "locator, and a regression test for a live failure must be proven "
        "against the real system before it is encoded.",
        "A gate must assert on structured status (not exit code alone) and "
        "report the concrete artifact locator it actually tested, so a mismatch "
        "is checkable; before writing a regression test for a live failure, "
        "reproduce that failure directly against the real system and record "
        "the confirmed exit code/error/log line before encoding it as the test.",
    ),
    "c-056": (
        "In a shared or concurrently-used git checkout, the actual branch/ref "
        "and remote state must be verified immediately before any commit, "
        "push, reset, or worktree removal -- never assumed from a brief or a "
        "prior report.",
        "In any shared or concurrently-used git checkout, verify the actual "
        "branch/ref (git rev-parse --abbrev-ref HEAD / git branch --show-current) "
        "and remote state (fetch + ls-tree/log against origin) immediately "
        "before any commit, push, reset, or worktree-remove; never assume the "
        "target branch, base, or worktree ownership from a brief, a flag, or a "
        "prior agent's self-report.",
    ),
    "c-062": (
        "Denying a capability by scrubbing one environment variable is "
        "incomplete unless every other reachable channel is enumerated and "
        "confirmed closed.",
        "When denying a capability by scrubbing an environment variable, "
        "enumerate every reachable channel that could still carry it (same-user "
        "IPC: D-Bus session bus, keyring/agent sockets, shared memory) and "
        "verify each is actually closed; to test whether a channel causes a "
        "capability, remove it and confirm the removal took effect, then "
        "retest -- never substitute a flag or alternate config believed to "
        "bypass it.",
    ),
    "c-079": (
        "A coordinator must never yield on a dispatched or background delegate "
        "without either a verified deliverable artifact or a confirmed-live "
        "process it is actively polling.",
        "A coordinator must not yield on a dispatched or background delegate "
        "without either (1) a terminal receipt confirming the declared "
        "deliverable artifact exists (non-empty, matching the brief's subject), "
        "or (2) a verified-live background process/job-registry entry it is "
        "actively polling; never accept a self-reported 'waiting' or "
        "future-tense status as evidence of progress.",
    ),
    "c-088": (
        "Merge-readiness must be gated on a check-run re-confirmed against the "
        "PR's current base, never a cached rollup or a check-run timestamp "
        "predating a rebase.",
        "Gate merge-readiness on a check-run re-confirmed against the PR's "
        "current base commit (fetch + compare timestamps against the last "
        "CI-infra change on main), not a cached statusCheckRollup or a "
        "check-run timestamp predating a rebase or retarget; re-run any check "
        "invalidated by a base change before merging.",
    ),
    "c-105": (
        "A git worktree removal is not safe merely because git permits it; "
        "untracked files, stash scope, and reflog/gc timing must all be "
        "checked first.",
        "Before deleting a git worktree, audit it for untracked files "
        "(git status --porcelain) since git's removal safety guarantees cover "
        "tracked content only, and never assume a worktree's stash entries are "
        "scoped to that worktree (stash is per-repository); never run "
        "`git gc --prune=now` or `git reflog expire --all` in the same pass as "
        "a deletion whose reversibility is being claimed.",
    ),
}


def main():
    with open(CLUSTERS_PATH) as f:
        clusters = {}
        for i, line in enumerate(f):
            if i == 0:
                continue
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            clusters[d["cluster_id"]] = d

    rows = []
    for n, (cid, (invariant, substitute)) in enumerate(SEED.items(), start=1):
        c = clusters[cid]
        source_repos = sorted(set(c["source_repos"]))
        assert len(source_repos) >= 2, f"{cid} is not multi-repo, refusing to seed it"
        # Schema matches the founder-authorized ground truth fixture
        # (pipeline/tests/fixtures/l3_ground_truth.jsonl, PR #63): cluster_ids
        # and source_repos live directly on the row, not behind a nested
        # provenance object the validator would have to cross-reference.
        row = {
            "id": f"L3-{n:03d}",
            "cluster_ids": [cid],
            "source_repos": source_repos,
            "kind": "judgment",
            "invariant": invariant,
            "enforcement": None,
            "procedural_substitute": substitute,
            "member_count": c["size"],
            "members": c["members"],
            "first_seen": c.get("first_seen"),
            "last_seen": c.get("last_seen"),
        }
        rows.append(row)

    with open(OUT_PATH, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print(f"wrote {len(rows)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
