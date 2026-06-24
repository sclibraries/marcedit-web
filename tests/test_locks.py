"""Advisory lock primitive for collaboration foundations (TASK-083)."""
from __future__ import annotations

import threading

import pytest

from marcedit_web.lib import db, locks


@pytest.fixture(autouse=True)
def _schema():
    db.init_schema()


def test_acquire_unlocked_resource():
    decision = locks.acquire_lock("job", "j1", "alice@example.edu", ttl_seconds=60)

    assert decision.acquired is True
    assert decision.holder_email == "alice@example.edu"
    row = locks.get_lock("job", "j1")
    assert row is not None
    assert row["holder_email"] == "alice@example.edu"


def test_acquire_denies_other_holder_before_expiry():
    locks.acquire_lock("job", "j1", "alice@example.edu", ttl_seconds=60)

    decision = locks.acquire_lock("job", "j1", "bob@example.edu", ttl_seconds=60)

    assert decision.acquired is False
    assert decision.holder_email == "alice@example.edu"
    assert locks.get_lock("job", "j1")["holder_email"] == "alice@example.edu"


def test_same_holder_refreshes_lock():
    first = locks.acquire_lock("job", "j1", "alice@example.edu", ttl_seconds=60)
    second = locks.acquire_lock("job", "j1", "alice@example.edu", ttl_seconds=120)

    assert first.acquired is True
    assert second.acquired is True
    assert second.holder_email == "alice@example.edu"
    assert second.expires_at > first.expires_at


def test_expired_lock_can_be_acquired_by_new_holder():
    locks.acquire_lock("job", "j1", "alice@example.edu", ttl_seconds=-1)

    decision = locks.acquire_lock("job", "j1", "bob@example.edu", ttl_seconds=60)

    assert decision.acquired is True
    assert decision.holder_email == "bob@example.edu"


def test_only_holder_can_release_lock():
    locks.acquire_lock("record", "r1", "alice@example.edu", ttl_seconds=60)

    assert locks.release_lock("record", "r1", "bob@example.edu") is False
    assert locks.get_lock("record", "r1") is not None
    assert locks.release_lock("record", "r1", "alice@example.edu") is True
    assert locks.get_lock("record", "r1") is None


def test_expire_locks_removes_expired_rows():
    locks.acquire_lock("record", "old", "alice@example.edu", ttl_seconds=-1)
    locks.acquire_lock("record", "new", "alice@example.edu", ttl_seconds=60)

    assert locks.expire_locks() == 1

    assert locks.get_lock("record", "old") is None
    assert locks.get_lock("record", "new") is not None


def test_concurrent_acquire_has_one_winner():
    winners: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def contender(i: int) -> None:
        try:
            holder = f"user-{i}@example.edu"
            barrier.wait()
            decision = locks.acquire_lock("record", "r1", holder, ttl_seconds=60)
            if decision.acquired:
                winners.append(holder)
        except BaseException as exc:  # pragma: no cover - re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=contender, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(winners) == 1
    assert locks.get_lock("record", "r1")["holder_email"] == winners[0]
