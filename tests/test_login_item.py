import subprocess

import app


def test_set_start_at_login_enable_calls_launchctl_enable(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: calls.append(args),
    )

    app.set_start_at_login(True)

    assert calls == [["launchctl", "enable", app._service_target()]]


def test_set_start_at_login_disable_calls_launchctl_disable(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: calls.append(args),
    )

    app.set_start_at_login(False)

    assert calls == [["launchctl", "disable", app._service_target()]]
