# kompress_zh Integration Notes

## Goal

Integrate `kompress_zh` into `headroom-zh` as an additional Chinese plain-text
compression lane while preserving upstream Headroom behavior.

## Strategy

- Keep upstream Kompress as the default ML compressor for English and mixed
  prose.
- Route Chinese-dominant plain text to `KompressZhCompressor`.
- Keep structured data, code, diffs, logs, search output, HTML, and tabular
  data on their existing upstream strategies.
- Fail closed to the original upstream path if the Chinese adapter is
  unavailable, disabled, or does not produce savings.

## Maintenance Rule

This branch should remain based on upstream `headroomlabs-ai/headroom:main`.
Future upstream updates should be merged or rebased into this branch, then the
small `headroom-zh` plugin surface should be revalidated.
