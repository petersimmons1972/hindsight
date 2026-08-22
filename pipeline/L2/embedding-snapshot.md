# Embedding snapshot schema

`embedding-snapshot.json` freezes the dense vectors used by L2 clustering so
offline replay does not contact the HTTP embedding service. Its top-level JSON
object has exactly these logical fields:

```json
{
  "schema": "hindsight.embedding-snapshot/v3",
  "provenance": {
    "l1_sha256": "64 lowercase hexadecimal characters",
    "cluster_sha256": "64 lowercase hexadecimal characters"
  },
  "backend": {
    "name": "http",
    "model": "BAAI/bge-m3",
    "revision": "bge-m3-Q8_0.gguf",
    "dimensions": 1024
  },
  "embeddings": {
    "L1-record-id": [0.1, -0.2]
  },
  "similarity_text_sha256": {
    "L1-record-id": "64 lowercase hexadecimal characters"
  }
}
```

- `schema` is the exact format identifier. Readers reject unknown versions.
- `provenance.l1_sha256` hashes every sorted `L1/*.jsonl` filename and its raw
  bytes using length-delimited frames. A filename, byte, added file, or removed
  file changes the digest.
- `provenance.cluster_sha256` hashes the raw `pipeline/cluster.py` bytes and a
  canonical JSON serialization of the clustering thresholds, linkage, dense
  weight, and degeneracy cap. Code or configuration drift changes the digest.
- `backend.name`, `backend.model`, and `backend.revision` are non-empty raw
  identities from the configured backend. `revision` identifies the served
  model artifact, not a mutable display alias.
- `backend.dimensions` is a positive integer and every vector must have exactly
  that many finite numeric elements.
- `embeddings` is keyed by the unique L1 `id`; keys are not row positions.
- `similarity_text_sha256` has the exact same ID keys and hashes the UTF-8
  `similarity_text(entry)` sent to the embedding backend. A vector is reusable
  only when this digest and the backend identity still match.

The top-level object, provenance object, and backend object are closed schemas:
missing or extra fields are rejected. Replay requires separately computed L1
and cluster code/config digests plus a separately declared backend identity,
and rejects the snapshot unless all declared values match exactly. It also
requires exact equality between the corpus ID set and snapshot key set. Missing
and unexpected IDs are both errors and are named; zero overlap is reported as
an alarm. Vectors are reordered by sorted L1 ID before being passed to
`cluster_entries`, matching the clustering core's stable entry order.

`pipeline/capture_embedding_snapshot.py` is the controlled release command. It
accepts only a parsed plain-HTTP origin whose hostname exactly matches the
authorized host allowlist and refuses redirects. By default it retains a prior
vector only when the v3 snapshot, backend identity, dimensions, ID, and exact
`similarity_text_sha256` all match; new IDs and stable IDs whose embedding text
changed are requested from the backend. `--refresh-embeddings` bypasses reuse
and requests every vector, even when the text and backend are unchanged.
Requests use the indexed OpenAI endpoint, falling back to the native per-text
endpoint only when the batch endpoint explicitly returns HTTP 404 or 405. It
binds OpenAI rows by their explicit indices, never by response order; malformed
responses and every other backend failure are final. Capture hashes L1 and
cluster/config inputs before the request and rechecks them immediately before
replacement. It writes and fsyncs a unique same-directory temporary file and,
when a prior snapshot exists, stages its recovery copy and fsyncs both that
file and its directory entry before atomically replacing the destination and
fsyncing the containing directory. Backend, protocol, coverage,
vector, provenance-drift, or pre-replacement write errors exit nonzero and
preserve the prior snapshot. If both atomic rollback methods fail, capture
removes the known-stale destination, retains the prior bytes in a named
`.recovery` file beside it, and fails loudly with that recovery path. Ordinary
CI must never invoke this command.

Example release invocation:

```bash
python3 pipeline/capture_embedding_snapshot.py \
  --model BAAI/bge-m3 --revision bge-m3-Q8_0.gguf --dimensions 1024
```

Add `--refresh-embeddings` only when the release deliberately needs current
live vectors for every entry. The committed v3 migration retained all 736 v2
vectors only after the v2 snapshot's full L1 digest, backend identity, and exact
ID coverage matched the current corpus; it added per-entry text digests and did
**not** perform or claim a live backend recapture.

Offline verification is read-only and never contacts HTTP:

```bash
python3 pipeline/replay_l2.py
```

The command validates snapshot provenance, backend identity, and exact L1/L2
metadata and member coverage before replaying at the calibrated HTTP threshold.
Committed L2 metadata is a closed, strictly typed schema: `backend` and
`linkage` are exact strings, `threshold` is numeric but never boolean, and
`entry_count` is an integer but never boolean; every value must also equal the
runtime expectation. Replay captures the cluster source bytes it executes and
checks L1 plus cluster code/config digests before and after parsing and
clustering, failing if either input drifts during the run.
It compares canonical partitions (sorted member IDs within sorted groups), so
cluster numbering and row order are irrelevant but membership changes fail
nonzero with deterministic group and member diagnostics. Snapshot capture and
later CI wiring remain separate responsibilities.
