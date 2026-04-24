import json
import logging
from datetime import datetime
from django.utils import timezone


logger = logging.getLogger("projects")


def _serialize(value):
    """Make values JSON-safe."""
    if isinstance(value, datetime):
        return timezone.localtime(value).isoformat()
    return value


def log_event(event: str, level="info", **fields):
    payload = {
        "event": event,
        "timestamp": timezone.now().isoformat(),
        **{k: _serialize(v) for k, v in fields.items()},
    }

    message = json.dumps(payload)

    getattr(logger, level)(message)