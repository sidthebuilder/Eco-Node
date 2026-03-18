"""
econode – Job Executor
State machine: QUEUED → RUNNING → CHECKPOINTING → MIGRATING → DONE | FAILED
Handles live checkpointing with aiofiles and triggers migration when the
optimizer finds ≥MIGRATION_THRESHOLD improvement mid-run.
"""
from __future__ import annotations

import asyncio
import logging
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles

from econode.config import get_settings
from econode.models import Job, JobStatus, OptimizationDecision, RegionSnapshot
from econode.audit import audit_engine

log = logging.getLogger(__name__)
_cfg = get_settings()
CHECKPOINT_DIR = Path("checkpoints")


class JobExecutor:
    """
    Manages the full lifecycle of a single Job.
    In demo mode: simulates GPU work with asyncio.sleep + progress tracking.
    In live mode: delegates to cloud SDK launch calls.
    """

    def __init__(self, job: Job) -> None:
        self.job = job
        self._progress: float = 0.0        # 0.0 – 1.0
        self._task: Optional[asyncio.Task] = None
        self._abort_event = asyncio.Event()
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self, region_id: str, snapshot: RegionSnapshot) -> None:
        """Launch the job in region_id."""
        self.job.status = JobStatus.RUNNING
        self.job.started_at = datetime.now(timezone.utc)
        self.job.current_region_id = region_id
        self._abort_event.clear()
        log.info("Job %s starting in region=%s", self.job.id[:8], region_id)
        self._task = asyncio.create_task(
            self._run_loop(snapshot), name=f"job-{self.job.id[:8]}"
        )

    async def checkpoint(self) -> Path:
        """Snapshot current progress to disk for migration."""
        self.job.status = JobStatus.CHECKPOINTING
        path = CHECKPOINT_DIR / f"{self.job.id}.ckpt"
        state = {
            "job_id":   self.job.id,
            "progress": self._progress,
            "ts":       time.time(),
        }
        async with aiofiles.open(path, "wb") as f:
            await f.write(pickle.dumps(state))
        self.job.checkpoint_path = str(path)
        log.info("Checkpoint saved for job %s (%.1f%%)", self.job.id[:8], self._progress * 100)
        return path

    async def migrate(self, decision: OptimizationDecision, snapshot: RegionSnapshot) -> None:
        """Checkpoint then restart in the new optimal region."""
        await self.checkpoint()
        # Cancel existing work loop
        if self._task and not self._task.done():
            self._abort_event.set()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        self.job.status = JobStatus.MIGRATING
        self.job.migration_count += 1
        old_region = self.job.current_region_id
        new_region = decision.best_region_id
        log.info(
            "Migrating job %s: %s → %s (savings=%.1f%%, CO₂↓%.1f%%)",
            self.job.id[:8], old_region, new_region,
            decision.savings_vs_baseline_pct, decision.carbon_reduction_pct,
        )
        await asyncio.sleep(2)  # simulate checkpoint transfer latency
        await self.start(new_region, snapshot)

    async def stop(self) -> None:
        """Gracefully terminate the job."""
        self._abort_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
        self.job.status = JobStatus.DONE
        self.job.completed_at = datetime.now(timezone.utc)

    @property
    def progress(self) -> float:
        return self._progress

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run_loop(self, snapshot: RegionSnapshot) -> None:
        """
        Simulates GPU computation ticking every 10s.
        In live mode this would be replaced by polling the cloud SDK job status.
        Accumulates cost and carbon incrementally.
        """
        duration_sec = self.job.spec.duration_hours * 3600
        tick = 10.0          # seconds per simulated tick
        elapsed = self._progress * duration_sec  # resume from checkpoint

        price_hr   = snapshot.price.spot_price_usd_hr
        carbon_gkwh = snapshot.carbon.carbon_intensity
        gpu_count  = self.job.spec.gpu_count
        gpu_power_kw = 0.3 * gpu_count  # 300W per GPU (A100-class)

        try:
            while elapsed < duration_sec and not self._abort_event.is_set():
                await asyncio.sleep(min(tick, duration_sec - elapsed))
                elapsed += tick
                self._progress = min(1.0, elapsed / duration_sec)

                # Incremental cost / carbon accrual
                tick_hrs = tick / 3600
                self.job.total_cost_usd    += price_hr   * gpu_count  * tick_hrs
                self.job.total_carbon_kgco2 += (carbon_gkwh * gpu_power_kw * tick_hrs) / 1000

            if not self._abort_event.is_set():
                self.job.status = JobStatus.DONE
                self.job.completed_at = datetime.now(timezone.utc)
                log.info("Job %s complete | cost=$%.2f | carbon=%.3fkg CO₂",
                         self.job.id[:8], self.job.total_cost_usd, self.job.total_carbon_kgco2)
                         
                # [AUDIT] Trigger post-execution sustainability audit
                baseline_metrics = {
                    "cost": self.job.savings_usd * 2, # Fake baseline for audit
                    "carbon": self.job.carbon_avoided_kgco2 * 2
                }
                audit_engine.profile_and_audit(self.job, baseline_metrics)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.job.status = JobStatus.FAILED
            self.job.error = str(exc)
            log.error("Job %s failed: %s", self.job.id[:8], exc)


class ExecutorRegistry:
    """Singleton registry mapping job_id → JobExecutor."""

    def __init__(self) -> None:
        self._executors: dict[str, JobExecutor] = {}

    def register(self, executor: JobExecutor) -> None:
        self._executors[executor.job.id] = executor

    def get(self, job_id: str) -> Optional[JobExecutor]:
        return self._executors.get(job_id)

    def all_running(self) -> list[JobExecutor]:
        return [
            e for e in self._executors.values()
            if e.job.status == JobStatus.RUNNING
        ]

    def remove(self, job_id: str) -> None:
        self._executors.pop(job_id, None)
