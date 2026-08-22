#!/usr/bin/env bash
# add-failure-mode.sh — append a new failure-mode entry to the canonical catalog.
#
# Usage:
#   add-failure-mode.sh [OPTIONS] TITLE [DESCRIPTION]
#   add-failure-mode.sh [OPTIONS]   # prompts for TITLE if stdin is a tty
#
# Options:
#   -c CLASS    Bug class letter (A-L) or explicit bug-class label.
#   -i ISSUE    GitHub issue number (appended to the concrete-instance column).
#   -a          Mark the row as automatable (`Auto?` = 🤖).
#   -t TIER     Criticality tier: CRITICAL|HIGH|MEDIUM|LOW. Required for the
#               canonical catalog; recorded in catalog/criticality.jsonl at
#               filing time so the backlog never regrows untriaged. Generality
#               defaults to NARROW (unassessed for cross-repo applicability);
#               hindsight-triage may upgrade it later.
#   --disposition mechanize|brief-inject|advisory
#               Required. Closed set. Recorded in catalog/criticality.jsonl.
#               A filing with --recurrence-of c-NNN is force-promoted to
#               mechanize regardless of this flag (--recurrence-of none is not).
#   --recurrence-of c-NNN|none
#               Record the human recurrence decision after corpus review.
#               c-NNN is a cluster id, not an FM id.
#   --undo DIR  Restore every file recorded in a prior run's undo journal.
#   -h          Show this help and exit successfully.
#
# TITLE is the check statement / rule (one sentence).
# DESCRIPTION is optional concrete-instance context for the catalog row.
#
# An undo journal is emitted before every write. Canonical adds also regenerate
# the derived L1/L2 artifacts and reconcile them before reporting success.
#
# Environment:
#   CATALOG     Override catalog path (default: <repo>/catalog/failure-modes.md).
#               Useful for testing: CATALOG=/tmp/fms-test.md add-failure-mode.sh ...
#   CRITICALITY Override criticality JSONL (default: sibling of CATALOG).
#               Scratch catalogs therefore never write catalog/criticality.jsonl.
#   CORPUS      Override the L1 corpus directory consulted before writing.
#   CLUSTERS    Override the L2 clusters artifact used to validate c-NNN.
#
# Install: ln -sf ~/projects/hindsight/bin/add-failure-mode.sh ~/bin/add-failure-mode.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CATALOG="${CATALOG:-$REPO_ROOT/catalog/failure-modes.md}"

usage() {
    grep '^#' "$0" | sed 's/^# \?//'
    exit "${1:-1}"
}

