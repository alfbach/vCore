from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from app.config import Settings

PASSWORD_OVERRIDE_FILENAME = ".api-password"


def password_override_path(settings: Settings) -> Path:
    return Path(settings.upload_dir).resolve() / PASSWORD_OVERRIDE_FILENAME


def load_password_override(settings: Settings) -> bool:
    path = password_override_path(settings)
    if not path.is_file():
        return False
    password = path.read_text(encoding="utf-8").strip()
    if not password:
        return False
    settings.validate_api_password(password)
    settings.api_password = password
    return True


def save_password_override(settings: Settings, password: str) -> Path:
    settings.validate_api_password(password)
    path = password_override_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(password)
            handle.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path
