# Embedding snapshot schema

`embedding-snapshot.json` freezes the dense vectors used by L2 clustering so
offline replay does not contact the HTTP embedding service. Its top-level JSON
object has exactly these logical fields:

```json
{
  "schema": "hindsight.embedding-snapshot/v2",
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
authorized host allowlist, requests one vector per sorted L1 ID, validates the
complete response, writes and fsyncs a unique same-directory temporary file,
then atomically replaces the destination. Any backend, protocol, coverage,
vector, or pre-replacement write error exits nonzero and preserves the prior
snapshot. Ordinary CI must never invoke this command.

Example release invocation:

```bash
python3 pipeline/capture_embedding_snapshot.py \
  --model BAAI/bge-m3 --revision bge-m3-Q8_0.gguf --dimensions 1024
```

The vectors in the committed v2 snapshot are retained unchanged from the v1
snapshot captured from the authorized HTTP service. The current L1 and cluster
code/config provenance was added deterministically; this packet did **not**
perform or claim a live backend recapture. CI wiring and canonical L2 comparison
belong to later issue #30 packets.
