from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    resend_api_key: str = Field(alias="RESEND_API_KEY")
    mistral_api_key: str = Field(alias="MISTRAL_API_KEY")
    from_address: str = Field(alias="FROM_ADDRESS")
    webhook_secret: str = Field(alias="RESEND_WEBHOOK_SECRET")
    llm_model: str = Field(default="mistral-small-latest", alias="LLM_MODEL")


def get_config() -> Config:
    return Config()  # ty: ignore[missing-argument]
