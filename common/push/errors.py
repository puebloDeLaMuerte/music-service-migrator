"""Structured push errors (provider capabilities and apply failures)."""

from __future__ import annotations

from enum import Enum


class PushErrorCode(str, Enum):
    NOT_SUPPORTED = "not_supported"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    PLAN_MISSING = "plan_missing"
    PLAN_BLOCKED = "plan_blocked"
    PLAN_STALE = "plan_stale"
    REMOTE_ERROR = "remote_error"


class PushError(Exception):
    def __init__(self, code: PushErrorCode, message: str, *, recoverable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable

    def __str__(self) -> str:
        return self.message
