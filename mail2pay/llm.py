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
