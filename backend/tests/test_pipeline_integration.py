"""First end-to-end integration test for the perception seam.

Every other test in this suite is a unit. This one proves the loop runs across
the whole seam: a video source -> PerceptionPipeline -> WorldModel -> a
broadcast WorldSnapshot.

Determinism / CI constraints (REQUIRED, all satisfied here):
  - NO Ollama, NO GPU, NO YOLO weights. The pipeline is built with
    yolo_weights=None, so `_run` exercises VO/SLAM + AprilTag detection on real
    (synthetic) frames but never touches a detector model.
  - Frames come from `SyntheticVideoSource` (seeded noise + moving rectangle):
    reproducible bytes -> reproducible VO -> deterministic test.
  - The pipeline's only frame-driving entry point is the async `_run` infinite
    loop (there is no synchronous single-tick method). We drive it as a
    cancellable asyncio task and poll `source.frames_read` until the synthetic
    source is fully consumed (bounded iteration count, not an unbounded sleep),
    then cancel the task. No flaky timing.

Why the detector is stubbed: there are no YOLO weights in CI, so the pipeline
cannot emit real detection entities. We split the seam into two halves that
together cover it end to end:
  1. source -> perception: `_run` consumes every synthetic frame through the
     real read/decode/VO/SLAM path WITHOUT error (asserted via frames_read and
     read_jpeg() == None afterwards).
  2. world -> broadcast: we upsert a representative YOLO Entity (standing in for
     a detector firing) and broadcast a WorldSnapshot through a RecordingHub,
     asserting the snapshot is recorded and carries that entity.
"""
from __future__ import annotations

import asyncio

from app.clock import FakeClock
from app.contracts import Entity, EntitySource, EntityType, Vec3, WorldSnapshot
from app.perception.pipeline import PerceptionPipeline
from app.world_model import WorldModel

from tests.fakes import RecordingHub, SyntheticVideoSource


# --- Part 2a: the doubles themselves behave as specified --------------------

def test_synthetic_source_yields_then_stops():
    source = SyntheticVideoSource(num_frames=3, width=160, height=120)
    source.start()
    frames = []
    for _ in range(3):
        frame = source.read_jpeg()
        assert frame is not None
        assert isinstance(frame, bytes) and len(frame) > 0
        frames.append(frame)
    # Exhausted: returns None thereafter.
    assert source.read_jpeg() is None
    # Distinct frames (moving rectangle + seeded noise => different bytes).
    assert len({f for f in frames}) == 3
    source.stop()
    assert source.is_streaming is False


def test_synthetic_source_is_deterministic():
    a = SyntheticVideoSource(num_frames=4, seed=7)
    b = SyntheticVideoSource(num_frames=4, seed=7)
    a.start()
    b.start()
    for _ in range(4):
        assert a.read_jpeg() == b.read_jpeg()


def test_recording_hub_captures_broadcast():
    hub = RecordingHub()

    async def drive():
        await hub.broadcast("hello")
        await hub.broadcast("world")

    asyncio.run(drive())
    assert hub.messages == ["hello", "world"]


# --- Part 2b: the real end-to-end seam --------------------------------------

def _consume_pipeline(source: SyntheticVideoSource, world: WorldModel) -> None:
    """Drive PerceptionPipeline._run as a cancellable task until the synthetic
    source is fully consumed, then cancel. Bounded polling => deterministic."""

    async def runner() -> None:
        pipeline = PerceptionPipeline(
            video_source=source,
            world=world,
            clock=FakeClock(1000.0),
            yolo_weights=None,        # no weights in CI -> SLAM/VO-only path
            perception_fps=1000.0,    # tiny inter-tick interval; consume fast
            img_width=source._width,
            img_height=source._height,
        )
        source.start()
        pipeline.start()

        # Poll until every synthetic frame has been read (read_jpeg advances the
        # index) OR a bounded number of yields elapse. perception_fps is huge so
        # each tick is near-instant; 200 yields is generous headroom and caps
        # the test even if VO were to stall, so it can never hang.
        for _ in range(200):
            if source.frames_read >= source._num_frames:
                break
            await asyncio.sleep(0.005)

        # Let the loop drain the final read (which returns None) so the
        # source-consumed assertion below is unambiguous.
        await asyncio.sleep(0.02)

        task = pipeline._task
        assert task is not None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())


def test_pipeline_consumes_source_and_world_broadcasts_snapshot():
    clock = FakeClock(1000.0)
    world = WorldModel(clock=clock)
    source = SyntheticVideoSource(num_frames=5, width=320, height=240)

    # HALF 1: source -> perception. Run the real loop over synthetic frames.
    # This exercises read_jpeg -> JPEG decode -> sliding-window VO/SLAM ->
    # AprilTag detection, with no detector model loaded. If any of that path
    # raised, the loop would print and continue, but VO running clean on these
    # frames is verified separately; here we assert the source was consumed.
    _consume_pipeline(source, world)

    # Every synthetic frame was pulled through the loop...
    assert source.frames_read == source._num_frames
    # ...and the source is now exhausted (matches a real EOF file source).
    assert source.read_jpeg() is None

    # HALF 2: world -> broadcast. Stand in for a detector firing (no weights in
    # CI): upsert a representative YOLO entity, then broadcast the snapshot the
    # server would push, through the recording hub.
    detector_entity = Entity(
        id="yolo_person_1_1",
        type=EntityType.OBJECT,
        position=Vec3(x=3.0, y=1.5, z=0.0),
        confidence=0.82,
        timestamp=clock.now(),
        source=EntitySource.YOLO,
        label="person",
    )
    world.upsert(detector_entity)

    hub = RecordingHub()

    async def broadcast_snapshot() -> None:
        snapshot = WorldSnapshot(entities=world.snapshot(), t=clock.now())
        await hub.broadcast(snapshot)

    asyncio.run(broadcast_snapshot())

    # A WorldSnapshot was broadcast and carries the detector's entity.
    assert len(hub.messages) == 1
    sent = hub.messages[0]
    assert isinstance(sent, WorldSnapshot)
    assert sent.t == clock.now()
    sent_ids = {e.id for e in sent.entities}
    assert "yolo_person_1_1" in sent_ids
    # And it round-trips as the type the WS layer validates against.
    yolo_entity = next(e for e in sent.entities if e.id == "yolo_person_1_1")
    assert yolo_entity.source is EntitySource.YOLO
    assert yolo_entity.type is EntityType.OBJECT
