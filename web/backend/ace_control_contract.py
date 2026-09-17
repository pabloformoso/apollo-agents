"""Shared wire contract for Apollo and its optional host-side ACE supervisor."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ServiceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["stopped", "starting", "running", "stopping", "failed", "unresponsive", "unknown"]
    ready: bool = False
    loaded: bool = False
    queued: int | None = Field(default=None, ge=0)
    running: int | None = Field(default=None, ge=0)
    reason: str | None = None


def queue_counts(stats: dict) -> tuple[int, int] | None:
    """Accept the real ACE schema and the older flat schema; fail closed."""
    jobs = stats.get("jobs")
    if isinstance(jobs, dict):
        queued, running = jobs.get("queued"), jobs.get("running")
        size = stats.get("queue_size")
        if type(size) is not int or size < 0:
            return None
    else:
        queued, running = stats.get("queued"), stats.get("running")
        size = 0
    if any(type(v) is not int or v < 0 for v in (queued, running)):
        return None
    return max(queued, size), running
