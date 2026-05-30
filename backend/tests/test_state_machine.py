from app.clock import FakeClock
from app.contracts import Command
from app.state_machine import MissionStateMachine, Stage


def test_follow_me_from_idle():
    sm = MissionStateMachine(clock=FakeClock())
    assert sm.apply(Command.FOLLOW_ME) is Stage.FOLLOWING


def test_hold_only_from_following():
    sm = MissionStateMachine(clock=FakeClock())
    assert sm.apply(Command.HOLD) is Stage.IDLE  # ignored from idle, no-op
    sm.apply(Command.FOLLOW_ME)
    assert sm.apply(Command.HOLD) is Stage.HOLDING


def test_stop_is_always_live():
    sm = MissionStateMachine(clock=FakeClock())
    sm.apply(Command.FOLLOW_ME)
    assert sm.apply(Command.STOP) is Stage.STOPPED


def test_recall_from_any_stage():
    sm = MissionStateMachine(clock=FakeClock())
    sm.apply(Command.FOLLOW_ME)
    sm.apply(Command.HOLD)
    assert sm.apply(Command.RECALL) is Stage.RECALL


def test_transitions_are_logged():
    clock = FakeClock(50.0)
    sm = MissionStateMachine(clock=clock)
    sm.apply(Command.FOLLOW_ME)
    clock.advance(2.0)
    sm.apply(Command.STOP)
    events = sm.events
    assert len(events) == 2
    assert events[0].from_stage is Stage.IDLE and events[0].to_stage is Stage.FOLLOWING
    assert events[1].to_stage is Stage.STOPPED
    assert events[1].t == 52.0


def test_fail_records_reason_and_stops():
    sm = MissionStateMachine(clock=FakeClock())
    sm.apply(Command.FOLLOW_ME)
    sm.fail("lost_tag")
    assert sm.stage is Stage.STOPPED
    assert sm.last_error == "lost_tag"


def test_approach_command_enters_approach_stage():
    from app.contracts import Command
    from app.state_machine import MissionStateMachine, Stage
    m = MissionStateMachine()
    m.apply(Command.FOLLOW_ME)     # IDLE -> FOLLOWING (verified earlier)
    m.apply(Command.APPROACH)
    assert m.stage is Stage.APPROACH


def test_stop_aborts_approach():
    from app.contracts import Command
    from app.state_machine import MissionStateMachine, Stage
    m = MissionStateMachine()
    m.apply(Command.FOLLOW_ME)
    m.apply(Command.APPROACH)
    m.apply(Command.STOP)
    assert m.stage is Stage.STOPPED
