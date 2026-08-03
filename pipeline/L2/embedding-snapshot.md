# Embedding snapshot schema

`embedding-snapshot.json` freezes the dense vectors used by L2 clustering so
offline replay does not contact the HTTP embedding service. Its top-level JSON
object has exactly these logical fields:

```json
{
  "schema": "hindsight.embedding-snapshot/v1",
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
- `backend.name`, `backend.model`, and `backend.revision` are non-empty raw
  identities from the configured backend. `revision` identifies the served
  model artifact, not a mutable display alias.
- `backend.dimensions` is a positive integer and every vector must have exactly
  that many finite numeric elements.
- `embeddings` is keyed by the unique L1 `id`; keys are not row positions.

Replay requires a separately declared backend identity and rejects the snapshot
unless all four identity fields match exactly. It also requires exact equality
between the corpus ID set and the snapshot key set. Missing and unexpected IDs
are both errors and are named; zero overlap is reported as an alarm. Vectors are
reordered by sorted L1 ID before being passed to `cluster_entries`, matching the
clustering core's stable entry order.

The committed snapshot was captured from the authorized HTTP service serving
`BAAI/bge-m3` from `bge-m3-Q8_0.gguf`. This packet defines and consumes the
format only. Snapshot capture automation, CI wiring, and canonical L2 comparison
belong to later issue #30 packets.
