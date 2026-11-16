# Vendored from fabraix/playground

- Source: https://github.com/fabraix/playground
- Commit: `40727601255422d9f77c83bcfaa8a2b6ab7a361e` (Fabraix Sync Bot, synced Nov 8 2026)
- License: MIT. The upstream `LICENSE` is kept at `fabraix_engine/LICENSE`.

`fabraix_engine/` is upstream `engine/` and `challenges/` is upstream `challenges/`, both copied
byte for byte. Nothing in this folder is edited. Where the bench needs different behavior, it
patches at runtime from `src/bench/` and says so in the top-level README:

- `TOOL_REGISTRY["search_web"]` is replaced with a local function that returns fixed or
  attacker-written results (`src/bench/poison.py`). Brave is never called.

The engine loads challenges from `fabraix_engine/challenges/library/`, which upstream keeps
identical to `challenges/`.
