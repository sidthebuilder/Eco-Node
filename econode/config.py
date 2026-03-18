"""
econode – Configuration
Single source of truth for all runtime settings via pydantic-settings.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ElectricityMaps
    electricity_maps_key: Optional[str] = Field(default=None)
    electricity_maps_base_url: str = "https://api.electricitymap.org/v3"

    # AWS
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_default_region: str = "us-east-1"

    # GCP
    google_application_credentials: Optional[str] = None

    # Azure
    azure_subscription_id: Optional[str] = None
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None

    # econode engine
    econode_poll_interval: int = 300          # seconds
    econode_migration_threshold: float = 0.15 # 15% improvement triggers migration
    econode_retrain_hours: int = 6
    econode_history_limit: int = 2016         # ~1 week of 5-min intervals
    econode_log_level: str = "INFO"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def has_electricity_maps(self) -> bool:
        return bool(self.electricity_maps_key)

    @property
    def has_aws(self) -> bool:
        return bool(self.aws_access_key_id and self.aws_secret_access_key)

    @property
    def has_gcp(self) -> bool:
        return bool(self.google_application_credentials)

    @property
    def has_azure(self) -> bool:
        return bool(self.azure_subscription_id and self.azure_tenant_id)

    @property
    def demo_mode(self) -> bool:
        """True when no real credentials are configured."""
        return not (self.has_electricity_maps or self.has_aws or self.has_gcp or self.has_azure)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
