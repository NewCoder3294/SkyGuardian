"""TELLO_DISABLE gates the laptop's Tello stack.

When the phone owns the Tello (demo topology), the backend must not contend for
it. The flag flips health reporting to "disabled" and is what the startup hook
checks before starting tello_client/tello_camera/follow.
"""
from app import server


def test_tello_health_reports_disabled_when_flagged(monkeypatch):
    monkeypatch.setattr(server, "_TELLO_DISABLED", True)
    assert server._tello_health() == "disabled"


def test_tello_health_reflects_client_state_when_enabled(monkeypatch):
    monkeypatch.setattr(server, "_TELLO_DISABLED", False)
    # Enabled → delegates to the live client state (DISCONNECTED at rest in tests).
    assert server._tello_health() == server.tello_client.state.value
