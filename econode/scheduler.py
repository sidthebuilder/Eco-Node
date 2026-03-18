"""
econode – APScheduler Engine
Central event loop that wires all components together:
  1. Every POLL_INTERVAL: fetch carbon + price → ingest into predictor
  2. Every POLL_INTERVAL: run migration scanner on RUNNING jobs
  3. Every 1h: generate fresh forecasts for all regions
  4. Per-job: deadline watchdog that triggers forced migration on proximity
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from econode.config import get_settings
from econode.models import JobStatus, RegionSnapshot
from econode.regions import REGIONS

if TYPE_CHECKING:
    from econode.carbon import CarbonClient
    from econode.executor import ExecutorRegistry
    from econode.optimizer import econodeOptimizer
    from econode.predictor import econodePredictor
    from econode.pricing import PricingClient

log = logging.getLogger(__name__)
_cfg = get_settings()


class econodeScheduler:
    """
    Central coordinator. Owns APScheduler and coordinates:
    carbon client → predictor → optimizer → executor pipeline.
    """

    def __init__(
        self,
        carbon: "CarbonClient",
        pricing: "PricingClient",
        predictor: "econodePredictor",
        optimizer: "econodeOptimizer",
        registry: "ExecutorRegistry",
    ) -> None:
        self._carbon    = carbon
        self._pricing   = pricing
        self._predictor = predictor
        self._optimizer = optimizer
        self._registry  = registry
        self._scheduler = AsyncIOScheduler()

        # Shared in-memory state (written by poll, read by API + dashboard)
        self.snapshots: dict[str, RegionSnapshot] = {}
        self.decisions: list = []   # OptimizationDecision history (last 200)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        poll_secs = _cfg.econode_poll_interval
        self._scheduler.add_job(
            self._poll,
            IntervalTrigger(seconds=poll_secs),
            id="econode_poll",
            max_instances=1,
            replace_existing=True,
            next_run_time=datetime.now(),
        )
        self._scheduler.add_job(
            self._migration_scan,
            IntervalTrigger(seconds=max(60, poll_secs)),
            id="econode_migration_scan",
            max_instances=1,
            replace_existing=True,
        )
        self._scheduler.start()
        log.info("econodeScheduler started (poll=%ds)", poll_secs)

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        log.info("econodeScheduler stopped")

    # ── Jobs ──────────────────────────────────────────────────────────────────

    async def submit_job(self, job) -> None:  # job: Job
        """Evaluate, then immediately start or schedule the job."""
        from econode.executor import JobExecutor

        if not self.snapshots:
            # First run – seed snapshots synchronously
            await self._poll()

        forecasts = self._predictor.forecast_all(list(self.snapshots.keys()))
        try:
            decision = self._optimizer.evaluate(
                job, forecasts, self.snapshots, trigger="initial"
            )
        except Exception as exc:
            log.error("Optimization failed for job %s: %s", job.id, exc)
            return

        self._record_decision(decision)

        best_snap = self.snapshots.get(decision.best_region_id)
        if not best_snap:
            log.error("Snapshot missing for region %s", decision.best_region_id)
            return

        exec_ = JobExecutor(job)
        self._registry.register(exec_)

        if decision.best_start_offset_hours > 0:
            # Temporal arbitrage: defer start
            delay = decision.best_start_offset_hours * 3600 + decision.jitter_seconds
            log.info(
                "Job %s deferred by %.1fh (jitter=%ds) to %s",
                job.id[:8], decision.best_start_offset_hours,
                decision.jitter_seconds, decision.best_region_id,
            )
            self._scheduler.add_job(
                exec_.start,
                "date",
                run_date=datetime.now(timezone.utc).__class__.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() + delay, tz=timezone.utc
                ),
                args=[decision.best_region_id, best_snap],
                id=f"job-start-{job.id}",
            )
        else:
            await exec_.start(decision.best_region_id, best_snap)

        # Set baselines for savings tracking
        baseline_cost   = best_snap.price.on_demand_usd_hr * job.spec.gpu_count * job.spec.duration_hours
        baseline_carbon = best_snap.carbon.carbon_intensity * (0.3 * job.spec.gpu_count) * job.spec.duration_hours
        job.baseline_cost_usd      = baseline_cost
        job.baseline_carbon_kgco2  = baseline_carbon / 1000

    # ── Internal ticks ────────────────────────────────────────────────────────

    async def _poll(self) -> None:
        """Fetch all carbon + price data, update predictor buffers."""
        try:
            carbon_data, price_data = await asyncio.gather(
                self._carbon.latest_all(),
                self._pricing.latest_all(),
                return_exceptions=False,
            )
        except Exception as exc:
            log.error("Poll failed: %s", exc)
            return

        new_snapshots: dict[str, RegionSnapshot] = {}
        for region_id, region in REGIONS.items():
            # carbon_data is now keyed by region_id (fixed in carbon.py)
            carbon_snap = carbon_data.get(region_id)
            price_snap  = price_data.get(region_id)
            if carbon_snap and price_snap:
                self._predictor.ingest(carbon_snap, price_snap)
                new_snapshots[region_id] = RegionSnapshot(
                    region=region,
                    carbon=carbon_snap,
                    price=price_snap,
                )
        self.snapshots = new_snapshots
        log.debug("Poll complete – %d regions updated", len(new_snapshots))

    async def _migration_scan(self) -> None:
        """Check every running job for a mid-run migration opportunity."""
        if not self.snapshots:
            return
        forecasts = self._predictor.forecast_all(list(self.snapshots.keys()))
        for executor in self._registry.all_running():
            job = executor.job
            if job.status != JobStatus.RUNNING:
                continue
            try:
                decision = self._optimizer.evaluate(
                    job, forecasts, self.snapshots, trigger="mid_run"
                )
            except Exception as exc:
                log.warning("Mid-run optimizer error for %s: %s", job.id[:8], exc)
                continue

            if (
                decision.best_region_id != job.current_region_id
                and decision.savings_vs_baseline_pct / 100 >= _cfg.econode_migration_threshold
            ):
                log.info(
                    "Migration opportunity for job %s → %s (savings=%.1f%%)",
                    job.id[:8], decision.best_region_id, decision.savings_vs_baseline_pct,
                )
                new_snap = self.snapshots.get(decision.best_region_id)
                if new_snap:
                    self._record_decision(decision)
                    await executor.migrate(decision, new_snap)

    def _record_decision(self, decision) -> None:
        self.decisions.append(decision)
        if len(self.decisions) > 200:
            self.decisions = self.decisions[-200:]


# ── Standalone entrypoint ─────────────────────────────────────────────────────

def run_standalone() -> None:
    """CLI entrypoint: `econode-sched`"""
    import signal
    from econode.carbon import CarbonClient
    from econode.executor import ExecutorRegistry
    from econode.optimizer import econodeOptimizer
    from econode.predictor import econodePredictor
    from econode.pricing import PricingClient

    logging.basicConfig(level=_cfg.econode_log_level)
    scheduler = econodeScheduler(
        carbon=CarbonClient(),
        pricing=PricingClient(),
        predictor=econodePredictor(),
        optimizer=econodeOptimizer(),
        registry=ExecutorRegistry(),
    )

    loop = asyncio.get_event_loop()
    scheduler.start()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        scheduler.stop()
