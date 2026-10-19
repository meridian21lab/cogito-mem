"""Errors carry gRPC / Google AIP-193 code names and map to HTTP statuses."""

from __future__ import annotations

HTTP_STATUS = {
    "invalid_argument": 400,
    "failed_precondition": 400,
    "out_of_range": 400,
    "unauthenticated": 401,
    "permission_denied": 403,
    "not_found": 404,
    "already_exists": 409,
    "aborted": 409,
    "resource_exhausted": 429,
    "cancelled": 499,
    "internal": 500,
    "unknown": 500,
    "data_loss": 500,
    "unimplemented": 501,
    "unavailable": 503,
    "deadline_exceeded": 504,
}


class ApiError(Exception):
    """An error a caller can act on. ``code`` is an AIP-193 name in lower case."""

    def __init__(self, code: str, message: str):
        if code not in HTTP_STATUS:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.code]

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def invalid(message: str) -> ApiError:
    return ApiError("invalid_argument", message)
