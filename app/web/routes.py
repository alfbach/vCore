from __future__ import annotations

import asyncio
import os
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.auth.session_manager import (
    Session,
    require_session,
    session_manager,
    verify_basic_credentials,
)
from app.auth.password_store import save_password_override
from app.config import get_settings
from app.parser.rvtools import parse_rvtools_xlsx
from app.store.inventory_store import inventory_store
from app.web.i18n import get_translations, normalize_locale

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
LANG_COOKIE = "vcenteremu_lang"
SESSION_COOKIE = "vcenteremu_session"
UPLOAD_CHUNK_SIZE = 1024 * 1024


def _public_base_url(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    scheme = forwarded_proto.split(",", 1)[0].strip() if forwarded_proto else request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def _locale_from_request(request: Request) -> str:
    query_lang = request.query_params.get("lang")
    if query_lang:
        return normalize_locale(query_lang)
    cookie_lang = request.cookies.get(LANG_COOKIE)
    if cookie_lang:
        return normalize_locale(cookie_lang)
    return normalize_locale(None)


def _template_context(request: Request, **extra: Any) -> dict[str, Any]:
    settings = get_settings()
    locale = _locale_from_request(request)
    base_url = _public_base_url(request)
    return {
        "request": request,
        "inventory": extra.pop("inventory", None),
        "settings": settings,
        "base_url": base_url,
        "api_base": f"{base_url}/rest",
        "locale": locale,
        "t": get_translations(locale),
        "authenticated": extra.pop("authenticated", False),
        **extra,
    }


async def _active_session_token(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    return token if await session_manager.validate(token) is not None else None


async def _write_upload_limited(file: UploadFile, target: Path, max_bytes: int) -> None:
    total = 0
    async with aiofiles.open(target, "xb") as handle:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="Upload exceeds the configured size limit",
                )
            await handle.write(chunk)


def _prune_stored_uploads(upload_dir: Path, keep: int) -> None:
    uploads = sorted(
        (
            path
            for path in upload_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".xlsx", ".xlsm"}
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for expired in uploads[keep:]:
        expired.unlink(missing_ok=True)


def _safe_upload_name(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return cleaned or "rvtools.xlsx"


@router.get("/language/{lang}")
async def set_language(lang: str, request: Request) -> RedirectResponse:
    locale = normalize_locale(lang)
    referer = request.headers.get("referer") or "/"
    path = urlparse(referer).path or "/"
    response = RedirectResponse(url=path, status_code=303)
    response.set_cookie(LANG_COOKIE, locale, max_age=365 * 24 * 3600, samesite="lax")
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    inventory = await inventory_store.get()
    session_token = await _active_session_token(request)
    context = _template_context(
        request,
        inventory=inventory,
        authenticated=session_token is not None,
        session_token=session_token,
        password_changed=request.query_params.get("password_changed") == "1",
    )
    return templates.TemplateResponse(request, "index.html", context)


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse:
    settings = get_settings()
    inventory = await inventory_store.get()
    try:
        verified_username = verify_basic_credentials(
            HTTPBasicCredentials(username=username, password=password), settings
        )
    except HTTPException:
        context = _template_context(
            request,
            inventory=inventory,
            login_error=True,
        )
        return templates.TemplateResponse(
            request, "index.html", context, status_code=401
        )

    session = await session_manager.create(
        verified_username, settings.session_ttl_seconds
    )
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session.token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=_public_base_url(request).startswith("https://"),
        samesite="lax",
    )
    return response


@router.post("/change-password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    _: Session = Depends(require_session),
) -> HTMLResponse:
    settings = get_settings()
    error: str | None = None
    if not secrets.compare_digest(current_password, settings.api_password):
        error = "current"
    elif new_password != confirm_password:
        error = "mismatch"
    else:
        try:
            settings.validate_api_password(new_password)
        except ValueError:
            error = "policy"

    if error:
        inventory = await inventory_store.get()
        context = _template_context(
            request,
            inventory=inventory,
            authenticated=True,
            session_token=request.cookies.get(SESSION_COOKIE),
            password_change_error=error,
        )
        return templates.TemplateResponse(
            request, "index.html", context, status_code=400
        )

    await asyncio.to_thread(save_password_override, settings, new_password)
    settings.api_password = new_password
    await session_manager.clear()
    response = RedirectResponse(url="/?password_changed=1", status_code=303)
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")
    return response


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await session_manager.delete(token)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")
    return response


@router.post("/upload", response_class=HTMLResponse)
async def upload_rvtools(
    request: Request,
    file: UploadFile = File(...),
    _: Session = Depends(require_session),
) -> HTMLResponse:
    settings = get_settings()
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx or .xlsm RVtools exports are supported")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    safe_name = _safe_upload_name(file.filename)
    upload_dir = Path(settings.upload_dir).resolve()
    await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
    upload_id = uuid4().hex
    temporary = upload_dir / f".{upload_id}.uploading"
    target = upload_dir / f"{upload_id}-{safe_name}"
    try:
        await _write_upload_limited(file, temporary, max_bytes)
        inventory = await asyncio.to_thread(
            parse_rvtools_xlsx,
            temporary,
            source_file=safe_name,
            max_uncompressed_bytes=settings.max_xlsx_uncompressed_mb * 1024 * 1024,
            max_rows=settings.max_xlsx_rows,
            max_cells=settings.max_xlsx_cells,
        )
        await asyncio.to_thread(os.replace, temporary, target)
        await asyncio.to_thread(target.chmod, 0o600)
        await asyncio.to_thread(
            _prune_stored_uploads,
            upload_dir,
            settings.max_stored_uploads,
        )
    except HTTPException:
        await asyncio.to_thread(temporary.unlink, missing_ok=True)
        raise
    except Exception as exc:
        await asyncio.to_thread(temporary.unlink, missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse RVtools file: {exc}") from exc
    finally:
        await file.close()

    await inventory_store.replace(inventory)

    context = _template_context(
        request,
        inventory=inventory,
        authenticated=True,
        session_token=request.cookies.get(SESSION_COOKIE),
        upload_success=True,
        uploaded_file=safe_name,
    )
    return templates.TemplateResponse(request, "index.html", context)


@router.get("/health")
async def health() -> dict:
    inventory = await inventory_store.get()
    return {
        "status": "ok",
        "inventory_loaded": inventory.is_loaded,
        "stats": inventory.stats,
    }
