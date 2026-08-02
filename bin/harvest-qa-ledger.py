#!/usr/bin/env python3
"""Harvest per-actor QA results from workflow journals into a comparable ledger.

Baseline arm: every packet run 2026-08-01/02 used the SAME shape --
Claude builds (sonnet), Claude verifies (opus), same vendor both sides.
This harvests that arm so a cross-vendor adversary-first arm can be
compared against it rather than argued about.
"""
import json, glob, os, re, sys

D = "/home/psimmons/.claude/projects/-home-psimmons/8a4dc9d2-9a1d-4529-a992-9436e2790a9f/subagents/workflows"

RUNS = {
    "wf_94954b01-6ea": ("G1/G2/C7 build r1", 1),
    "wf_84e1ad58-d16": ("merge #5/#4/#1", 0),
    "wf_203552ca-954": ("G1/G2 repair r2", 2),
    "wf_8a748ad0-11d": ("C4b enforcement-scope", 1),
    "wf_5e5f98d6-f4f": ("C4c honest-enforcement", 2),
    "wf_0e6f038b-083": ("G2 rescope r3", 3),
    "wf_24e65f8a-144": ("C4d config-integrity", 3),
    "wf_e385c058-72d": ("G1 round3", 3),
    "wf_0c3f6fb5-cd6": ("C1c clustering-repair", 1),
    "wf_036f3ba2-130": ("G1 round4", 4),
    "wf_e83200e0-3cc": ("C4e ratchet", 4),
    "wf_fb9954f3-d11": ("G1 round5", 5),
    "wf_f7f228f5-3cc": ("C4f environment", 5),
    "wf_0dad5c7f-bf8": ("C1d corpus-grounded", 2),
    "wf_0f5ec394-f2d": ("C4g attestation", 6),
    "wf_62cdafad-1b8": ("C1e experiment", 0),
    "wf_5abdad5b-029": ("ArmB rerun", 0),
}

ROLE_PATTERNS = [
    ("verify", re.compile(r"ADVERSARIAL verif|You are an ADVERSARIAL", re.I)),
    ("decide", re.compile(r"pre-registered decision rule", re.I)),
    ("fixture", re.compile(r"You are the \*\*fixture author\*\*", re.I)),
    ("land", re.compile(r"Gate and merge PR", re.I)),
    ("audit", re.compile(r"Independent post-merge audit", re.I)),
    ("measure", re.compile(r"This is a MEASUREMENT", re.I)),
    ("build", re.compile(r"RED FIRST|Repair round|repairs? #", re.I)),
]

SEV = re.compile(r"\b(HIGH|MEDIUM|LOW|CRITICAL)\b")


def first_prompt(agent_file):
    try:
        with open(agent_file) as fh:
            for line in fh:
                e = json.loads(line)
                m = e.get("message") or {}
                if e.get("type") == "user" or m.get("role") == "user":
                    c = m.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                    if isinstance(c, str) and len(c) > 40:
                        return c[:4000]
    except Exception:
        pass
    return ""


def role_of(prompt):
    for name, pat in ROLE_PATTERNS:
        if pat.search(prompt):
            return name
    return "unknown"


def verdict_of(result):
    s = json.dumps(result) if not isinstance(result, str) else result
    if "VERDICT: CONFIRMED_GOOD" in s or '"verdict": "CONFIRMED_GOOD"' in s or "'verdict': 'CONFIRMED_GOOD'" in s:
        return "CONFIRMED_GOOD"
    if "VERDICT: DEFECTIVE" in s or '"verdict": "DEFECTIVE"' in s or "'verdict': 'DEFECTIVE'" in s:
        return "DEFECTIVE"
    if "VERDICT: fail" in s:
        return "FAIL"
    if "VERDICT: pass" in s:
        return "PASS"
    return ""


def severities(result):
    s = json.dumps(result) if not isinstance(result, str) else result
    out = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for m in SEV.finditer(s):
        out[m.group(1)] += 1
    return out


