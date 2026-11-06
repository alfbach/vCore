from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VCENTEREMU_", env_file=".env")

    host: str = "127.0.0.1"
    port: int = 8181
    workers: int = 1
    api_username: str = "administrator@vsphere.local"
    api_password: str = "Emulator123!"
    allow_weak_password: bool = False
    upload_dir: str = "/var/lib/vcenteremu/uploads"
    max_upload_mb: int = 256
    vcenter_name: str = "vcenteremu.local"
    vcenter_version: str = "8.0.3.00000"
    product_name: str = "VMware vCenter Server"
    session_ttl_seconds: int = 3600
    auto_load_xlsx: str = ""
    cors_origins: str = ""

    @field_validator("workers")
    @classmethod
    def single_worker_only(cls, value: int) -> int:
        if value != 1:
            raise ValueError(
                "VCENTEREMU_WORKERS must be 1 because sessions and simulated inventory state "
                "are process-local"
            )
        return value

    @model_validator(mode="after")
    def reject_weak_password_on_network_bind(self) -> "Settings":
        if self.allow_weak_password:
            return self
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        known_defaults = {"emulator123!", "password", "changeme"}
        if self.host not in loopback_hosts and (
            len(self.api_password) < 12 or self.api_password.lower() in known_defaults
        ):
            raise ValueError(
                "VCENTEREMU_API_PASSWORD must be at least 12 characters and non-default "
                "when VCENTEREMU_HOST is not loopback"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
