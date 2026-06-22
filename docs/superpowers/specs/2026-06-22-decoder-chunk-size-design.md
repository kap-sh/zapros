# Bounded-output decoders (`chunk_size`)

Date: 2026-06-22
Status: Approved design, pre-implementation

## Problem

`ContentDecoder.decode(data: bytes) -> bytes` returns the full decompressed
output of a fed chunk in one buffer. A small compressed network chunk can
expand enormously in a single `decode()` call (decompression bomb), so peak
memory is unbounded *before* `ByteChunker` ever slices the output. The existing
`ByteChunker` (see [_models.py](../../../src/zapros/_models.py) iter paths) only
bounds the size of yielded chunks; it cannot bound the peak produced inside
`decode()`.

## Goal

Bound **peak memory per `decode()` call** to a caller-supplied `chunk_size`, for
every supported codec. The decoder must never materialize more than ~`chunk_size`
bytes of decompressed output in one piece.

Out of scope: capping *total* decompressed size (bomb refusal by total ratio).
That is handled separately at the `Response.read` level and is not part of this
change.

## Key constraint that drives the interface

`decode(data) -> bytes` *cannot* bound peak: a single `bytes` return forces
concatenating all output of that input back into one buffer, which is unbounded
again. True bounding requires `decode` to **yield** pieces. Therefore the
protocol changes to return an iterator.

## Verified codec capabilities

All confirmed empirically (2026-06-22):

| codec | backend | bounding mechanism |
|---|---|---|
| gzip / deflate | `zlib` | `decompressobj().decompress(data, max_length)` + `unconsumed_tail` drain loop |
| br | `brotlicffi` (or google `brotli`) | `process(data, output_buffer_limit=chunk_size)` + `can_accept_more_data()` drain loop |
| zstd | `zstandard` | `ZstdDecompressor().stream_writer(sink, write_size=chunk_size)` — push model, sink receives pieces ≤ `write_size` |

Notes:
- `zstandard`'s `decompressobj()` does **not** bound (its `write_size` is an
  internal buffer; `decompress()` still returns everything). `stream_reader` is
  pull-based and treats a `b""` source read as EOF, so it cannot drive a push
  loop. `stream_writer` is the only `zstandard` primitive that bounds in a push
  model — verified with a 3071-byte → 100 MB bomb fed in one `write()`, emitting
  1526 sink writes each ≤ `write_size`.
- google `brotli` ≥1.1.0 also supports `output_buffer_limit`; the dependency is
  switched to `brotlicffi` ≥1.2.0 (which added the parameter) but the decoder
  keeps importing either.
- Python 3.14's builtin `compression.zstd` also bounds (`decompress(data,
  max_length)`), but is **not** used: `zstandard` `stream_writer` already bounds
  on all versions, so a single code path is preferred.

## Design

### 1. Protocol

```python
class ContentDecoder(Protocol):
    def decode(self, data: bytes) -> Iterator[bytes]: ...   # each piece <= chunk_size
    def flush(self) -> Iterator[bytes]: ...
```

Every concrete decoder takes `chunk_size: int` in `__init__`.

### 2. Concrete decoders (`src/zapros/_decoders.py`)

- **IdentityDecoder**: slice input into `chunk_size` pieces, yield.
- **GZipDecoder / DeflateDecoder**: loop
  `out = decompressobj.decompress(data, chunk_size)`; yield `out`;
  `data = decompressobj.unconsumed_tail`; stop when tail empty. Same `zlib.error
  → DecodingError` handling as today. DeflateDecoder keeps its raw-deflate retry.
- **BrotliDecoder**: loop `process(data, output_buffer_limit=chunk_size)`,
  draining via `can_accept_more_data()` with empty input between calls; yield
  each returned piece. Keep brotli-missing `ImportError` guard.
- **ZStandardDecoder**: hold an internal collector sink and
  `ZstdDecompressor().stream_writer(sink, write_size=chunk_size)`. `decode(data)`
  calls `writer.write(data)` then yields and clears the sink's collected pieces
  (each ≤ `chunk_size`). `flush()` flushes the writer and yields any trailing
  pieces. Keep zstandard-missing `ImportError` guard. Wrap `ZstdError →
  DecodingError`.

### 3. MultiDecoder

Rewrite as a lazy generator chain so stacked encodings (e.g. `gzip, br`) stay
bounded: feed each piece through the next decoder's `decode`/`flush` as a
generator pipeline rather than buffering an intermediate full list.

### 4. `_models.py` plumbing

- `_get_content_decoder()` gains a `chunk_size` parameter and passes it to each
  decoder constructed from `SUPPORTED_DECODERS[...]` and to `MultiDecoder`.
- The `iter_bytes` / `async_iter_bytes` decoded paths call
  `_get_content_decoder(chunk_size)` and consume the decoder's yielded pieces.
- `ByteChunker` stays **downstream** to coalesce the decoder's (≤ chunk_size)
  pieces into uniform `chunk_size` output for the user. Decoder bounds peak;
  chunker normalizes output size.

### 5. Packaging (`pyproject.toml`)

- `brotli` extra: `brotli>=1.0.0` → `brotlicffi>=1.2.0`.
- `zstd` extra: unchanged (`zstandard>=0.18.0`).

### 6. Sync regeneration

Async is source of truth. After editing async decoder/model code run
`./scripts/fix` to regenerate sync versions per `ry.yml`.

## Testing

- For each codec: feed a high-ratio compressed payload (bomb-ish) in one chunk
  and assert **no single yielded piece exceeds `chunk_size`** (gzip, deflate,
  br, zstd — all bounded now).
- For each codec: assert decoded output round-trips byte-identical to the
  original.
- Multi-feed incremental: feed compressed input in many small parts, assert
  round-trip identity and bound hold across feeds.
- MultiDecoder: stacked `gzip, br` round-trips and stays bounded.
- `flush()` emits trailing bytes correctly for each codec.
- Identity passthrough slices correctly and round-trips.

## Risks

- `stream_writer` finalization: ensure `flush()` emits all trailing output and
  the writer is finalized exactly once (no double-close). Covered by flush tests.
- brotli drain protocol: after hitting `output_buffer_limit`, only empty input
  is permitted until `can_accept_more_data()` returns True — drain loop must
  honor this or risk dropped/duplicated output. Covered by bound + round-trip
  tests.
