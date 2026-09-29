"""Structured logging setup with secret redaction.

Two formatters are available:

* human-readable single-line text (default, used during development)
* machine-readable JSON (recommended for deployed environments)

Every log record passes through :class:`SecretRedactionFilter`, which removes
API keys, bearer tokens, authorization headers, passwords and query-string
secrets from the emitted message and arguments. Secrets must therefore never
be logged in the first place, but this filter is a defensive second line.

The module also defines the canonical pipeline trace labels used across the
backend so the team can follow a single claim end to end.
"""

import json
import logging
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple

# --------------------------------------------------------------------------
# Canonical trace labels
# --------------------------------------------------------------------------
TRANSCRIPT_RECEIVED = "TRANSCRIPT_RECEIVED"
CLAIM_CREATED = "CLAIM_CREATED"
VERIFICATION_STARTED = "VERIFICATION_STARTED"
VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
FRONTEND_BROADCAST = "FRONTEND_BROADCAST"
SESSION_STARTED = "SESSION_STARTED"
SESSION_STOPPED = "SESSION_STOPPED"
WS_CLIENT_CONNECTED = "WS_CLIENT_CONNECTED"
WS_CLIENT_DISCONNECTED = "WS_CLIENT_DISCONNECTED"
SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"

# Logger name used for pipeline tracing so labels can be filtered in isolation.
trace_logger = logging.getLogger("live_fact_checker.trace")

_RESERVED_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName"}


#: The literal text substituted for any detected secret.
REDACTED = "[REDACTED]"

#: Regexes for values that must never reach a log sink, each paired with the
#: replacement that preserves non-secret context (such as the key name).
_SECRET_PATTERNS: Tuple[Tuple[Pattern[str], Any], ...] = (
    # key=value / "key": "value" for anything secret-shaped
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_]*(?:api[_-]?key|apikey|secret|password|passwd|token|credential)s?)"
            r"(\s*[:=]\s*)[\"']?([^\s,;\"'}\)\]]+)[\"']?"
        ),
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}",
    ),
    # Authorization: Bearer <token>
    (
        re.compile(r"(?i)\b(authorization)(\s*[:=]\s*)[\"']?bearer\s+[A-Za-z0-9._\-\+/=]+"),
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}",
    ),
    # A bare bearer token anywhere in the message
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-\+/=]{12,}"), lambda m: f"bearer {REDACTED}"),
    # Well-known provider key shapes
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), REDACTED),
    # Credentials embedded in a URL: scheme://user:password@host
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"),
        lambda m: f"{m.group(1)}{REDACTED}@",
    ),
)


def _redact_text(text: str) -> str:
    """Mask any secret-looking substring inside ``text``."""
    if not text:
        return text
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


#: Attribute/dict key names whose *value* is always a secret.
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)api[_-]?key|apikey|secret|password|passwd|token|authorization|credential"
)


def is_secret_key(name: Any) -> bool:
    """Return whether a key/attribute name implies its value is a secret.

    Used for both structured log fields (``extra={"apiKey": ...}``) and nested
    dictionaries, so a secret is masked by *name* even when the value itself
    carries no recognisable pattern.
    """
    return isinstance(name, str) and bool(_SECRET_KEY_PATTERN.search(name))


def _redact_value(value: Any) -> Any:
    """Recursively redact secrets inside dicts, lists, tuples and strings."""
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {
            key: (
                _redact_value(value[key])
                if isinstance(value[key], (dict, list, tuple, set))
                else REDACTED
            )
            if is_secret_key(key)
            else _redact_value(value[key])
            for key in value
        }
    if isinstance(value, (list, tuple, set)):
        redacted = [_redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(redacted)
        if isinstance(value, set):
            return set(redacted)
        return redacted
    return value


class SecretRedactionFilter(logging.Filter):
    """Logging filter that strips secrets from messages and arguments."""

    def __init__(self, extra_secret_values: Optional[Iterable[str]] = None) -> None:
        super().__init__()
        self._literals: List[str] = []
        for secret in extra_secret_values or ():
            if secret and len(secret) >= 6:
                self._literals.append(secret)

    def register_secret(self, secret: Optional[str]) -> None:
        """Register a literal secret value so it is masked verbatim."""
        if secret and len(secret) >= 6 and secret not in self._literals:
            self._literals.append(secret)

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the record in place. Always returns ``True``."""
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _redact_value(record.args)
            else:
                record.args = tuple(_redact_value(arg) for arg in record.args)

        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            # A structured field whose *name* is secret-shaped is masked whole,
            # even if its value matches none of the text patterns.
            if is_secret_key(key) and not isinstance(value, (dict, list, tuple, set)):
                record.__dict__[key] = REDACTED
            else:
                record.__dict__[key] = self._scrub_value(value)
        return True

    def _scrub(self, text: str) -> str:
        for literal in self._literals:
            if literal in text:
                text = text.replace(literal, REDACTED)
        return _redact_text(text)

    def _scrub_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._scrub(value)
        return _redact_value(value)


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def _formatter_for(json_output: bool) -> logging.Formatter:
    if json_output:
        return JsonFormatter()
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    secret_values: Optional[Iterable[str]] = None,
) -> logging.Logger:
    """Install the root handler, redaction filter and formatter.

    Safe to call more than once; existing handlers are replaced so repeated
    calls (app startup plus tests) do not duplicate log lines.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_formatter_for(json_output))
    handler.addFilter(SecretRedactionFilter(extra_secret_values=secret_values))

    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    trace_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return trace_logger


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger for a backend module."""
    return logging.getLogger(f"live_fact_checker.{name}")


def register_secret(secret: Optional[str]) -> None:
    """Register a live secret value with every installed redaction filter."""
    for handler in logging.getLogger().handlers:
        for log_filter in handler.filters:
            if isinstance(log_filter, SecretRedactionFilter):
                log_filter.register_secret(secret)


def log_trace(label: str, **fields: Any) -> None:
    """Emit a pipeline trace record carrying a canonical label.

    Example::

        log_trace(TRANSCRIPT_RECEIVED, sessionId="session_001", isFinal=True)
    """
    trace_logger.info(label, extra={"trace": label, **fields})
