from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_multiple_workers_are_rejected_for_process_local_state():
    with pytest.raises(ValidationError, match="must be 1"):
        Settings(workers=2, _env_file=None)


def test_weak_password_is_rejected_on_network_bind():
    with pytest.raises(ValidationError, match="at least 12 characters"):
        Settings(host="0.0.0.0", api_password="password", _env_file=None)


def test_weak_password_is_allowed_for_loopback_development():
    settings = Settings(host="127.0.0.1", api_password="password", _env_file=None)
    assert settings.api_password == "password"
