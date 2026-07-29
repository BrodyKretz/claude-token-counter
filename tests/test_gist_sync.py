import json
import subprocess
import urllib.request
from types import SimpleNamespace

import gist_sync


def test_get_github_token_returns_none_when_not_set(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )

    assert gist_sync.get_github_token() is None


def test_get_github_token_returns_stored_value(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ghp_abc123\n"),
    )

    assert gist_sync.get_github_token() == "ghp_abc123"


def test_set_github_token_calls_security_add_generic_password(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: calls.append(args),
    )

    gist_sync.set_github_token("ghp_xyz")

    assert calls == [
        [
            "security",
            "add-generic-password",
            "-s",
            gist_sync.KEYCHAIN_SERVICE,
            "-a",
            gist_sync.KEYCHAIN_SERVICE,
            "-w",
            "ghp_xyz",
            "-U",
        ]
    ]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_create_gist_returns_id(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=10):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.get_header("Authorization")
        return _FakeResponse({"id": "abc123"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    gist_id = gist_sync.create_gist("token123", {"name": "Alice", "total_tokens": 5})

    assert gist_id == "abc123"
    assert captured["method"] == "POST"
    assert captured["url"] == f"{gist_sync.API_BASE}/gists"
    assert captured["auth"] == "Bearer token123"
    assert captured["body"]["public"] is False
    stored_content = json.loads(
        captured["body"]["files"][gist_sync.GIST_FILENAME]["content"]
    )
    assert stored_content == {"name": "Alice", "total_tokens": 5}


def test_update_gist_patches_correct_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=10):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        return _FakeResponse({})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    gist_sync.update_gist("token123", "abc123", {"name": "Alice"})

    assert captured["method"] == "PATCH"
    assert captured["url"] == f"{gist_sync.API_BASE}/gists/abc123"


def test_fetch_gist_parses_file_content_without_auth(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=10):
        captured["auth"] = request.get_header("Authorization")
        return _FakeResponse(
            {
                "files": {
                    gist_sync.GIST_FILENAME: {
                        "content": json.dumps({"name": "Bob", "total_tokens": 9})
                    }
                }
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    content = gist_sync.fetch_gist("abc123")

    assert content == {"name": "Bob", "total_tokens": 9}
    assert captured["auth"] is None
