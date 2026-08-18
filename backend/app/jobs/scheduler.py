"""Scheduler process.

A single asyncio loop rather than Celery beat: the workload is a handful of
short database sweeps, and one less moving part in production is worth more than
distributed scheduling at this scale. Every tick is guarded so a failing job
never kills the loop, and jobs skip themselves if a previous run is still going.

Run with ``python -m app.jobs.scheduler``.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.db import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.jobs.tasks import run_job

log = get_logger(__name__)


@dataclass(slots=True)
class ScheduledJob:
    name: str
    interval_seconds: int
    # Optional wall-clock gate, e.g. run only at 08:00 UTC on Mondays.
    hour: int | None = None
    weekday: int | None = None
    last_run: datetime | None = None
    running: bool = False

    def is_due(self, now: datetime) -> bool:
        if self.running:
            return False
        if self.hour is not None and now.hour != self.hour:
            return False
        if self.weekday is not None and now.isoweekday() != self.weekday:
            return False
        if self.last_run is None:
            return True
        return (now - self.last_run).total_seconds() >= self.interval_seconds


SCHEDULE: list[ScheduledJob] = [
    ScheduledJob("medication_reminders", 60),
    ScheduledJob("reminder_calls", 60),
    ScheduledJob("missed_doses", 900),
    ScheduledJob("dose_horizon", 3600),
    ScheduledJob("expire_consultations", 600),
    ScheduledJob("expire_subscriptions", 3600, hour=7),
    ScheduledJob("weekly_reports", 86_400, hour=8, weekday=1),
    ScheduledJob("cleanup_otp", 86_400, hour=3),
]


async def _run(job: ScheduledJob) -> None:
    job.running = True
    started = datetime.now(UTC)
    try:
        result = await run_job(job.name)
        if result:
            log.info(
                "scheduler.job_done",
                job=job.name,
                result=result,
                seconds=round((datetime.now(UTC) - started).total_seconds(), 2),
            )
    except Exception as exc:  # noqa: BLE001 - the loop must survive any job
        log.error("scheduler.job_failed", job=job.name, error=str(exc))
    finally:
        job.running = False
        job.last_run = datetime.now(UTC)


async def run_forever(tick_seconds: int = 20) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    log.info("scheduler.started", jobs=[job.name for job in SCHEDULE])
    tasks: set[asyncio.Task] = set()
    try:
        while not stop.is_set():
            now = datetime.now(UTC)
            for job in SCHEDULE:
                if job.is_due(now):
                    task = asyncio.create_task(_run(job), name=f"job:{job.name}")
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=tick_seconds)
    finally:
        log.info("scheduler.stopping", pending=len(tasks))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await dispose_engine()
        log.info("scheduler.stopped")


def main() -> None:
    configure_logging()
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
