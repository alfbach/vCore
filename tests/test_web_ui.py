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
    response = client.get("/static/logo.png")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_dashboard_does_not_expose_api_password():
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import create_app

    page = TestClient(create_app()).get("/")
    assert page.status_code == 200
    assert f"<code>{get_settings().api_password}</code>" not in page.text
    assert f":{get_settings().api_password}&quot;" not in page.text
    assert "&lt;password&gt;" in page.text


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


def test_upload_requires_login():
    from fastapi.testclient import TestClient

    from app.main import create_app

    response = TestClient(create_app()).post(
        "/upload", files={"file": ("inventory.xlsx", b"not a workbook")}
    )
    assert response.status_code == 401


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
