import threading
import time

import pytest

from app.video import NullSource, StreamVideoSource, make_source


def test_make_source_selects_type():
    assert isinstance(make_source("url:rtsp://x/y"), StreamVideoSource)
    assert isinstance(make_source("file:/tmp/clip.mp4"), StreamVideoSource)
    assert isinstance(make_source("device:0"), StreamVideoSource)
    assert isinstance(make_source("/tmp/clip.mp4"), StreamVideoSource)
    assert isinstance(make_source(""), NullSource)
    assert isinstance(make_source(None), NullSource)


def test_null_source_never_produces_frames():
    source = NullSource()
    source.start()
    assert source.read_jpeg() is None
    assert source.is_streaming is False
    source.stop()


def test_invalid_device_spec_is_rejected():
    with pytest.raises(ValueError, match="device spec must be an integer"):
        make_source("device:not-an-int")


def test_unknown_source_kind_is_rejected():
    with pytest.raises(ValueError, match="unknown video source kind"):
        make_source("unknown:value")


def test_stream_source_start_does_not_block_on_slow_capture_open():
    open_started = threading.Event()

    class SlowCapture:
        def __init__(self, _spec):
            open_started.set()
            time.sleep(0.2)
            self.released = False

        def isOpened(self):
            return False

        def read(self):
            return False, None

        def release(self):
            self.released = True

    class FakeCv2:
        IMWRITE_JPEG_QUALITY = 1

        def VideoCapture(self, spec):
            return SlowCapture(spec)

        def imencode(self, _ext, _frame, _params):
            return False, None

    source = StreamVideoSource.__new__(StreamVideoSource)
    source._cv2 = FakeCv2()
    source._spec = "rtmp://127.0.0.1:1935/live"
    source._jpeg_quality = 80
    source._cap = None
    source._lock = threading.Lock()
    source._latest_jpeg = None
    source._thread = None
    source._stop = threading.Event()

    started_at = time.monotonic()
    source.start()
    elapsed = time.monotonic() - started_at
    try:
        assert elapsed < 0.1
        assert open_started.wait(timeout=1)
    finally:
        source.stop()
