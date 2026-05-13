# OpenRouter LLM Backend Implementation Plan

> **REQUIRED SUB-SKILL:** Use the executing-plans skill to implement this plan task-by-task.

**Goal:** Replace the direct OpenAI backend in `Extractor` with OpenRouter, switching the API call from the Responses API (`client.responses.parse`) to the Chat Completions API (`client.chat.completions.parse`), and change the default model.

**Architecture:** OpenRouter exposes an OpenAI-compatible Chat Completions endpoint at `https://openrouter.ai/api/v1`. The `openai` Python SDK can target it by passing `base_url` and `api_key` to the `OpenAI` constructor. Structured outputs use `client.chat.completions.parse(..., response_format=PaymentDetails)` — same Pydantic model, different method chain. `client.chat.completions.parse` (non-beta) is confirmed available on the installed `openai==2.36.0`. No other modules change.

**Tech Stack:** `openai` SDK (already installed), OpenRouter API, `pydantic-settings`, `pytest`

---

### Task 1: Update `Config` – swap OpenAI key for OpenRouter key and base URL

**Files:**
- Modify: `mail2pay/config.py`
- Modify: `tests/conftest.py`
- Modify: `.env.example`

**Step 1: Write the failing test**

In `tests/test_config.py`, add at the bottom:

```python
def test_config_openrouter_fields(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "r")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("COMPANY_NAME", "C")
    monkeypatch.setenv("FROM_ADDRESS", "f@f.com")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "wh")

    cfg = Config()  # type: ignore[call-arg]
    assert cfg.openrouter_api_key == "or-key"
    assert cfg.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert cfg.openrouter_model == "mistralai/mistral-small-2603"


def test_config_no_longer_has_openai_api_key():
    assert "openai_api_key" not in Config.model_fields
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_config.py::test_config_openrouter_fields -v
```
Expected: `FAIL` – `Config` has no `openrouter_api_key` field.

**Step 3: Update `mail2pay/config.py`**

Replace `openai_api_key` with `openrouter_api_key` and add `openrouter_base_url`. Change the default model to an OpenRouter model (e.g. `anthropic/claude-sonnet-4-5`):

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    resend_api_key: str = Field(alias="RESEND_API_KEY")
    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    company_name: str = Field(alias="COMPANY_NAME")
    from_address: str = Field(alias="FROM_ADDRESS")
    webhook_secret: str = Field(alias="RESEND_WEBHOOK_SECRET")
    openrouter_model: str = Field(default="mistralai/mistral-small-2603", alias="OPENROUTER_MODEL")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )


def get_config() -> Config:
    return Config()  # type: ignore[call-arg]
```

**Step 4: Update `tests/conftest.py`** – replace `OPENAI_API_KEY` with `OPENROUTER_API_KEY` in `_make_cfg` defaults, and update the `real_extractor` fixture to read `OPENROUTER_API_KEY` from env:

```python
def _make_cfg(**overrides) -> Config:
    defaults = dict(
        RESEND_API_KEY="test-resend-key",
        OPENROUTER_API_KEY="test-openrouter-key",
        COMPANY_NAME="Test Corp",
        FROM_ADDRESS="noreply@example.com",
        RESEND_WEBHOOK_SECRET="test-webhook-secret",
        OPENROUTER_MODEL="mistralai/mistral-small-2603",
    )
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[call-arg]


