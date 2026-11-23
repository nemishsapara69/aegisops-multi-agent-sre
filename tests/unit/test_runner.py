from app.graph.runner import pending_approval


class FakeSnap:
    def __init__(self, next_nodes, tasks):
        self.next = next_nodes
        self.tasks = tasks


class FakeApp:
    def __init__(self, snap):
        self.snap = snap

    def get_state(self, config):
        return self.snap


class FakeInterrupt:
    value = {"question": "Approve this change?"}


class FakeTask:
    interrupts = (FakeInterrupt(),)


class FakeRunningTask:
    interrupts = ()


def test_finished_run_has_no_pending_approval():
    assert pending_approval(FakeApp(FakeSnap((), ())), "x") is None


def test_run_in_progress_is_not_reported_as_pending():
    app = FakeApp(FakeSnap(("investigator",), (FakeRunningTask(),)))
    assert pending_approval(app, "x") is None


def test_run_without_tasks_yet_is_not_reported_as_pending():
    assert pending_approval(FakeApp(FakeSnap(("triage",), ())), "x") is None


def test_real_interrupt_is_returned():
    app = FakeApp(FakeSnap(("governance",), (FakeTask(),)))
    assert pending_approval(app, "x") == {"question": "Approve this change?"}