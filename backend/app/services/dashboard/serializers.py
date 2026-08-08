from datetime import date, datetime
from decimal import Decimal


def serialize_dashboard(value):
    """Convert the internal read model into stable JSON-compatible primitives."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serialize_dashboard(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_dashboard(item) for item in value]
    return value
