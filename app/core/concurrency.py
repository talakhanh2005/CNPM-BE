from functools import wraps
from threading import RLock

# The signaling deployment uses one API process. SQL row locks / Mongo CAS additionally
# protect slot assignment; these locks serialize local membership changes with frame saves.
_meeting_locks = [RLock() for _ in range(128)]


def meeting_lock(meeting_id):
    return _meeting_locks[hash(meeting_id) % len(_meeting_locks)]


def meeting_operation(method):
    @wraps(method)
    def locked(self, meeting_id, *args, **kwargs):
        with meeting_lock(meeting_id):
            return method(self, meeting_id, *args, **kwargs)

    return locked
