from __future__ import annotations

from typing import Any

from marcedit_web.render import operation_activity


class FakeStatus:
    def __init__(self, owner: "FakeStatusFactory") -> None:
        self.owner = owner
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class FakeStatusFactory:
    def __init__(self) -> None:
        self.created: list[tuple[str, bool]] = []
        self._status: FakeStatus | None = None

    def __call__(self, label: str, *, expanded: bool) -> FakeStatus:
        self.created.append((label, expanded))
        self._status = FakeStatus(self)
        return self._status

    @property
    def status(self) -> FakeStatus:
        assert self._status is not None
        return self._status

    @property
    def updates(self) -> list[dict[str, Any]]:  # type: ignore[no-redef]
        assert self._status is not None
        return self._status.updates


class FakeProgress:
    def __init__(self, owner: "FakeProgressFactory") -> None:
        self.owner = owner

    def progress(self, value: float) -> None:
        self.owner.values.append(value)


class FakeProgressFactory:
    def __init__(self) -> None:
        self.created: list[FakeProgress] = []
        self.values: list[float] = []

    def __call__(self, value: float = 0.0) -> FakeProgress:
        progress = FakeProgress(self)
        self.created.append(progress)
        self.values.append(value)
        return progress


class FakePlaceholder:
    def __init__(self, owner: "FakeStreamlit") -> None:
        self.owner = owner
        self.values: list[str] = []
        self._replaced_initial = False

    def write(self, value: str) -> None:
        self.values.append(value)
        if " record " in value and self.owner.messages and not self._replaced_initial:
            self.owner.messages[-1] = value
            self._replaced_initial = True
            return
        self.owner.messages.append(value)

    def markdown(self, value: str) -> None:
        self.values.append(value)
        if " record " in value and self.owner.messages and not self._replaced_initial:
            self.owner.messages[-1] = value
            self._replaced_initial = True
            return
        self.owner.messages.append(value)


class FakeStreamlit:
    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.status = FakeStatusFactory()
        self.progress = FakeProgressFactory()
        self.messages: list[str] = []

    def empty(self) -> FakePlaceholder:
        return FakePlaceholder(self)

    def write(self, value: str) -> None:
        self.messages.append(value)


def test_activity_starts_expanded_and_finishes_collapsed(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)

    with operation_activity.open_activity(
        "quick-field-change-preview",
        "Quick field change",
        phase="Preparing",
        total=1000,
    ) as activity:
        activity.phase("Previewing", "Running in the sandbox")
        activity.complete("Preview ready", "Review the changes below.")

    assert fake.status.created == [("Quick field change", True)]
    assert fake.messages[0] == "Preparing…"
    assert fake.status.updates[-1] == {
        "label": "Preview ready",
        "state": "complete",
        "expanded": False,
    }
    assert fake.session_state[operation_activity.COMPLETION_KEY] == {
        "operation_id": "quick-field-change-preview",
        "state": "complete",
        "label": "Preview ready",
        "message": "Review the changes below.",
    }


def test_progress_uses_existing_first_boundary_and_throttle(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)
    with operation_activity.open_activity(
        "quick-batch-preview", "Quick batch", phase="Previewing", total=1000
    ) as activity:
        for value in (1, 2, 250, 251, 500, 1000):
            activity.progress_callback(value, 1000)

    assert fake.progress.values == [0.0, 0.001, 0.25, 0.5, 1.0]
    assert fake.messages == [
        "Previewing record 1 of 1,000…",
        "Previewing record 250 of 1,000…",
        "Previewing record 500 of 1,000…",
        "Previewing record 1,000 of 1,000…",
    ]


def test_progress_ignores_sparse_non_boundary_callbacks(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)
    with operation_activity.open_activity(
        "quick-batch-preview", "Quick batch", phase="Previewing", total=1000
    ) as activity:
        for value in (1, 501, 750, 1000):
            activity.progress_callback(value, 1000)

    assert fake.progress.values == [0.0, 0.001, 0.75, 1.0]
    assert fake.messages == [
        "Previewing record 1 of 1,000…",
        "Previewing record 750 of 1,000…",
        "Previewing record 1,000 of 1,000…",
    ]


def test_zero_total_reports_progress_unavailable(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)
    with operation_activity.open_activity(
        "find-preview", "Find and replace", phase="Preparing", total=0
    ) as activity:
        activity.progress_callback(0, 0)

    assert fake.messages[-1] == "Progress unavailable — processing records…"
    assert fake.progress.created == []


def test_unknown_total_reports_progress_unavailable(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)
    with operation_activity.open_activity(
        "find-preview", "Find and replace", phase="Preparing", total=None
    ) as activity:
        activity.progress_callback(1, 0)

    assert fake.messages[-1] == "Progress unavailable — processing records…"
    assert fake.progress.created == []


def test_failure_collapses_status_and_stores_error_summary(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(operation_activity, "st", fake)

    with operation_activity.open_activity(
        "find-preview", "Find and replace", phase="Preparing", total=None
    ) as activity:
        activity.fail("Preview failed", "The sandbox rejected this request.")

    assert fake.status.updates[-1] == {
        "label": "Preview failed",
        "state": "error",
        "expanded": False,
    }
    assert fake.session_state[operation_activity.COMPLETION_KEY] == {
        "operation_id": "find-preview",
        "state": "error",
        "label": "Preview failed",
        "message": "The sandbox rejected this request.",
    }


def test_render_completion_and_clear_are_operation_scoped(monkeypatch):
    fake = FakeStreamlit(
        session_state={
            operation_activity.COMPLETION_KEY: {
                "operation_id": "quick-batch-preview",
                "state": "complete",
                "label": "Preview ready",
                "message": "Review below.",
            }
        }
    )
    monkeypatch.setattr(operation_activity, "st", fake)

    assert operation_activity.render_completion("quick-batch-preview")
    assert not operation_activity.render_completion("quick-field-change-preview")
    operation_activity.clear_completion("quick-batch-preview")
    assert operation_activity.COMPLETION_KEY not in fake.session_state