restore_journal() {
    local journal="$1"
    local manifest="$journal/manifest.tsv"
    local targets_file="$journal/targets.tsv"
    [[ -d "$journal" && -f "$manifest" && ! -L "$manifest" && -f "$targets_file" && ! -L "$targets_file" ]] || {
        echo "ERROR: undo journal not found: $journal" >&2
        return 1
    }

    # The transaction records every target at snapshot time.  Restore must use
    # that recorded set rather than a second, manually-maintained list: a new
    # artifact added to the write transaction is undoable by construction.
    local -A owned=() seen=()
    local -a expected=()
    local target extra normalized line_number=0
    while IFS=$'\t' read -r target extra; do
        line_number=$((line_number + 1))
        [[ -z "$extra" && -n "$target" ]] || {
            echo "ERROR: malformed undo journal target at line $line_number: $targets_file" >&2
            return 1
        }
        normalized="$(realpath -m -- "$target")"
        [[ "$target" == "$normalized" && -z "${owned[$normalized]:-}" ]] || {
            echo "ERROR: duplicate or non-canonical undo journal target: $target" >&2
            return 1
        }
        owned["$normalized"]=1
        expected+=("$normalized")
    done <"$targets_file"
    [[ ${#expected[@]} -gt 0 ]] || {
        echo "ERROR: undo journal target set is empty" >&2
        return 1
    }

    local -a states=() targets=() backups=()
    local state backup
    line_number=0
    while IFS=$'\t' read -r state target backup extra; do
        line_number=$((line_number + 1))
        [[ -z "$extra" && -n "$state" && -n "$target" && -n "$backup" ]] || {
            echo "ERROR: malformed undo journal at line $line_number: $manifest" >&2
            return 1
        }
        normalized="$(realpath -m -- "$target")"
        [[ "$target" == "$normalized" && -n "${owned[$normalized]:-}" ]] || {
            echo "ERROR: undo journal target is not owned by this run: $target" >&2
            return 1
        }
        [[ -z "${seen[$normalized]:-}" ]] || {
            echo "ERROR: duplicate undo journal target: $target" >&2
            return 1
        }
        case "$state" in
            present)
                [[ "$backup" =~ ^file-[0-9]+$ && -f "$journal/$backup" && ! -L "$journal/$backup" ]] || {
                    echo "ERROR: undo snapshot missing: $journal/$backup" >&2
                    return 1
                }
                ;;
            absent)
                [[ "$backup" == "-" ]] || {
                    echo "ERROR: malformed absent-file entry in undo journal: $target" >&2
                    return 1
                }
                ;;
            *)
                echo "ERROR: malformed undo journal: $manifest" >&2
                return 1
                ;;
        esac
        seen["$normalized"]=1
        states+=("$state")
        targets+=("$normalized")
        backups+=("$backup")
    done <"$manifest"

    [[ ${#targets[@]} -eq ${#expected[@]} ]] || {
        echo "ERROR: undo journal target set is incomplete" >&2
        return 1
    }
    for target in "${expected[@]}"; do
        target="$(realpath -m -- "$target")"
        [[ -n "${seen[$target]:-}" ]] || {
            echo "ERROR: undo journal is missing owned target: $target" >&2
            return 1
        }
    done

    local rollback_dir
    rollback_dir="$(mktemp -d "${TMPDIR:-/tmp}/hindsight-undo-rollback.XXXXXX")"
    local -a previous_states=() previous_backups=()
    local index previous_backup
    for index in "${!targets[@]}"; do
        if [[ -e "${targets[$index]}" ]]; then
            [[ -f "${targets[$index]}" && ! -L "${targets[$index]}" ]] || {
                echo "ERROR: undo target is not a regular owned file: ${targets[$index]}" >&2
                rm -r -- "$rollback_dir"
                return 1
            }
            previous_backup="current-$index"
            if ! cp "${targets[$index]}" "$rollback_dir/$previous_backup"; then
                echo "ERROR: could not stage pre-undo recovery copy: ${targets[$index]}" >&2
                rm -r -- "$rollback_dir"
                return 1
            fi
            previous_states+=(present)
            previous_backups+=("$previous_backup")
        else
            previous_states+=(absent)
            previous_backups+=(-)
        fi
    done

    local restore_status=0
    for index in "${!targets[@]}"; do
        if [[ "${states[$index]}" == "present" ]]; then
            if cp "$journal/${backups[$index]}" "${targets[$index]}"; then
                :
            else
                restore_status=$?
                break
            fi
        else
            if rm -f -- "${targets[$index]}"; then
                :
            else
                restore_status=$?
                break
            fi
        fi
    done

    if [[ $restore_status -ne 0 ]]; then
        echo "ERROR: undo apply failed; restoring the complete pre-undo state" >&2
        local rollback_failed=0
        for index in "${!targets[@]}"; do
            if [[ "${previous_states[$index]}" == "present" ]]; then
                cp "$rollback_dir/${previous_backups[$index]}" "${targets[$index]}" || rollback_failed=1
            else
                rm -f -- "${targets[$index]}" || rollback_failed=1
            fi
        done
        if [[ $rollback_failed -ne 0 ]]; then
            echo "ERROR: compensating rollback was incomplete; recovery copies remain at $rollback_dir" >&2
            return 1
        fi
        echo "add-failure-mode: compensating rollback restored pre-undo state; recovery copies remain at $rollback_dir" >&2
        return "$restore_status"
    fi

    rm -r -- "$rollback_dir"
    echo "add-failure-mode: restored files from $journal"
}

if [[ "${1:-}" == "--undo" ]]; then
    [[ $# -eq 2 ]] || { echo "ERROR: --undo requires exactly one journal directory" >&2; exit 1; }
    restore_journal "$2"
    exit $?
fi

CLASS=""
ISSUE=""
AUTO=0
TIER=""
TIER_SEEN=0
DISPOSITION=""
DISPOSITION_SEEN=0
RECURRENCE_OF=""
RECURRENCE_SEEN=0
POSITIONAL=()
DISPOSITION_VALUES="mechanize, brief-inject, or advisory"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--class)
            [[ $# -ge 2 ]] || { echo "ERROR: $1 requires a value" >&2; exit 1; }
            CLASS="${2^^}"; shift 2
            ;;
        -i|--issue)
            [[ $# -ge 2 ]] || { echo "ERROR: $1 requires a value" >&2; exit 1; }
            ISSUE="$2"; shift 2
            ;;
        -a|--auto)  AUTO=1; shift ;;
        -t|--tier)
            [[ $# -ge 2 ]] || { echo "ERROR: $1 requires a value" >&2; exit 1; }
            case "${2^^}" in
                CRITICAL|HIGH|MEDIUM|LOW) TIER="${2^^}" ;;
                *) echo "ERROR: -t/--tier accepts CRITICAL, HIGH, MEDIUM, or LOW" >&2; exit 1 ;;
            esac
            TIER_SEEN=1; shift 2
            ;;
        --disposition)
            [[ $# -ge 2 ]] || {
                echo "ERROR: --disposition requires $DISPOSITION_VALUES" >&2
                exit 1
            }
            [[ $DISPOSITION_SEEN -eq 0 ]] || {
                echo "ERROR: --disposition may be given once; accepted values are $DISPOSITION_VALUES" >&2
                exit 1
            }
            case "$2" in
                mechanize|brief-inject|advisory) DISPOSITION="$2" ;;
                *)
                    echo "ERROR: --disposition accepts $DISPOSITION_VALUES" >&2
                    exit 1
                    ;;
            esac
            DISPOSITION_SEEN=1
            shift 2
            ;;
        --recurrence-of)
            [[ $# -ge 2 ]] || {
                echo "ERROR: --recurrence-of requires c-NNN or none" >&2
                exit 1
            }
            [[ $RECURRENCE_SEEN -eq 0 ]] || {
                echo "ERROR: --recurrence-of may be given once; accepted forms are c-NNN or none" >&2
                exit 1
            }
            if [[ "$2" != "none" && ! "$2" =~ ^c-[0-9]{3}$ ]]; then
                echo "ERROR: --recurrence-of accepts c-NNN or none" >&2
                exit 1
            fi
            RECURRENCE_OF="$2"; shift 2
            RECURRENCE_SEEN=1
            ;;
        -h|--help)  usage 0 ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do POSITIONAL+=("$1"); shift; done
            ;;
        -*)         echo "unknown flag: $1" >&2; usage ;;
        *)           POSITIONAL+=("$1"); shift ;;
    esac
