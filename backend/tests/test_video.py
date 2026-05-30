from app.clock import FakeClock
from app.video import (
    BOUNDARY,
    DisabledSource,
    MockCameraSource,
    StreamVideoSource,
    TelloVideoSource,
    make_source,
)


def test_make_source_selects_type():
    assert isinstance(make_source("tello", "TELLO"), TelloVideoSource)
    assert isinstance(make_source("url:rtsp://x/y", "MAVIC"), StreamVideoSource)
    assert isinstance(make_source("mock", "TELLO", clock=FakeClock()), MockCameraSource)
    # unset/unknown -> honest empty feed, never a mock
    assert isinstance(make_source("", "MAVIC"), DisabledSource)
    assert isinstance(make_source("bogus", "TELLO"), DisabledSource)


def test_tello_source_returns_none_until_connected():
    # Before start()/connect, read_jpeg is non-blocking and returns None.
    assert TelloVideoSource().read_jpeg() is None
    assert DisabledSource().read_jpeg() is None


def test_mock_source_produces_jpeg():
    src = MockCameraSource("TELLO", clock=FakeClock(1.0))
    data = src.read_jpeg()
    assert data is not None
    # JPEG SOI / EOI magic bytes.
    assert data[:2] == b"\xff\xd8"
    assert data[-2:] == b"\xff\xd9"


def test_frames_differ_over_time():
    clock = FakeClock(0.0)
    src = MockCameraSource("TELLO", clock=clock)
    a = src.read_jpeg()
    clock.advance(0.5)
    b = src.read_jpeg()
    # Moving target box => the encoded frame changes.
    assert a != b


def test_mjpeg_stream_yields_multipart_frames():
    import asyncio

    from app.video import MJPEG_MEDIA_TYPE, mjpeg_stream

    async def first_two() -> list[bytes]:
        gen = mjpeg_stream(MockCameraSource("TELLO", clock=FakeClock(0.0)), fps=1000.0)
        out = []
        async for chunk in gen:
            out.append(chunk)
            if len(out) >= 2:
                break
        return out

    chunks = asyncio.run(first_two())
    assert len(chunks) == 2
    for chunk in chunks:
        assert chunk.startswith(b"--" + BOUNDARY.encode())
        assert b"Content-Type: image/jpeg" in chunk
        assert b"\xff\xd8" in chunk and b"\xff\xd9" in chunk  # full JPEG in each part
    assert "multipart/x-mixed-replace" in MJPEG_MEDIA_TYPE
