"""Oracle Phase 1 — Kill switch reader.

Reads ORACLE_AUTONOMOUS_RUN_ENABLED from the environment and returns
a boolean that gates autonomous Oracle run activity.

Returns True only when the variable is present and its value, after
stripping surrounding whitespace and lowercasing, is exactly "true"
or "1".  Any other value — including absent, empty, whitespace-only,
"yes", "on", "false", "0", or arbitrary strings — returns False.

The function never reads or mutates environment state at import time.
It accepts an optional env mapping for deterministic testing without
patching the process environment.
"""

from __future__ import annotations

import os

_ENV_VAR: str = "ORACLE_AUTONOMOUS_RUN_ENABLED"
_ENABLED_TOKENS: frozenset[str] = frozenset({"true", "1"})


def is_autonomous_run_enabled(env: dict[str, str] | None = None) -> bool:
    """Return True if autonomous Oracle runs are currently enabled.

    Args:
        env: Optional string-to-string mapping consulted instead of
            os.environ.  Pass None (the default) to read from the real
            process environment at call time.  Pass an explicit dict in
            tests to avoid patching the process environment.

    Returns:
        True when ORACLE_AUTONOMOUS_RUN_ENABLED strips and lowercases
        to exactly "true" or "1".  False for every other condition,
        including a missing variable.
    """
    mapping: dict[str, str] | os._Environ = os.environ if env is None else env  # type: ignore[type-arg]
    raw: str | None = mapping.get(_ENV_VAR)
    if raw is None:
        return False
    return raw.strip().lower() in _ENABLED_TOKENS