done

[[ $DISPOSITION_SEEN -eq 1 ]] || {
    echo "ERROR: --disposition is required; accepted values are $DISPOSITION_VALUES" >&2
    exit 1
}

[[ ${#POSITIONAL[@]} -le 2 ]] || {
    echo "ERROR: expected TITLE and optional DESCRIPTION" >&2
    exit 1
}
TITLE="${POSITIONAL[0]:-}"
DESC="${POSITIONAL[1]:-}"

# If no title given, prompt when interactive, read line when piped
if [[ -z "$TITLE" ]]; then
    if [[ -t 0 ]]; then
        read -r -p "Check/title (one sentence): " TITLE
    else
        read -r TITLE
    fi
fi

[[ -z "$TITLE" ]] && { echo "ERROR: title is required" >&2; exit 1; }
[[ -f "$CATALOG" ]] || { echo "ERROR: catalog not found: $CATALOG" >&2; exit 1; }
CATALOG="$(realpath -e -- "$CATALOG")"

# Consult the corpus before interpreting the human recurrence decision. The
# lookup is advisory: its status describes only whether measurement happened.
LOOKUP_ARGS=()
if [[ -n "${CORPUS+x}" ]]; then
    LOOKUP_ARGS+=(--corpus "$CORPUS")
fi
LOOKUP_QUERY="$TITLE"
[[ -n "$DESC" ]] && LOOKUP_QUERY="$TITLE $DESC"
set +e
LOOKUP_OUTPUT="$(python3 "$REPO_ROOT/bin/similar-causes.py" "${LOOKUP_ARGS[@]}" "$LOOKUP_QUERY" 2>&1)"
LOOKUP_STATUS=$?
set -e
printf '%s\n' "$LOOKUP_OUTPUT"
[[ $LOOKUP_STATUS -eq 0 ]] || exit "$LOOKUP_STATUS"

CANDIDATE_SEEN=0
while IFS= read -r line; do
    if [[ "$line" =~ ^[0-9]+([.][0-9]+)?[[:space:]]*\| ]]; then
        CANDIDATE_SEEN=1
        break
    fi
done <<<"$LOOKUP_OUTPUT"
[[ $CANDIDATE_SEEN -eq 1 ]] || echo "Corpus lookup measured; no advisory candidates found."

if [[ $RECURRENCE_SEEN -eq 0 ]]; then
    echo "ERROR: recurrence decision required; rerun with --recurrence-of c-NNN or --recurrence-of none" >&2
    exit 1
fi

CLUSTERS="${CLUSTERS:-$REPO_ROOT/pipeline/L2/clusters.jsonl}"
if [[ "$RECURRENCE_OF" != "none" ]]; then
    python3 - "$CLUSTERS" "$RECURRENCE_OF" <<'PYEOF'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
wanted = sys.argv[2]
try:
    lines = path.read_text(encoding="utf-8").splitlines()
except OSError as exc:
    raise SystemExit(f"ERROR: clusters artifact unavailable: {path}: {exc}")

found = set()
try:
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {number} is not an object")
        cluster_id = value.get("cluster_id")
        if isinstance(cluster_id, str):
            found.add(cluster_id)
except (json.JSONDecodeError, ValueError) as exc:
    raise SystemExit(f"ERROR: clusters artifact is malformed: {path}: {exc}")

if wanted not in found:
    raise SystemExit(f"ERROR: recurrence cluster {wanted} does not exist in clusters artifact: {path}")
PYEOF
fi

# A recurrence against a live cluster is the second time this cause has
# been catalogued. That filing is force-promoted to mechanize even if the
# caller asked for brief-inject or advisory: a repeated FM costs tokens
# forever until a guard exists.
EFFECTIVE_DISPOSITION="$DISPOSITION"
if [[ "$RECURRENCE_OF" != "none" ]]; then
    EFFECTIVE_DISPOSITION="mechanize"
fi

CANONICAL_CATALOG="$(realpath -e -- "$REPO_ROOT/catalog/failure-modes.md")"
RUN_FULL_LOOP=0
if [[ "$CATALOG" == "$CANONICAL_CATALOG" ]]; then
    RUN_FULL_LOOP=1
    REQUIRED_TOPOLOGY=(
        "$REPO_ROOT/../fleet/FAILURE-MODES.md"
        "$REPO_ROOT/../fleet/orchestration/FAILURE-MODES.md"
        "$REPO_ROOT/../fleet/CODING-INVARIANTS.md"
        "$REPO_ROOT/../fleet/CODING-FAILURE-MODES.md"
        "$REPO_ROOT/../claude-codex/docs/integration-failure-modes.md"
        "$REPO_ROOT/../fleet-dispatch/migrations/0017_failure_class.sql"
    )
    TOPOLOGY_MISSING=0
    for source_path in "${REQUIRED_TOPOLOGY[@]}"; do
        if [[ ! -f "$source_path" || ! -r "$source_path" ]]; then
            echo "ERROR: full-loop source unavailable: $source_path" >&2
            TOPOLOGY_MISSING=1
        fi
    done
    [[ $TOPOLOGY_MISSING -eq 0 ]] || {
        echo "ERROR: canonical ingest requires the complete sibling-repository topology; no files were written" >&2
        exit 1
    }
    [[ $TIER_SEEN -eq 1 ]] || {
        echo "ERROR: -t/--tier is required for the canonical catalog (CRITICAL|HIGH|MEDIUM|LOW)" >&2
        exit 1
    }
fi

FM_ID="$(python3 "$REPO_ROOT/guard/failure_mode_catalog_guard.py" --next-id "$CATALOG")"

class_label() {
    case "${1^^}" in
        A) echo "Identity vs. Routing" ;;
        B) echo "Install / Config Layout Integrity" ;;
        C) echo "Portability" ;;
        D) echo "Fail-Loud" ;;
        E) echo "Thermal / Resource-Role Safety" ;;
        F) echo "Repo Hygiene / Canonical Home" ;;
        G) echo "Deploy / Verify Discipline" ;;
        H) echo "Ephemeral Resource Leakage / Host Exhaustion" ;;
        I) echo "Container Runtime — Design" ;;
        J) echo "Container Runtime — Operational" ;;
        K) echo "Agent Runtime / Coordination" ;;
        L) echo "GitOps Declarative Drift" ;;
        "") echo "Unclassified" ;;
        *) echo "$1" ;;
    esac
}

