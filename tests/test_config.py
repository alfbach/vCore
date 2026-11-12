from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_local_credentials():
    settings = Settings(_env_file=None)
    assert settings.api_username == "admin"
    assert settings.api_password == "changeme"


def test_multiple_workers_are_rejected_for_process_local_state():
    with pytest.raises(ValidationError, match="must be 1"):
        Settings(workers=2, _env_file=None)


def test_weak_password_is_rejected_on_network_bind():
    with pytest.raises(ValidationError, match="at least 12 characters"):
        Settings(host="0.0.0.0", api_password="password", _env_file=None)


def test_weak_password_is_allowed_for_loopback_development():
    settings = Settings(host="127.0.0.1", api_password="password", _env_file=None)
    assert settings.api_password == "password"


def test_weak_password_requires_explicit_opt_in_on_network_bind():
    settings = Settings(
        host="0.0.0.0",
        api_password="password",
        allow_weak_password=True,
        _env_file=None,
    )
    assert settings.api_password == "password"


@pytest.mark.parametrize(
    "field",
    [
        "max_upload_mb",
        "max_stored_uploads",
        "max_xlsx_uncompressed_mb",
        "max_xlsx_rows",
        "max_xlsx_cells",
        "session_ttl_seconds",
    ],
)
def test_resource_limits_must_be_positive(field):
    with pytest.raises(ValidationError, match="must be positive"):
        Settings(**{field: 0}, _env_file=None)
