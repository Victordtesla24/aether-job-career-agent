"""Settings profile photo — POST/GET/DELETE /workspaces/settings/avatar.

Wireframe contract (design/screens/settings.html btn-avatar-st08): PNG or JPG,
max 2MB. Storage mirrors Resume.originalFile (bytea + sniffed content type +
bounded read). User.image holds the SHA-256 revision for cache-busting — never
a data URL or the raw bytes.

TDD: this file is written BEFORE the routes exist and is expected RED until
the implementation lands.
"""
from __future__ import annotations

import hashlib
import uuid

MAX_AVATAR_BYTES = 2 * 1024 * 1024

# Minimal bodies that pass magic-byte sniff (not full image decoders — stdlib
# sniff only, no Pillow).
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_GIF = b"GIF89a" + b"\x00" * 32
_PDF = b"%PDF-1.4 junk"
_SVG = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
_JUNK = b"not-an-image-at-all"


def _upload(client, headers, filename: str, content: bytes, mime: str):
    return client.post(
        "/workspaces/settings/avatar",
        files={"file": (filename, content, mime)},
        headers=headers,
    )


def _settings_payload(email: str) -> dict:
    return {
        "profile": {
            "fullName": "Avatar Tester",
            "email": email,
            "targetRole": "Software Engineer",
            "location": "Melbourne, AU",
        },
        "agentConfig": {
            "autoApply": False,
            "approvalGate": True,
            "matchThreshold": 80,
        },
    }


def test_avatar_endpoints_require_auth(client):
    assert _upload(client, {}, "a.png", _PNG, "image/png").status_code == 401
    assert client.get("/workspaces/settings/avatar").status_code == 401
    assert client.delete("/workspaces/settings/avatar").status_code == 401


def test_settings_reports_no_avatar_by_default(client, auth_headers):
    res = client.get("/workspaces/settings", headers=auth_headers)
    assert res.status_code == 200, res.text
    profile = res.json()["profile"]
    assert profile["hasAvatar"] is False
    assert profile["avatarRevision"] is None


def test_get_avatar_404_when_none_stored(client, auth_headers):
    res = client.get("/workspaces/settings/avatar", headers=auth_headers)
    assert res.status_code == 404, res.text
    detail = res.json().get("detail", "")
    assert "no profile photo" in detail.lower() or "not stored" in detail.lower()


def test_upload_png_persists_and_round_trips(client, auth_headers):
    up = _upload(client, auth_headers, "me.png", _PNG, "image/png")
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["profile"]["hasAvatar"] is True
    rev = body["profile"]["avatarRevision"]
    assert isinstance(rev, str) and len(rev) == 64
    assert rev == hashlib.sha256(_PNG).hexdigest()

    settings = client.get("/workspaces/settings", headers=auth_headers).json()
    assert settings["profile"]["hasAvatar"] is True
    assert settings["profile"]["avatarRevision"] == rev

    got = client.get("/workspaces/settings/avatar", headers=auth_headers)
    assert got.status_code == 200, got.text
    assert got.content == _PNG
    assert got.headers["content-type"].startswith("image/png")
    assert got.headers.get("x-content-type-options") == "nosniff"
    assert "private" in (got.headers.get("cache-control") or "").lower()
    assert got.headers.get("etag", "").strip('"') == rev


def test_upload_jpeg_persists(client, auth_headers):
    up = _upload(client, auth_headers, "me.jpg", _JPEG, "image/jpeg")
    assert up.status_code == 200, up.text
    assert up.json()["profile"]["hasAvatar"] is True
    got = client.get("/workspaces/settings/avatar", headers=auth_headers)
    assert got.status_code == 200
    assert got.content == _JPEG
    assert got.headers["content-type"].startswith("image/jpeg")


def test_replace_overwrites_bytes_and_revision(client, auth_headers):
    first = _upload(client, auth_headers, "a.png", _PNG, "image/png")
    assert first.status_code == 200
    rev1 = first.json()["profile"]["avatarRevision"]

    second = _upload(client, auth_headers, "b.jpg", _JPEG, "image/jpeg")
    assert second.status_code == 200
    rev2 = second.json()["profile"]["avatarRevision"]
    assert rev2 != rev1
    assert rev2 == hashlib.sha256(_JPEG).hexdigest()

    got = client.get("/workspaces/settings/avatar", headers=auth_headers)
    assert got.content == _JPEG


def test_rejects_unsupported_formats_without_writing(client, auth_headers):
    for name, data, mime in (
        ("x.gif", _GIF, "image/gif"),
        ("x.svg", _SVG, "image/svg+xml"),
        ("x.pdf", _PDF, "application/pdf"),
        ("x.bin", _JUNK, "application/octet-stream"),
        # Spoofed content-type: client claims PNG, bytes are GIF.
        ("spoof.png", _GIF, "image/png"),
    ):
        res = _upload(client, auth_headers, name, data, mime)
        assert res.status_code == 422, f"{name}: {res.status_code} {res.text}"
        detail = res.json().get("detail", "")
        assert "PNG or JPG" in detail

    settings = client.get("/workspaces/settings", headers=auth_headers).json()
    assert settings["profile"]["hasAvatar"] is False
    assert client.get("/workspaces/settings/avatar", headers=auth_headers).status_code == 404


def test_rejects_oversized_upload(client, auth_headers):
    # Magic bytes valid so only the size gate fires; exactly one byte past the cap.
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_AVATAR_BYTES + 1 - 8)
    assert len(oversized) == MAX_AVATAR_BYTES + 1

    res = _upload(client, auth_headers, "big.png", oversized, "image/png")
    assert res.status_code == 413, res.text
    settings = client.get("/workspaces/settings", headers=auth_headers).json()
    assert settings["profile"]["hasAvatar"] is False


def test_delete_clears_avatar(client, auth_headers):
    assert _upload(client, auth_headers, "me.png", _PNG, "image/png").status_code == 200
    deleted = client.delete("/workspaces/settings/avatar", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["profile"]["hasAvatar"] is False
    assert body["profile"]["avatarRevision"] is None

    assert client.get("/workspaces/settings/avatar", headers=auth_headers).status_code == 404
    settings = client.get("/workspaces/settings", headers=auth_headers).json()
    assert settings["profile"]["hasAvatar"] is False


def test_put_settings_does_not_clear_avatar(client, auth_headers):
    up = _upload(client, auth_headers, "me.png", _PNG, "image/png")
    assert up.status_code == 200
    rev = up.json()["profile"]["avatarRevision"]

    me = client.get("/auth/me", headers=auth_headers).json()
    put = client.put(
        "/workspaces/settings",
        json=_settings_payload(me["email"]),
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["profile"]["hasAvatar"] is True
    assert put.json()["profile"]["avatarRevision"] == rev

    got = client.get("/workspaces/settings/avatar", headers=auth_headers)
    assert got.status_code == 200
    assert got.content == _PNG


def test_second_user_cannot_see_first_users_avatar(client, auth_headers):
    assert _upload(client, auth_headers, "owner.png", _PNG, "image/png").status_code == 200

    email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    creds = {"email": email, "password": "Sup3rSecret"}
    assert client.post("/auth/register", json=creds).status_code == 201
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200
    other = {"Authorization": f"Bearer {login.json()['access_token']}"}

    settings = client.get("/workspaces/settings", headers=other).json()
    assert settings["profile"]["hasAvatar"] is False
    res = client.get("/workspaces/settings/avatar", headers=other)
    assert res.status_code == 404
    # Must never return the first user's bytes.
    assert res.content != _PNG