BUG_CLASS="$(class_label "$CLASS")"

# ── Build entry components ────────────────────────────────────────────────────

AUTO_MARKER="Judgment"
[[ $AUTO -eq 1 ]] && AUTO_MARKER="🤖"

# Table row: | FM-NNN | Bug class | Concrete instance | Check that catches it | Auto? |
TABLE_DESC="${DESC:-${TITLE}} [recurrence_of: ${RECURRENCE_OF}]"
[[ -n "$ISSUE" ]] && TABLE_DESC="${TABLE_DESC} (GitHub #${ISSUE})"
TABLE_ROW="| ${FM_ID} | ${BUG_CLASS} | ${TABLE_DESC} | ${TITLE} | ${AUTO_MARKER} |"

# ── Undo journal before write ─────────────────────────────────────────────────

LEDGER="$(dirname "$CATALOG")/id-ledger.txt"
if [[ ! -f "$LEDGER" ]]; then
    echo "ERROR: id ledger not found: $LEDGER" >&2
    echo "  Restore it from git; do not regenerate it from the catalog." >&2
    exit 1
fi

JOURNAL="$(mktemp -d "${TMPDIR:-/tmp}/hindsight-add-failure-mode.XXXXXX")"
MANIFEST="$JOURNAL/manifest.tsv"
TARGETS_FILE="$JOURNAL/targets.tsv"
SNAPSHOT_NUMBER=0
snapshot_file() {
    local target="$1"
    local backup
    target="$(realpath -m -- "$target")"
    SNAPSHOT_NUMBER=$((SNAPSHOT_NUMBER + 1))
    backup="file-${SNAPSHOT_NUMBER}"
    printf '%s\n' "$target" >>"$TARGETS_FILE"
    if [[ -f "$target" ]]; then
        cp "$target" "$JOURNAL/$backup"
        printf 'present\t%s\t%s\n' "$target" "$backup" >>"$MANIFEST"
    else
        printf 'absent\t%s\t-\n' "$target" >>"$MANIFEST"
    fi
}

