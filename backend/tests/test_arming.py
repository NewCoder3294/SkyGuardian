from app.follow.arming import ArmingLock


def test_unowned_lock_denies_all():
    lock = ArmingLock()
    assert lock.holder is None
    assert lock.can_command("follow") is False
    assert lock.can_command("approach") is False


def test_acquire_grants_exclusive_command_rights():
    lock = ArmingLock()
    assert lock.acquire("follow") is True
    assert lock.holder == "follow"
    assert lock.can_command("follow") is True
    assert lock.can_command("approach") is False


def test_acquire_is_rejected_while_held_by_another():
    lock = ArmingLock()
    assert lock.acquire("follow") is True
    assert lock.acquire("approach") is False
    assert lock.holder == "follow"


def test_reacquire_by_same_owner_is_idempotent():
    lock = ArmingLock()
    assert lock.acquire("follow") is True
    assert lock.acquire("follow") is True
    assert lock.holder == "follow"


def test_release_clears_only_for_holder():
    lock = ArmingLock()
    lock.acquire("follow")
    assert lock.release("approach") is False
    assert lock.holder == "follow"
    assert lock.release("follow") is True
    assert lock.holder is None