rows = []
for run_dir in sorted(glob.glob(os.path.join(D, "wf_*"))):
    run_id = os.path.basename(run_dir)
    packet, rnd = RUNS.get(run_id, (run_id, -1))
    jl = os.path.join(run_dir, "journal.jsonl")
    if not os.path.exists(jl):
        continue
    for line in open(jl):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") != "result":
            continue
        aid = e.get("agentId")
        meta_p = os.path.join(run_dir, f"agent-{aid}.meta.json")
        model = ""
        if os.path.exists(meta_p):
            try:
                model = json.load(open(meta_p)).get("model", "")
            except Exception:
                pass
        prompt = first_prompt(os.path.join(run_dir, f"agent-{aid}.jsonl"))
        res = e.get("result")
        sev = severities(res)
        rows.append({
            "run_id": run_id,
            "packet": packet,
            "round": rnd,
            "agent_id": aid,
            "vendor": "anthropic",
            "model": model,
            "role": role_of(prompt),
            "verdict": verdict_of(res),
            "sev_high": sev["HIGH"] + sev["CRITICAL"],
            "sev_medium": sev["MEDIUM"],
            "sev_low": sev["LOW"],
            "result_chars": len(json.dumps(res)) if res is not None else 0,
        })

out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(out_dir, exist_ok=True)
out_p = os.path.join(out_dir, "actor-results.jsonl")

# Rows this script did NOT produce -- cross-vendor actors run through
# cli-dispatch, not through workflows, so they have no journal to harvest and
# are appended by hand. A plain overwrite would delete them, which is the
# silent-data-loss family this repo exists to catalogue. Preserve anything
# whose run_id is not a workflow id, and say how many were carried over.
carried = []
if os.path.exists(out_p):
    for line in open(out_p):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not str(r.get("run_id", "")).startswith("wf_"):
            carried.append(r)

with open(out_p, "w") as fh:
    for r in rows + carried:
        fh.write(json.dumps(r) + "\n")
print(f"carried over {len(carried)} non-workflow row(s)")

# ---- summary ----
print(f"rows: {len(rows)} -> {out_p}")
by_role = {}
for r in rows:
    by_role.setdefault(r["role"], []).append(r)
print("\nrole            n   model(s)          verdicts")
for role, rs in sorted(by_role.items()):
    models = ",".join(sorted({x["model"] for x in rs if x["model"]}))
    vs = {}
    for x in rs:
        if x["verdict"]:
            vs[x["verdict"]] = vs.get(x["verdict"], 0) + 1
    print(f"{role:12} {len(rs):4}   {models:16}  {vs}")

# Denominator is rows that emitted a LITERAL verdict line, not every
# verify-role row. An actor that returned no verdict has not failed a
# verification -- it has failed to report one, which is a different defect and
# is counted separately below. Dividing by all verify-role rows understates the
# acceptance rate and hides the reporting gap inside it.
verifies = [r for r in rows if r["role"] == "verify"]
judged = [r for r in verifies if r["verdict"]]
silent = len(verifies) - len(judged)
good = [r for r in judged if r["verdict"] == "CONFIRMED_GOOD"]
print(f"\nADVERSARIAL VERIFY PASSES: {len(good)}/{len(judged)} "
      f"({100*len(good)/max(1,len(judged)):.0f}%) of actors that returned a verdict")
print(f"NO VERDICT LINE EMITTED:   {silent}/{len(verifies)} verify-role actors "
      f"-- the landing gate matches on that string, so these are unlandable by construction")
print("HIGH findings by verifies:", sum(r["sev_high"] for r in verifies))

lineage = {}
for r in rows:
    fam = r["packet"].split()[0]
    lineage.setdefault(fam, set()).add(r["round"])
print("\nrounds per lineage (same-vendor arm):")
for fam, rs in sorted(lineage.items()):
    rr = sorted(x for x in rs if x >= 0)
    if rr:
        print(f"  {fam:10} max round {max(rr)}")