CRITICALITY="${CRITICALITY:-$(dirname "$CATALOG")/criticality.jsonl}"

snapshot_file "$CATALOG"
snapshot_file "$LEDGER"
snapshot_file "$CRITICALITY"
if [[ $RUN_FULL_LOOP -eq 1 ]]; then
    snapshot_file "$REPO_ROOT/pipeline/L1/homelab-canon.jsonl"
    snapshot_file "$REPO_ROOT/pipeline/L1/fleet-dispatch-schema.jsonl"
    snapshot_file "$REPO_ROOT/pipeline/L2/clusters.jsonl"
    snapshot_file "$REPO_ROOT/pipeline/L2/embedding-snapshot.json"
    snapshot_file "$REPO_ROOT/pipeline/L2/recall-baselines.json"
    snapshot_file "$REPO_ROOT/docs/POINTER.md"
    snapshot_file "$REPO_ROOT/docs/HIGH.md"
    snapshot_file "$REPO_ROOT/pipeline/tests/test_replay_l2.py"
    snapshot_file "$REPO_ROOT/pipeline/tests/test_replay_l2_mutations.py"
fi

printf 'UNDO: CATALOG=%q CRITICALITY=%q bash %q --undo %q\n' "$CATALOG" "$CRITICALITY" "$0" "$JOURNAL"

JOURNAL_READY=1
rollback_on_error() {
    local status=$?
    if [[ $status -ne 0 && ${JOURNAL_READY:-0} -eq 1 ]]; then
        echo "add-failure-mode: operation failed; applying undo journal" >&2
        if ! restore_journal "$JOURNAL" >&2; then
            echo "ERROR: undo journal restoration failed: $JOURNAL" >&2
            status=1
        fi
    fi
    exit "$status"
}
trap rollback_on_error EXIT

