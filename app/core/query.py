"""Query-string parsing shared by BE A list endpoints (history, documents)."""

from datetime import datetime, timezone

from app.core.errors import AppError

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50


def validation_error(message):
    return AppError(422, "VALIDATION_ERROR", message)


def parse_int(value, name, default, minimum, maximum):
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except ValueError:
        raise validation_error(f"Tham số {name} phải là số nguyên.") from None
    if not minimum <= number <= maximum:
        raise validation_error(f"Tham số {name} phải trong khoảng {minimum}-{maximum}.")
    return number


def parse_date(value, name):
    """ISO date or datetime -> (aware UTC datetime, date_only)."""
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise validation_error(f"Tham số {name} phải là ngày ISO (YYYY-MM-DD).") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, len(value) == 10


def paginate(items, page, size):
    import math

    total = len(items)
    window = items[(page - 1) * size : page * size]
    return window, {
        "page": page,
        "size": size,
        "total": total,
        "total_pages": math.ceil(total / size),
    }
