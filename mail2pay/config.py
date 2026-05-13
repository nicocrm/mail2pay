from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    resend_api_key: str = Field(alias="RESEND_API_KEY")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    company_name: str = Field(alias="COMPANY_NAME")
    from_address: str = Field(alias="FROM_ADDRESS")
    openai_model: str = Field(default="gpt-5.4-mini", alias="OPENAI_MODEL")
    webhook_secret: str = Field(alias="RESEND_WEBHOOK_SECRET")


def get_config() -> Config:
    return Config()  # ty: ignore[missing-argument]
