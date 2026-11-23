import time

from langgraph.types import Command


def _config(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def current_state(app, thread_id):
    return dict(app.get_state(_config(thread_id)).values)


def pending_approval(app, thread_id):
    """Returns the approval request (a dict) only if the run is really paused for a human.
    A run that is merely in progress has snap.next set but no interrupt, so it returns None."""
    snap = app.get_state(_config(thread_id))
    if not snap.next:
        return None
    for task in snap.tasks:
        for item in (getattr(task, "interrupts", None) or ()):
            return item.value
    return None


def start_incident(app, alert, role, thread_id):
    app.invoke({"raw_alert": alert, "user_role": role, "run_id": thread_id, "started_at": time.time()},
               _config(thread_id))
    return current_state(app, thread_id)


def resume_incident(app, thread_id, decision):
    app.invoke(Command(resume=decision), _config(thread_id))
    return current_state(app, thread_id)