# ── Insert the canonical catalog row ───────────────────────────────────────────

python3 - "$CATALOG" "$TABLE_ROW" <<'PYEOF'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
table_row = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
table_row_pat = re.compile(r'^\| FM-\d+')

last_table_row = None
for i, line in enumerate(lines):
    if table_row_pat.match(line):
        last_table_row = i

if last_table_row is None:
    lines.append(table_row + '\n')
else:
    lines.insert(last_table_row + 1, table_row + '\n')

path.write_text(''.join(lines), encoding="utf-8")
PYEOF

# ── Record the ID in the append-only ledger ───────────────────────────────────
# The ledger is the baseline that makes "never delete a catalog row" a mechanism
# rather than a sentence. It must be OLDER than the change it checks, so this
# script REFUSES when it is absent instead of regenerating it from the catalog:
# reseeding from the current catalog would launder any deletion that had already
# happened, which is precisely the failure the ledger exists to catch.
printf '%s\n' "$FM_ID" >> "$LEDGER"

# Disposition (and tier, when supplied) are recorded beside the catalog so a
# scratch CATALOG override never writes the real catalog/criticality.jsonl.
# Existing rows without a disposition field are pre-O2; readers must tolerate
# their absence rather than treating it as mechanize.
python3 - "$CRITICALITY" "$FM_ID" "${TIER:-}" "$TITLE" "$DESC" "$EFFECTIVE_DISPOSITION" <<'PYEOF'
import datetime
import json
import sys

path, fm_id, tier, title, desc, disposition = sys.argv[1:7]
evidence = f"{title} {desc}".strip()
row = {
    "fm_id": fm_id,
    "tier": tier or None,
    "generality": "NARROW",
    "rationale": "filed at creation time",
    "evidence": evidence,
    "mechanize_action": "n/a",
    "scored_by": "add-failure-mode.sh (write-time)",
    "date": datetime.date.today().isoformat(),
    "disposition": disposition,
}
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(row) + "\n")
PYEOF

if [[ $RUN_FULL_LOOP -eq 1 ]]; then
    python3 "$REPO_ROOT/guard/failure_mode_catalog_guard.py" "$CATALOG"
    python3 "$REPO_ROOT/pipeline/extract_mechanical.py"

    # Release the L2 embedding snapshot through the sanctioned controlled
    # command (hindsight#108). A canonical add grows pipeline/L1, so the
    # committed pipeline/L2/embedding-snapshot.json must be re-derived from it
    # in the same write, or catalog-guard's replay check (pipeline/replay_l2.py)
    # goes red the moment CI notices -- after the commit already landed. This is
    # the only caller of capture_embedding_snapshot.py in the write path; a
    # scratch-catalog add (RUN_FULL_LOOP=0) never reaches it.
    python3 "$REPO_ROOT/pipeline/capture_embedding_snapshot.py" \
        --model "BAAI/bge-m3" --revision "bge-m3-Q8_0.gguf" --dimensions 1024

    # pipeline/L2/clusters.jsonl must be derived from that same freshly
    # released snapshot -- not from an independent live-embedding run -- so it
    # is guaranteed replayable from what was just committed.
    python3 - "$REPO_ROOT" <<'PYEOF'
import importlib.util
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
code = repo_root / "pipeline" / "cluster.py"
spec = importlib.util.spec_from_file_location("hindsight_release_cluster", code)
cl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cl
spec.loader.exec_module(cl)

l1 = repo_root / "pipeline" / "L1"
snapshot = repo_root / "pipeline" / "L2" / "embedding-snapshot.json"
clusters_path = repo_root / "pipeline" / "L2" / "clusters.jsonl"

entries = cl.load_entries(l1)
l1_digest = cl.l1_corpus_digest(l1)
cluster_digest = cl.cluster_code_config_digest(code)
matrix = cl.load_embedding_snapshot(
    snapshot, entries, cl.HTTP_BACKEND_IDENTITY,
    expected_l1_digest=l1_digest, expected_cluster_digest=cluster_digest,
)
threshold = cl.default_threshold("http")
ordered = sorted(entries, key=lambda entry: entry.id)
clusters = cl.cluster_entries(ordered, matrix, backend_name="http", threshold=threshold)


class _ReleasedBackend:
    name = "http"


