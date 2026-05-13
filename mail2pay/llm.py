from typing import Optional

from openai import OpenAI

from .config import Config
from .models import PaymentDetails

import logging

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 10_000


class Extractor:
    def __init__(self, cfg: Config, client: Optional[OpenAI] = None):
        self._model = cfg.openai_model
        self._client = client or OpenAI(api_key=cfg.openai_api_key)

    def extract(self, raw_text: str) -> PaymentDetails:
        if len(raw_text) > _MAX_TEXT_CHARS:
            logger.warning(
                "Invoice text truncated from %d to %d chars before LLM call.",
                len(raw_text),
                _MAX_TEXT_CHARS,
            )
            raw_text = raw_text[:_MAX_TEXT_CHARS]
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": "Precise invoice data extractor."},
                {
                    "role": "user",
                    "content": (
                        "Extract amount, Belgian IBAN, and communication.\n\n"
                        f"Invoice:\n{raw_text}"
                    ),
                },
            ],
            text_format=PaymentDetails,
        )
        result = response.output_parsed
        if result is None:
            raise ValueError(
                "LLM returned no structured output (refusal or content filter)"
            )
        return result
