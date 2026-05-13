# Switch LLM backend from OpenRouter to Mistral AI

## Goal

Replace the OpenRouter-via-OpenAI-SDK integration with a direct Mistral AI
client using the official `mistralai` Python SDK. Structured output
(`PaymentDetails`) must continue to work.

## Env var changes

| Old | New |
|---|---|
| `OPENROUTER_API_KEY` | `MISTRAL_API_KEY` |
| `OPENROUTER_MODEL` | `LLM_MODEL` |
| `OPENROUTER_BASE_URL` | *dropped* |

Default model: `mistral-small-latest` (replacing
`mistralai/mistral-small-2603`).

## Proposed changes

### `pyproject.toml`
- Add `mistralai` dependency.
- Remove `openai` dependency (no longer used).

### `mail2pay/config.py`
- Rename `openrouter_api_key` → `mistral_api_key`
  (alias `MISTRAL_API_KEY`).
- Rename `openrouter_model` → `llm_model` (alias `LLM_MODEL`, default
  `mistral-small-latest`).
- Remove `openrouter_base_url` field and `HttpUrl` import if unused.

### `mail2pay/llm.py`
- Replace `from openai import OpenAI` with `from mistralai.client import Mistral`.
- `Extractor.__init__`: accept `Optional[Mistral]`, instantiate with
  `Mistral(api_key=cfg.mistral_api_key)`.
- Use `cfg.llm_model`.
- Structured-output call (same shape as current code):
  `self._client.chat.parse(model=..., messages=..., response_format=PaymentDetails, temperature=0)`.
- Response shape matches OpenAI closely:
  `response.choices[0].message.parsed` is the `PaymentDetails` instance
  (or `None` on refusal / non-string content). Keep the existing
  `parsed is None` guard as-is.

### `.env.example`
- Replace the three `OPENROUTER_*` lines with:
  - `MISTRAL_API_KEY=your-mistral-api-key`
  - `LLM_MODEL=mistral-small-latest` (optional)

### `README.md`
- Update env var table (lines ~18, 22, 23):
  - `MISTRAL_API_KEY` (required, "Mistral AI API key — console.mistral.ai")
  - `LLM_MODEL` (optional, default `mistral-small-latest`)
  - Drop the base-URL row.
- Update the `llm.py` comment on line 73 (`# OpenAI Extractor` →
  `# Mistral Extractor`).

### `tests/conftest.py`
- `_make_cfg` defaults: `MISTRAL_API_KEY="test-mistral-key"`,
  `LLM_MODEL="mistral-small-latest"`.
- `live_cfg` fixture: skip unless `MISTRAL_API_KEY` is set; pass it
  through to `_make_cfg`.
- Mock client fixture: update docstring / type to `Mistral`.

### `tests/test_config.py`
- Replace `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` env vars and
  attribute assertions with the new names.
- Drop the `openrouter_base_url` assertion.
- Update the required-var list in the "missing env" test.

### `tests/test_llm.py`
- Update mocked client to mimic `Mistral().chat.parse(...)`.
- Assert `call_kwargs.kwargs.get("model") == cfg.llm_model`.

### `tests/test_handler.py`
- Replace `OPENROUTER_API_KEY` with `MISTRAL_API_KEY` in all four
  env-patch dicts (lines ~74, 130, 145, 161) and the live-test skip
  check at line ~83.

## Verification

- `uv run ty check .` → 0 diagnostics.
- `uv run pytest` → all green (live Mistral test auto-skips without
  `MISTRAL_API_KEY`).
- Manual smoke test with a real `MISTRAL_API_KEY` if available.

## API reference (resolved)

Verified against installed `mistralai==2.4.5` and
https://docs.mistral.ai/studio-api/conversations/structured-output/custom:

- Import: `from mistralai.client import Mistral` (not top-level
  `mistralai`).
- Client: `Mistral(api_key=...)` — no base URL needed.
- Call: `client.chat.parse(model=..., messages=[...],
  response_format=PaymentDetails, temperature=0, max_tokens=...)`.
- Return: `ParsedChatCompletionResponse` where
  `response.choices[0].message.parsed` is the pydantic instance (or
  `None` if content was non-string / absent).
- Internally `parse` wraps `chat.complete` + JSON schema derived from
  the pydantic model, so message format (`role`/`content` dicts) is
  identical to today's OpenAI-SDK call.

## Open questions

*None — all resolved.*

- Hard cutover confirmed; existing `.env` files will need updating.
- `temperature=0` confirmed; pass explicitly in `client.chat.parse(...)`.