@pytest.fixture
def real_extractor(cfg):
    """Extractor with a real OpenRouter client – skipped when key absent."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set – skipping live LLM test")
    real_cfg = _make_cfg(OPENROUTER_API_KEY=api_key)
    return Extractor(real_cfg)
```

**Step 5: Update `.env.example`** – remove the `OPENAI_API_KEY` line and add the three OpenRouter entries. Leave `RESEND_API_KEY` and `RESEND_WEBHOOK_SECRET` entries untouched:

```
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=mistralai/mistral-small-2603
```

**Step 6: Run tests to verify config tests pass**

```bash
uv run pytest tests/test_config.py -v
```
Expected: all config tests pass.

**Step 7: Commit**

```bash
git add mail2pay/config.py tests/conftest.py tests/test_config.py .env.example
git commit -m "feat: replace OpenAI key with OpenRouter key+base_url in Config"
```

---

### Task 2: Update `Extractor` – switch to Chat Completions API and OpenRouter client

**Files:**
- Modify: `mail2pay/llm.py`
- Modify: `tests/test_llm.py`

**Step 1: Write the failing tests**

In `tests/test_llm.py`, replace the three mock-based tests entirely (they reference `responses.parse` which will be gone):

```python
def test_mock_extractor_calls_chat_completions_parse(mock_extractor):
    """Verify the correct API call shape."""
    expected = PaymentDetails(amount="50.00", iban="BE68539007547034", communication="INV-001")
    mock_extractor._mock_client.chat.completions.parse.return_value.choices[0].message.parsed = expected

    result = mock_extractor.extract("some invoice text")

    call_kwargs = mock_extractor._mock_client.chat.completions.parse.call_args
    assert call_kwargs.kwargs.get("response_format") is PaymentDetails
    assert result is expected


def test_mock_extractor_passes_correct_roles(mock_extractor):
    mock_extractor._mock_client.chat.completions.parse.return_value.choices[0].message.parsed = PaymentDetails(
        amount="10.00", iban="BE68539007547034", communication="ref"
    )
    mock_extractor.extract("invoice text here")

    call_kwargs = mock_extractor._mock_client.chat.completions.parse.call_args
    messages = call_kwargs.kwargs.get("messages")
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user"]
    assert "invoice text here" in messages[1]["content"]


def test_mock_extractor_uses_configured_model(mock_extractor, cfg):
    mock_extractor._mock_client.chat.completions.parse.return_value.choices[0].message.parsed = PaymentDetails(
        amount="1.00", iban="BE68539007547034", communication="x"
    )
    mock_extractor.extract("t")

    call_kwargs = mock_extractor._mock_client.chat.completions.parse.call_args
    assert call_kwargs.kwargs.get("model") == cfg.openrouter_model


def test_mock_extractor_truncates_long_text(mock_extractor):
    mock_extractor._mock_client.chat.completions.parse.return_value.choices[0].message.parsed = PaymentDetails(
        amount="1.00", iban="BE68539007547034", communication="x"
    )
    mock_extractor.extract("A" * 20_000)

    messages = mock_extractor._mock_client.chat.completions.parse.call_args.kwargs["messages"]
    assert messages[1]["content"].count("A") == 10_000


def test_mock_extractor_raises_on_none_parsed(mock_extractor):
    mock_extractor._mock_client.chat.completions.parse.return_value.choices[0].message.parsed = None
    with pytest.raises(ValueError):
        mock_extractor.extract("t")
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_llm.py -v
```
Expected: `FAIL` – mock is set up on wrong chain (`responses.parse` still in llm.py).

**Step 3: Update `mail2pay/llm.py`**

```python
import logging
from typing import Optional

from openai import OpenAI

from .config import Config
from .models import PaymentDetails

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 10_000


class Extractor:
    def __init__(self, cfg: Config, client: Optional[OpenAI] = None):
        self._model = cfg.openrouter_model
        self._client = client or OpenAI(
            api_key=cfg.openrouter_api_key,
            base_url=cfg.openrouter_base_url,
        )

    def extract(self, raw_text: str) -> PaymentDetails:
        if len(raw_text) > _MAX_TEXT_CHARS:
            logger.warning(
                "Invoice text truncated from %d to %d chars before LLM call.",
                len(raw_text),
                _MAX_TEXT_CHARS,
            )
            raw_text = raw_text[:_MAX_TEXT_CHARS]

        response = self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": "Precise invoice data extractor."},
                {
                    "role": "user",
                    "content": (
                        "Extract amount, Belgian IBAN, and communication.\n\n"
                        f"Invoice:\n{raw_text}"
                    ),
                },
            ],
            response_format=PaymentDetails,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError(
                "LLM returned no structured output (refusal or content filter)"
            )
        return parsed
```

**Step 4: Run all tests**

```bash
uv run pytest -v
```
Expected: 15 passed, 1 skipped. No failures.

**Step 5: Commit**

```bash
git add mail2pay/llm.py tests/test_llm.py
git commit -m "feat: switch Extractor to OpenRouter via chat.completions.parse"
```

---

### Task 3: Update `handler.py` env var references in test

`handler.py` itself does not reference `OPENAI_API_KEY` directly (it flows through `Config`), but `tests/test_handler.py` sets `OPENAI_API_KEY` in the env dict inside `_run_handler`. Update it.

**Files:**
- Modify: `tests/test_handler.py`

**Step 1: Run handler tests to confirm they still pass** (they should, since `handler.py` is unchanged):

```bash
uv run pytest tests/test_handler.py -v
```
Expected: all pass (handler tests monkeypatch env vars; `OPENAI_API_KEY` is ignored by the updated Config so it's harmless, but tidy it up).

**Step 2: Update `_run_handler` in `tests/test_handler.py`** – replace `OPENAI_API_KEY` with `OPENROUTER_API_KEY` in `base_env`, and update the live-key detection:

```python
def _run_handler(monkeypatch, payment: PaymentDetails, env: dict | None = None):
    env = env or {}
    base_env = {
        "RESEND_API_KEY": "test-resend",
        "OPENROUTER_API_KEY": "test-openrouter",
        "RESEND_WEBHOOK_SECRET": "test-webhook-secret",
        "COMPANY_NAME": "Test Corp",
        "FROM_ADDRESS": "noreply@test.com",
    }
    for k, v in {**base_env, **env}.items():
        monkeypatch.setenv(k, v)

    import os
    live_key = os.environ.get("OPENROUTER_API_KEY")
    use_live = live_key and not live_key.startswith("test-")

    if not use_live:
        import mail2pay.llm as llm_mod
        monkeypatch.setattr(llm_mod, "Extractor", _stub_extractor_class(payment))

    resend_mock = MagicMock()
    with patch("resend.Emails.send", resend_mock):
        import handler
        result = handler.handle(_make_event(_make_pdf_b64()), context=None)

    return result, resend_mock
```

**Step 3: Run full suite**

```bash
uv run pytest -v
```
Expected: 15 passed, 1 skipped.

**Step 4: Commit**

```bash
git add tests/test_handler.py
git commit -m "chore: update test_handler to use OPENROUTER_API_KEY"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md`

**Step 1:** In the env vars table, replace the `OPENAI_API_KEY` row with:

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API key (get one at openrouter.ai) |
| `OPENROUTER_BASE_URL` | ✗ | Override base URL (default: `https://openrouter.ai/api/v1`) |
| `OPENROUTER_MODEL` | ✗ | Model slug (default: `mistralai/mistral-small-2603`) |

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README for OpenRouter"
```
