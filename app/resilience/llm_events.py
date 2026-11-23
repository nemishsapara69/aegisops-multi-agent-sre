from collections import deque

EVENTS = deque(maxlen=1000)      # recent LLM attempts, newest last
_LISTENERS = []


def add_listener(fn):
    _LISTENERS.append(fn)


def remove_listener(fn):
    if fn in _LISTENERS:
        _LISTENERS.remove(fn)


def emit(event):
    EVENTS.append(event)
    for fn in list(_LISTENERS):
        try:
            fn(event)
        except Exception:
            pass                 # a broken listener must never break an incident