cl.write_clusters(clusters_path, clusters, _ReleasedBackend(), threshold, len(entries))
PYEOF

    # Ratchet the ground-truth recall baselines against the partition just
    # written (founder ruling 2026-08-19, hindsight#121). A canonical add grows
    # the corpus, and corpus growth is exactly what degraded
    # shared-mutable-checkout below the old absolute 0.75 floor. This records
    # the new per-(family,backend) recall -- and REFUSES the write if any family
    # dropped, so a regression cannot ride in on a routine catalog add. Measured
    # against `released` only: the live backends are re-measured by the test
    # suite, and an add must not depend on the embedding host being up twice.
    # To accept a drop deliberately:
    #   pipeline/recall_baselines.py --update --allow-drop --reason "..."
    RECALL_BASELINE_ARGS=(--update --backend released)
    if [[ -n "${HINDSIGHT_ALLOW_RECALL_DROP_REASON:-}" ]]; then
        RECALL_BASELINE_ARGS+=(--allow-drop --reason "$HINDSIGHT_ALLOW_RECALL_DROP_REASON")
    fi
    python3 "$REPO_ROOT/pipeline/recall_baselines.py" "${RECALL_BASELINE_ARGS[@]}"

    # The exact consistency check catalog-guard runs in CI. If the release
    # somehow still leaves the tree inconsistent (a no-op release, a release
    # that destroyed its own evidence, etc.) this fails loudly here, before
    # commit, and the trap below rolls the whole write back.
    REPLAY_OUTPUT="$(python3 "$REPO_ROOT/pipeline/replay_l2.py")"
    printf '%s\n' "$REPLAY_OUTPUT"

    # Replay pins are updated and verified by one plain-Python registry.  This
    # deliberately does not invoke pytest: ambient collection/plugin settings
    # can make a test runner exit zero without executing a test.  The verifier
    # itself runs the real replay, reads the snapshot cardinality, compares all
    # registered literals, and derives its exit status from those comparisons.
    python3 "$REPO_ROOT/pipeline/replay_pins.py" rewrite --repo-root "$REPO_ROOT"
    python3 "$REPO_ROOT/pipeline/replay_pins.py" verify --repo-root "$REPO_ROOT"

    # Report every L1 source so consumer-sync drift remains a visible health
    # signal, but gate this write only on homelab-canon: it is the sole source
    # derived from the catalog row this loop just wrote. Sibling shortfalls are
    # ongoing backlog, tracked separately rather than allowed to roll back a
    # correct canonical write (hindsight#101).
    #
    # CI (guard.yml) scopes its own reconciliation to homelab-canon because it
    # checks out only this repository. CI does NOT verify fleet-main,
    # fleet-orch, claude-codex-integration, or fleet-dispatch-schema; this
    # write-time full report makes their current health visible but does not
    # claim that the canonical-write gate resolves their consumer-sync backlog.
    python3 "$REPO_ROOT/pipeline/reconcile_l1.py" --gate homelab-canon

    # Keep the curated pointer files in sync with criticality.jsonl on every
    # canonical write -- a second manual step here is exactly how POINTER.md/
    # HIGH.md would silently drift out of date. Deterministic and idempotent,
    # so re-running it is always safe.
    python3 "$REPO_ROOT/bin/synthesize-pointer.py"
else
    python3 "$REPO_ROOT/guard/failure_mode_catalog_guard.py" "$CATALOG" >/dev/null
fi

JOURNAL_READY=0
trap - EXIT

# ── Report ────────────────────────────────────────────────────────────────────

echo "add-failure-mode: ${FM_ID} appended to ${CATALOG}"
echo "  class: ${BUG_CLASS}"
[[ -n "$TIER" ]]   && echo "  tier: ${TIER} (recorded in ${CRITICALITY})"
[[ -n "$ISSUE" ]]  && echo "  issue: #${ISSUE}"
echo "  recurrence_of: ${RECURRENCE_OF}"
if [[ "$EFFECTIVE_DISPOSITION" != "$DISPOSITION" ]]; then
    echo "  disposition: ${EFFECTIVE_DISPOSITION} (force-promoted from ${DISPOSITION} by --recurrence-of ${RECURRENCE_OF})"
else
    echo "  disposition: ${EFFECTIVE_DISPOSITION}"
fi
echo "  table:  ${TABLE_ROW}"
