# mail2pay – Agent Rules

## Verification

- Before considering any code change complete, run `uv run ty check .` and
  ensure it reports 0 diagnostics.
- Also run `uv run pytest` for changes that touch runtime or test code.
