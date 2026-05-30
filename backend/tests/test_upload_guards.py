"""Guards on the operator video-upload control-plane endpoint.

These cover the hardening added to backend/app/server.py: a streamed size cap,
video-extension allowlist, single-flight state guard, and the optional
OPERATOR_KEY gate. The endpoint handler is exercised directly (as a coroutine)
so the tests need neither python-multipart nor a running server, and they never
reach the perception path (every case rejects before the background task).
"""
import asyncio
import io

import pytest
from starlette.datastructures import UploadFile

from app import server


def _upload(filename: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Point uploads at a temp dir and reset the single-slot status registry
    around every test so order can't leak state."""
    monkeypatch.setattr(server, "_UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(server, "_OPERATOR_KEY", "")
    server._upload_status.update({"state": "idle", "name": None, "error": None})
    yield
    server._upload_status.update({"state": "idle", "name": None, "error": None})


# --- _save_upload_capped ----------------------------------------------------

def test_save_capped_aborts_and_cleans_up_over_limit(tmp_path):
    dest = tmp_path / "big.mp4"
    with pytest.raises(ValueError):
        server._save_upload_capped(io.BytesIO(b"x" * 4096), dest, max_bytes=1024)
    assert not dest.exists()  # partial file removed, no half-written clip left behind


def test_save_capped_writes_payload_under_limit(tmp_path):
    dest = tmp_path / "ok.mp4"
    written = server._save_upload_capped(io.BytesIO(b"abcde"), dest, max_bytes=1024)
    assert written == 5
    assert dest.read_bytes() == b"abcde"


# --- _require_operator ------------------------------------------------------

def test_operator_gate_is_noop_when_key_unset(monkeypatch):
    monkeypatch.setattr(server, "_OPERATOR_KEY", "")
    server._require_operator(None)          # no key configured → open
    server._require_operator("anything")


def test_operator_gate_enforced_when_key_set(monkeypatch):
    monkeypatch.setattr(server, "_OPERATOR_KEY", "s3cret")
    with pytest.raises(server.HTTPException) as missing:
        server._require_operator(None)
    assert missing.value.status_code == 401
    with pytest.raises(server.HTTPException):
        server._require_operator("wrong")
    server._require_operator("s3cret")      # correct key passes


# --- endpoint guards (direct coroutine calls, reject before perception) -----

def test_upload_rejects_non_video_extension():
    with pytest.raises(server.HTTPException) as exc:
        asyncio.run(server.upload_source_video(file=_upload("notes.txt", b"hi"), _=None))
    assert exc.value.status_code == 400


def test_upload_rejects_concurrent_upload():
    server._upload_status["state"] = "processing"
    with pytest.raises(server.HTTPException) as exc:
        asyncio.run(server.upload_source_video(file=_upload("clip.mp4", b"\x00"), _=None))
    assert exc.value.status_code == 409


def test_upload_rejects_oversize_and_marks_error(monkeypatch):
    monkeypatch.setattr(server, "_MAX_UPLOAD_BYTES", 4)
    with pytest.raises(server.HTTPException) as exc:
        asyncio.run(server.upload_source_video(file=_upload("clip.mp4", b"toolong"), _=None))
    assert exc.value.status_code == 413
    assert server._upload_status["state"] == "error"
