import json
import logging
import re
from typing import Any

import colorlog

from src.core.config import settings


def mask_sensitive_data(data: Any, sensitive_keys: list[str]) -> Any:
    """Recursively mask sensitive keys in nested dicts or lists."""
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if k.lower() in sensitive_keys:
                masked[k] = "***FILTERED***"
            else:
                masked[k] = mask_sensitive_data(v, sensitive_keys)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item, sensitive_keys) for item in data]
    return data


def mask_string_or_json(content: str, sensitive_keys: list[str]) -> str:
    """Mask sensitive parameters in a raw string, attempting JSON parsing first."""
    if not content:
        return content
    try:
        # Attempt to parse as JSON
        data = json.loads(content)
        masked_data = mask_sensitive_data(data, sensitive_keys)
        return json.dumps(masked_data)
    except json.JSONDecodeError:
        # Fallback to regex-based masking for query params / form-data / log text
        masked = content
        for key in sensitive_keys:
            # Query param or form style: key=value
            pattern = re.compile(rf"({key}\s*=\s*)[^&\s]+", re.IGNORECASE)
            masked = pattern.sub(r"\1***FILTERED***", masked)
            # JSON-like string style: "key": "value"
            pattern_json = re.compile(rf'("{key}"\s*:\s*")[^"]+(")', re.IGNORECASE)
            masked = pattern_json.sub(r"\1***FILTERED***\2", masked)
        return masked


class MaskingColoredFormatter(colorlog.ColoredFormatter):
    """Logging Formatter that applies colors and masks sensitive values."""

    def format(self, record: logging.LogRecord) -> str:
        # Save original message to avoid mutating it permanently if needed
        orig_msg = record.msg
        orig_args = record.args

        # Mask the main log message
        if isinstance(record.msg, str):
            record.msg = mask_string_or_json(record.msg, settings.SENSITIVE_KEYS)
        elif isinstance(record.msg, dict):
            record.msg = mask_sensitive_data(record.msg, settings.SENSITIVE_KEYS)

        # Mask any string arguments passed to log format
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(mask_string_or_json(arg, settings.SENSITIVE_KEYS))
                elif isinstance(arg, dict):
                    new_args.append(mask_sensitive_data(arg, settings.SENSITIVE_KEYS))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)

        try:
            return super().format(record)
        finally:
            # Restore original to prevent side-effects in other handlers
            record.msg = orig_msg
            record.args = orig_args


def setup_logging():
    """Configure root logger to use colored masking logs."""
    log_format = (
        "%(log_color)s[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s"
    )

    # Configure handlers
    console_handler = logging.StreamHandler()
    formatter = MaskingColoredFormatter(
        log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
    console_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
    else:
        root_logger.handlers = [console_handler]

    # Set external libraries log levels to be less verbose
    logging.getLogger("uvicorn.access").disabled = (
        True  # We will log requests ourselves!
    )
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("amqp").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
