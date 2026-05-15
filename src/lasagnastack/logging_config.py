import logging
import os
from typing import Any

import structlog

_FIELD_PRIORITY = ["stage", "source"]


def _prioritise_fields(
    logger: Any,
    method: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Reorder event dict so priority fields appear first in console output.

    Args:
        logger: Unused; required by the structlog processor protocol.
        method: Unused; required by the structlog processor protocol.
        event_dict: The log event dict to reorder in-place.

    Returns:
        New event dict with priority fields moved to the front.
    """
    front = {k: event_dict.pop(k) for k in _FIELD_PRIORITY if k in event_dict}
    return {**front, **event_dict}


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for the process.

    Reads ``LOG_FORMAT`` from the environment: set to ``"json"`` for
    machine-parseable output (useful in CI or when shipping logs to an
    aggregator). Any other value (or absent) produces human-readable
    ``ConsoleRenderer`` output.

    Args:
        level: Minimum log level string, e.g. ``"INFO"`` or ``"DEBUG"``.
    """
    use_json = os.getenv("LOG_FORMAT", "").lower() == "json"
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if use_json
        else structlog.dev.ConsoleRenderer(colors=True, sort_keys=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            _prioritise_fields,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
