from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBasicCredentials

from app.auth.session_manager import (
    security,
    session_manager,
    verify_basic_credentials,
)
from app.config import Settings, get_settings

router = APIRouter(tags=["session"])


@router.post("/com/vmware/cis/session")
async def create_session(
    credentials: HTTPBasicCredentials | None = Depends(security),
    settings: Settings = Depends(get_settings),
) -> str:
    username = verify_basic_credentials(credentials, settings)
    session = await session_manager.create(username, settings.session_ttl_seconds)
    return session.token


@router.delete("/com/vmware/cis/session")
async def delete_session(
    request: Request,
) -> None:
    token = request.headers.get("vmware-api-session-id") or request.cookies.get(
        "vcenteremu_session"
    )
    if token:
        await session_manager.delete(token)
