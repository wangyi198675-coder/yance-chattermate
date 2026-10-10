# GRAPHITI_UPSTREAM_FIX_FRESHNESS_RESULT

## Verdict

`GRAPHITI_0_30_2 = HOLD_OWNER_PRODUCTION_QUALIFICATION`

No Graphiti wiring was performed.

## Freshness check 2026-10-05

- latest stable release: `v0.30.2`, published 2026-09-08
- current upstream main: `b7fc30f2a1e288266760640164a37bdb7d1d0f28` (2026-10-04 UTC)
- issue `getzep/graphiti#1893`: OPEN
- PR `#1894`: OPEN
- PR `#1895`: OPEN

At current main:

- `pyproject.toml` still declares `openai>=1.91.0` and does not declare `httpx`.
- `graphiti_core/llm_client/client.py` still executes top-level `import httpx` and references `httpx.HTTPStatusError`.

This matches the Phase 3B clean-install reproduction where `openai` 3.x installed `httpx2` but `graphiti_core` failed at import with `ModuleNotFoundError: No module named 'httpx'`.

There is no released fix and no merged upstream fix to consume.

Forbidden workarounds remain forbidden:

- `pip install httpx` as a private qualification fix
- private wheel
- monkey patch
- import rewrite
- Wave C wiring

Fresh public evidence:

- https://github.com/getzep/graphiti/issues/1893
- https://github.com/getzep/graphiti/pull/1894
- https://github.com/getzep/graphiti/pull/1895
- https://github.com/getzep/graphiti/releases
