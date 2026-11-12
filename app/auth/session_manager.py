from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import Settings, get_settings

security = HTTPBasic(auto_error=False)


@dataclass
class Session:
    token: str
    username: str
    created_at: float
    expires_at: float


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self, username: str, ttl_seconds: int) -> Session:
        token = secrets.token_hex(16)
        now = time.time()
        session = Session(
            token=token,
            username=username,
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        async with self._lock:
            self._purge_expired_locked(now)
            self._sessions[token] = session
        return session

    async def validate(self, token: str | None) -> Session | None:
        if not token:
            return None
        now = time.time()
        async with self._lock:
            self._purge_expired_locked(now)
            session = self._sessions.get(token)
            if session and session.expires_at > now:
                return session
            self._sessions.pop(token, None)
        return None

    async def delete(self, token: str) -> None:
        async with self._lock:
            self._sessions.pop(token, None)

    async def clear(self) -> None:
        async with self._lock:
            self._sessions.clear()

    def _purge_expired_locked(self, now: float) -> None:
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            del self._sessions[token]


session_manager = SessionManager()


def verify_basic_credentials(
    credentials: HTTPBasicCredentials | None,
    settings: Settings,
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic realm=\"vCore\""},
        )
    username_ok = secrets.compare_digest(credentials.username, settings.api_username)
    password_ok = secrets.compare_digest(credentials.password, settings.api_password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic realm=\"vCore\""},
        )
    return credentials.username


async def require_session(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Session:
    token = request.headers.get("vmware-api-session-id") or request.cookies.get(
        "vcenteremu_session"
    )
    session = await session_manager.validate(token)
    if session:
        return session
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )
