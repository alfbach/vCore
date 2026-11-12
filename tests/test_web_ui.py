from __future__ import annotations

from app.web.i18n import get_translations, normalize_locale


def test_default_locale_is_english():
    t = get_translations("en")
    assert t["upload_button"] == "Load inventory"
    assert t["subtitle"].startswith("Upload an RVtools")


def test_german_translations():
    t = get_translations("de")
    assert t["upload_button"] == "Inventar laden"
    assert "hochladen" in t["subtitle"]


def test_normalize_locale_fallback():
    assert normalize_locale(None) == "en"
    assert normalize_locale("de") == "de"
    assert normalize_locale("fr") == "en"
    assert normalize_locale("DE") == "de"


def test_language_route_sets_cookie():
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/language/de", follow_redirects=False)
    assert response.status_code == 303
    assert response.cookies.get("vcenteremu_lang") == "de"

    page = client.get("/", cookies={"vcenteremu_lang": "de"})
    assert page.status_code == 200
    assert "Administrator-Zugang" in page.text


def test_static_logo_available():
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    for asset in ("vcore-icon.png", "vcore-lockup.png", "vcore-title.png"):
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/")

    tokens = client.get("/static/alfslab-tokens.css")
    assert tokens.status_code == 200
    assert "--alfslab-brand: #c9190b" in tokens.text


def test_dashboard_does_not_expose_api_password():
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    page = TestClient(create_app()).get("/")
    assert page.status_code == 200
    assert f"<code>{get_settings().api_password}</code>" not in page.text
    assert f":{get_settings().api_password}&quot;" not in page.text
    assert "&lt;password&gt;" in page.text
    assert 'action="/change-password"' not in page.text


def test_authenticated_dashboard_reveals_password_and_session_token():
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    settings = get_settings()
    client = TestClient(create_app())
    login = client.post(
        "/login",
        data={"username": settings.api_username, "password": settings.api_password},
        follow_redirects=False,
    )
    token = login.cookies.get("vcenteremu_session")
    assert token

    page = client.get("/")
    assert page.status_code == 200
    assert f"<code>{settings.api_password}</code>" in page.text
    assert f"<code>{token}</code>" in page.text
    assert 'action="/change-password"' in page.text
    assert 'name="current_password"' in page.text
    assert 'name="new_password"' in page.text
    assert 'name="confirm_password"' in page.text


def test_upload_requires_login():
    from fastapi.testclient import TestClient

    from app.main import create_app

    response = TestClient(create_app()).post(
        "/upload", files={"file": ("inventory.xlsx", b"not a workbook")}
    )
    assert response.status_code == 401


def test_change_password_requires_login():
    from fastapi.testclient import TestClient

    from app.main import create_app

    response = TestClient(create_app()).post(
        "/change-password",
        data={
            "current_password": "old",
            "new_password": "new-password-123",
            "confirm_password": "new-password-123",
        },
    )
    assert response.status_code == 401


def test_change_password_persists_and_invalidates_sessions(tmp_path):
    from fastapi.testclient import TestClient

    from app.auth.password_store import PASSWORD_OVERRIDE_FILENAME, load_password_override
    from app.auth.session_manager import session_manager
    from app.config import get_settings
    from app.main import create_app

    import asyncio

    settings = get_settings()
    original_upload_dir = settings.upload_dir
    original_password = settings.api_password
    settings.upload_dir = str(tmp_path)
    try:
        client = TestClient(create_app())
        login = client.post(
            "/login",
            data={"username": settings.api_username, "password": original_password},
            follow_redirects=False,
        )
        assert login.status_code == 303

        mismatch = client.post(
            "/change-password",
            data={
                "current_password": original_password,
                "new_password": "new-password-123",
                "confirm_password": "different-password",
            },
        )
        assert mismatch.status_code == 400

        changed = client.post(
            "/change-password",
            data={
                "current_password": original_password,
                "new_password": "new-password-123",
                "confirm_password": "new-password-123",
            },
            follow_redirects=False,
        )
        assert changed.status_code == 303
        assert changed.headers["location"] == "/?password_changed=1"
        override = tmp_path / PASSWORD_OVERRIDE_FILENAME
        assert override.read_text(encoding="utf-8").strip() == "new-password-123"
        assert override.stat().st_mode & 0o777 == 0o600

        settings.api_password = original_password
        assert load_password_override(settings) is True
        assert settings.api_password == "new-password-123"

        assert client.get("/").status_code == 200
        old_login = client.post(
            "/login",
            data={"username": settings.api_username, "password": original_password},
            follow_redirects=False,
        )
        assert old_login.status_code == 401
        new_login = client.post(
            "/login",
            data={"username": settings.api_username, "password": "new-password-123"},
            follow_redirects=False,
        )
        assert new_login.status_code == 303
    finally:
        settings.upload_dir = original_upload_dir
        settings.api_password = original_password
        asyncio.run(session_manager.clear())


def test_login_upload_sanitizes_filename_and_logout(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app
    from tests.test_rvtools_parser import _build_sample_workbook

    settings = get_settings()
    original_upload_dir = settings.upload_dir
    settings.upload_dir = str(tmp_path)
    try:
        client = TestClient(create_app())
        login = client.post(
            "/login",
            data={
                "username": settings.api_username,
                "password": settings.api_password,
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert login.cookies.get("vcenteremu_session")

        upload = client.post(
            "/upload",
            files={"file": ("../../escape.xlsx", _build_sample_workbook())},
        )
        assert upload.status_code == 200
        saved = list(tmp_path.iterdir())
        assert len(saved) == 1
        assert saved[0].parent == tmp_path
        assert ".." not in saved[0].name

        logout = client.post("/logout", follow_redirects=False)
        assert logout.status_code == 303
        denied = client.post(
            "/upload",
            files={"file": ("inventory.xlsx", _build_sample_workbook())},
        )
        assert denied.status_code == 401
    finally:
        settings.upload_dir = original_upload_dir


def test_upload_size_limit_and_retention(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app
    from tests.test_rvtools_parser import _build_sample_workbook

    settings = get_settings()
    original_upload_dir = settings.upload_dir
    original_max_upload_mb = settings.max_upload_mb
    original_max_stored_uploads = settings.max_stored_uploads
    settings.upload_dir = str(tmp_path)
    settings.max_upload_mb = 1
    settings.max_stored_uploads = 1
    try:
        client = TestClient(create_app())
        login = client.post(
            "/login",
            data={"username": settings.api_username, "password": settings.api_password},
            follow_redirects=False,
        )
        assert login.status_code == 303

        too_large = client.post(
            "/upload",
            files={"file": ("large.xlsx", b"x" * (1024 * 1024 + 1))},
        )
        assert too_large.status_code == 413
        assert not list(tmp_path.iterdir())

        workbook = _build_sample_workbook()
        assert client.post("/upload", files={"file": ("first.xlsx", workbook)}).status_code == 200
        assert client.post("/upload", files={"file": ("second.xlsx", workbook)}).status_code == 200
        saved = list(tmp_path.glob("*.xlsx"))
        assert len(saved) == 1
        assert saved[0].name.endswith("-second.xlsx")
    finally:
        settings.upload_dir = original_upload_dir
        settings.max_upload_mb = original_max_upload_mb
        settings.max_stored_uploads = original_max_stored_uploads
