"""Validated, dependency-free runtime configuration."""
import os
from dataclasses import dataclass


def integer(name, default, minimum, maximum):
    value = int(os.environ.get(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return value


@dataclass(frozen=True)
class Settings:
    port: int = 8000
    workers: int = 4
    max_pending: int = 32
    max_history: int = 1000
    request_timeout: int = 10
    stage_delay: float = .65

    @classmethod
    def from_env(cls):
        return cls(
            port=integer('AICRAWL_PORT', 8000, 1, 65535),
            workers=integer('AICRAWL_WORKERS', 4, 1, 32),
            max_pending=integer('AICRAWL_MAX_PENDING', 32, 1, 1000),
            max_history=integer('AICRAWL_MAX_HISTORY', 1000, 10, 100000),
            request_timeout=integer('AICRAWL_REQUEST_TIMEOUT', 10, 1, 120),
        )
