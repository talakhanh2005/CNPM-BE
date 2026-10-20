"""Database-independent identifiers and UTC timestamps."""

from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid4())
