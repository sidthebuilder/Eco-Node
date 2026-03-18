"""
econode – Multi-Objective SOAD Optimizer
Formalizes the scheduling problem as:
  Spatiotemporal Online Allocation with Deadline Constraints (SOAD)
  as defined in CarbonClipper (arXiv:2408.07831).

Given:
  - A job J with GPUs g, duration d, deadline T, cost/carbon weights (α, β)
  - Per-region, per-hour forecasts of carbon c(r,t) and price p(r,t)

Find:
  - Region r* and start time t* that minimise α·cost + β·carbon
  - Subject to: t* + d ≤ T (deadline), budget ≤ B

Thundering-herd mitigation (CarbonFlex):
  When multiple jobs defer to the same optimal window, randomised jitter
  is added proportional to job_id hash to spread load across ±jitter_window.
"""
from __future__ import annotations

import hashlib
import logging
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from econode.models import (
    CloudRegion,
    Forecast,
    ForecastPoint,
    Job,
    OptimizationDecision,
    RegionSnapshot,
)
from econode.regions import REGIONS

log = logging.getLogger(__name__)

JITTER_WINDOW_MINUTES = 30   # max ±30 min spread for thundering-herd mitigation
EPSILON = 1e-9               # avoid divide-by-zero

# Migration overhead model (c3lab-net migration-carbon-impact)
# Network transfer: ~0.1 kWh per GB, checkpoint ≈ 50GB per 8-GPU job → ~5 kWh
# At avg grid intensity ~300 gCO2/kWh → ~1.5 kg CO2 per migration event
# Roughly: 0.1875 kg CO2 per GPU migrated (8 GPU baseline)
MIGRATION_CARBON_KG_PER_GPU = 0.1875


