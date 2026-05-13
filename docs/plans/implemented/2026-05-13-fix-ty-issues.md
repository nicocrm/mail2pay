# Fix existing `ty check` issues

## Goal

Make `uv run ty check .` pass cleanly so the new pre-commit hook doesn't block
commits. 9 diagnostics across 3 files.

## Current diagnostics

1. `handler.py` 44, 79, 82, 85 — `_cfg`/`_extractor` typed as `None` because
   module globals are initialised to `None`; ty can't narrow after `_bootstrap()`.
2. `mail2pay/config.py:19` — `Config()` flagged missing required args.
   Existing `# type: ignore[call-arg]` is mypy syntax; ty ignores it.
3. `tests/conftest.py:36` — `extractor._mock_client = client` sets an
   undeclared attribute on `Extractor`.
4. `tests/test_config.py` 14, 31, 41 — same `Config()` call-arg issue as (2).

## Proposed changes

### handler.py
Replace module-level `None` globals with a typed accessor that returns
non-optional values. Two options:

- **(preferred)** Use a small dataclass/container populated by `_bootstrap()`
  and return it: `def _bootstrap() -> tuple[Config, Extractor]`, then in
  `handle()` do `cfg, extractor = _bootstrap()`. Cache on function attribute
  or keep module globals but read via the returned tuple inside `handle`.
- Alternative: add `assert _cfg is not None` / `assert _extractor is not None`
  after the bootstrap call — cheapest fix, preserves structure.

Going with the assert approach for minimal diff:
- After `_bootstrap()` in `handle()`, add
  `assert _cfg is not None and _extractor is not None`.

### mail2pay/config.py
- Replace `# type: ignore[call-arg]` with `# ty: ignore[missing-argument]`
  (ty's ignore syntax). Values come from env, so call is safe.

### tests/test_config.py
- Same change: swap the three `# type: ignore[call-arg]` comments for
  `# ty: ignore[missing-argument]`.

### tests/conftest.py
- Either:
  - (a) declare `_mock_client: MagicMock | None = None` as a class attribute
    on `Extractor` (leaks test concern into prod code — bad), OR
  - (b) stop stashing the mock on the extractor; return `(extractor, client)`
    from the fixture as a tuple/namedtuple, OR
  - (c) keep setting it but add `# ty: ignore[unresolved-attribute]`.

  Going with **(b)**: change fixture to return a small object
  (e.g. `types.SimpleNamespace(extractor=..., client=...)`) or a tuple.
  Update any test that reads `mock_extractor._mock_client` accordingly.

## Verification

- `uv run ty check .` → 0 diagnostics
- `uv run pytest` still passes

## Open questions

- OK with the `assert` pattern in `handler.py`, or prefer refactoring
  `_bootstrap()` to return the objects?
- For the `mock_extractor` fixture, prefer tuple return or SimpleNamespace?
  (Need to grep tests for `_mock_client` usage before changing.)
