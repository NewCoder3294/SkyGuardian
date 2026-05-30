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