class econodeOptimizer:
    """
    Stateless SOAD optimizer.
    Call `evaluate(job, forecasts, snapshots)` on every scheduler tick
    and whenever a mid-run migration check fires.
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    def evaluate(
        self,
        job: Job,
        forecasts: dict[str, Forecast],
        snapshots: dict[str, RegionSnapshot],
        trigger: str = "scheduled",
    ) -> OptimizationDecision:
        """
        Run SOAD optimisation for a single job.
        Returns the best decision with ranked alternatives.
        """
        now = datetime.now(timezone.utc)
        deadline_dt = (job.started_at or now) + timedelta(hours=job.spec.deadline_hours)
        remaining_hours = max(0.0, (deadline_dt - now).total_seconds() / 3600)

        if remaining_hours < job.spec.duration_hours:
            # Deadline pressure: force immediate start in best available region
            log.warning(
                "Job %s approaching deadline – forcing immediate placement", job.id
            )
            return self._deadline_forced(job, snapshots, now, trigger)

        candidates = self._score_all(
            job=job,
            forecasts=forecasts,
            snapshots=snapshots,
            now=now,
            deadline_dt=deadline_dt,
        )
        if not candidates:
            raise RuntimeError(f"No viable candidates for job {job.id}")

        best = candidates[0]
        alternatives = [c["region_id"] for c in candidates[1:5]]

        # Thundering-herd jitter (CarbonFlex)
        jitter = self._jitter_seconds(job.id) if best["start_offset_hours"] > 0 else 0

        # Baseline = running immediately in cheapest on-demand region
        baseline_cost, baseline_carbon = self._baseline(job, snapshots)

        # For mid-run migrations, add the carbon cost of the migration itself
        # (network checkpoint transfer + storage I/O) — c3lab-net migration-carbon-impact
        migration_carbon_overhead = 0.0
        if trigger == "mid_run" and job.current_region_id and job.current_region_id != best["region_id"]:
            migration_carbon_overhead = MIGRATION_CARBON_KG_PER_GPU * job.spec.gpu_count * 1000  # back to gCO2
            best["carbon"] = best["carbon"] + migration_carbon_overhead
            if migration_carbon_overhead > 0:
                log.debug(
                    "Migration overhead added: %.2f gCO2 for %d GPUs",
                    migration_carbon_overhead, job.spec.gpu_count,
                )

        savings_pct = max(0.0, (baseline_cost - best["cost"]) / (baseline_cost + EPSILON)) * 100
        carbon_pct  = max(0.0, (baseline_carbon - best["carbon"]) / (baseline_carbon + EPSILON)) * 100

        return OptimizationDecision(
            job_id=job.id,
            evaluated_at=now,
            best_region_id=best["region_id"],
            best_start_offset_hours=best["start_offset_hours"],
            estimated_cost_usd=round(best["cost"], 4),
            estimated_carbon_kgco2=round(best["carbon"] / 1000, 4),
            savings_vs_baseline_pct=round(savings_pct, 2),
            carbon_reduction_pct=round(carbon_pct, 2),
            ranked_alternatives=alternatives,
            trigger=trigger,
            jitter_seconds=jitter,
        )

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_all(
        self,
        job: Job,
        forecasts: dict[str, Forecast],
        snapshots: dict[str, RegionSnapshot],
        now: datetime,
        deadline_dt: datetime,
    ) -> list[dict]:
        """
        For each region × start_offset combination, compute the SOAD cost:
          score = α · normalised_cost + β · normalised_carbon
        Lower is better. Returns list sorted ascending by score.
        """
        spec = job.spec
        α = spec.cost_weight
        β = spec.carbon_weight
        duration = spec.duration_hours

        # Candidates: try starting now, +2h, +4h, ... up to deadline
        max_offset = max(0, int((deadline_dt - now).total_seconds() / 3600) - int(duration))
        offsets = list(range(0, min(max_offset + 1, 25), 2)) or [0]

        raw_candidates: list[dict] = []
        for region_id, snap in snapshots.items():
            forecast = forecasts.get(region_id)
            region = REGIONS.get(region_id)
            if not region:
                continue
            # Filter by preferred providers if specified
            if spec.preferred_providers and region.provider not in spec.preferred_providers:
                continue

            for offset_h in offsets:
                cost, carbon = self._window_cost_carbon(
                    snap, forecast, offset_h, duration,
                    gpu_count=spec.gpu_count,
                )
                # Hard constraints
                if cost > spec.budget_usd:
                    continue
                raw_candidates.append({
                    "region_id": region_id,
                    "start_offset_hours": float(offset_h),
                    "cost": cost,
                    "carbon": carbon,
                })

        if not raw_candidates:
            # Relax budget constraint (add all)
            raw_candidates = [
                {
                    "region_id": rid,
                    "start_offset_hours": 0.0,
                    "cost": self._instant_cost(snap, job.spec.gpu_count, job.spec.duration_hours),
                    "carbon": self._instant_carbon(snap, job.spec.gpu_count, job.spec.duration_hours),
                }
                for rid, snap in snapshots.items()
                if REGIONS.get(rid)
            ]

        # Normalise across candidates for Pareto scoring
        costs   = [c["cost"]   for c in raw_candidates]
        carbons = [c["carbon"] for c in raw_candidates]
        c_min, c_max = min(costs),   max(costs)   + EPSILON
        k_min, k_max = min(carbons), max(carbons) + EPSILON

        for cand in raw_candidates:
            norm_c = (cand["cost"]   - c_min) / (c_max - c_min)
            norm_k = (cand["carbon"] - k_min) / (k_max - k_min)
            cand["score"] = α * norm_c + β * norm_k

        return sorted(raw_candidates, key=lambda x: x["score"])

    def _window_cost_carbon(
        self,
        snap: RegionSnapshot,
        forecast: Optional["Forecast"],
        offset_h: int,
        duration: float,
        gpu_count: int,
    ) -> tuple[float, float]:
        """Integrate cost & carbon over the job's execution window."""
        if forecast and len(forecast.points) > offset_h:
            window_pts: list[ForecastPoint] = forecast.points[
                offset_h : offset_h + math.ceil(duration)
            ]
            if window_pts:
                avg_price  = sum(p.predicted_price  for p in window_pts) / len(window_pts)
                avg_carbon = sum(p.predicted_carbon for p in window_pts) / len(window_pts)
                cost   = avg_price  * gpu_count * duration
                # carbon: gCO2eq/kWh × power(kW) × hours → gCO2eq → /1000 for kg
                # Assume ~300W per GPU (A100-class)
                carbon = avg_carbon * (0.3 * gpu_count) * duration
                return cost, carbon

        return (
            self._instant_cost(snap, gpu_count, duration),
            self._instant_carbon(snap, gpu_count, duration),
        )

    @staticmethod
    def _instant_cost(snap: RegionSnapshot, gpu_count: int, duration: float) -> float:
        return snap.price.spot_price_usd_hr * gpu_count * duration

    @staticmethod
    def _instant_carbon(snap: RegionSnapshot, gpu_count: int, duration: float) -> float:
        return snap.carbon.carbon_intensity * (0.3 * gpu_count) * duration

    def _baseline(
        self,
        job: Job,
        snapshots: dict[str, RegionSnapshot],
    ) -> tuple[float, float]:
        """On-demand cost + no-optimisation carbon (worst-region benchmark)."""
        max_price  = max((s.price.on_demand_usd_hr for s in snapshots.values()), default=3.0)
        max_carbon = max((s.carbon.carbon_intensity for s in snapshots.values()), default=500.0)
        cost   = max_price  * job.spec.gpu_count * job.spec.duration_hours
        carbon = max_carbon * (0.3 * job.spec.gpu_count) * job.spec.duration_hours
        return cost, carbon

    def _deadline_forced(
        self,
        job: Job,
        snapshots: dict[str, RegionSnapshot],
        now: datetime,
        trigger: str,
    ) -> OptimizationDecision:
        α, β = job.spec.cost_weight, job.spec.carbon_weight
        best_rid, best_score = "", math.inf
        for rid, snap in snapshots.items():
            if not REGIONS.get(rid):
                continue
            norm_cost   = snap.price.spot_price_usd_hr / 5.0
            norm_carbon = snap.carbon.carbon_intensity / 900.0
            score = α * norm_cost + β * norm_carbon
            if score < best_score:
                best_score, best_rid = score, rid
        snap = snapshots[best_rid]
        cost   = self._instant_cost(snap, job.spec.gpu_count, job.spec.duration_hours)
        carbon = self._instant_carbon(snap, job.spec.gpu_count, job.spec.duration_hours)
        baseline_cost, baseline_carbon = self._baseline(job, snapshots)
        return OptimizationDecision(
            job_id=job.id,
            evaluated_at=now,
            best_region_id=best_rid,
            best_start_offset_hours=0.0,
            estimated_cost_usd=round(cost, 4),
            estimated_carbon_kgco2=round(carbon / 1000, 4),
            savings_vs_baseline_pct=round(max(0, (baseline_cost - cost) / (baseline_cost + EPSILON)) * 100, 2),
            carbon_reduction_pct=round(max(0, (baseline_carbon - carbon) / (baseline_carbon + EPSILON)) * 100, 2),
            ranked_alternatives=[],
            trigger=trigger,
            jitter_seconds=0,
        )

    @staticmethod
    def _jitter_seconds(job_id: str) -> int:
        """Deterministic jitter per job_id to spread thundering-herd deferrals."""
        h = int(hashlib.md5(job_id.encode()).hexdigest()[:8], 16)
        rng = random.Random(h)
        return rng.randint(-JITTER_WINDOW_MINUTES * 60, JITTER_WINDOW_MINUTES * 60)
