"""
econode – FastAPI Control Plane
Endpoints:
  POST /jobs             – Submit a new job
  GET  /jobs             – List all jobs
  GET  /jobs/{id}        – Job status + live savings
  GET  /regions          – Live carbon + price snapshot for all regions
  GET  /forecast/{id}    – 24h forecast for a region
  GET  /decisions        – Last N optimizer decisions
  GET  /health           – Liveness probe
  GET  /metrics          – Aggregate savings / carbon avoided
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
import json
import os

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from econode.carbon import CarbonClient
from econode.config import get_settings
from econode.executor import ExecutorRegistry
from econode.models import Job, JobSpec, JobStatus
from econode.optimizer import econodeOptimizer
from econode.predictor import econodePredictor
from econode.pricing import PricingClient
from econode.scheduler import econodeScheduler
from econode.audit import audit_engine

log = logging.getLogger(__name__)
_cfg = get_settings()

# ── Global singletons ─────────────────────────────────────────────────────────

_carbon    = CarbonClient()
_pricing   = PricingClient()
_predictor = econodePredictor()
_optimizer = econodeOptimizer()
_registry  = ExecutorRegistry()
_scheduler = econodeScheduler(
    carbon=_carbon,
    pricing=_pricing,
    predictor=_predictor,
    optimizer=_optimizer,
    registry=_registry,
)

_jobs: dict[str, Job] = {}    # in-process store; swap for Redis in production
_JOBS_FILE = "jobs.json"

def _load_jobs() -> None:
    """Load jobs from disk on startup."""
    global _jobs
    if os.path.exists(_JOBS_FILE):
        try:
            with open(_JOBS_FILE, 'r') as f:
                data = json.load(f)
                for job_id, job_data in data.items():
                    _jobs[job_id] = Job(**job_data)
            log.info(f"Loaded {len(_jobs)} jobs from disk")
        except Exception as e:
            log.error(f"Failed to load jobs: {e}")

def _save_jobs() -> None:
    """Persist jobs to disk."""
    try:
        with open(_JOBS_FILE, 'w') as f:
            json.dump({jid: job.model_dump() for jid, job in _jobs.items()}, f, indent=2, default=str)
    except Exception as e:
        log.error(f"Failed to save jobs: {e}")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=_cfg.econode_log_level)
    _load_jobs()
    _scheduler.start()
    log.info("econode API started | demo_mode=%s", _cfg.demo_mode)
    yield
    _scheduler.stop()
    _save_jobs()
    await _carbon.close()
    log.info("econode API shut down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="econode – Carbon-Cost Arbitrage Engine",
    description=(
        "Autonomous routing of AI workloads to the globally optimal cloud "
        "region/time based on real-time carbon intensity and spot pricing.\n\n"
        "**Market gap**: only 2 of 28 published studies combine spatial AND "
        "temporal workload shifting (MDPI 2025). econode is the first "
        "production-ready unified engine."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": _cfg.demo_mode,
        "regions_loaded": len(_scheduler.snapshots),
        "active_jobs": sum(
            1 for j in _jobs.values() if j.status == JobStatus.RUNNING
        ),
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
    }


@app.post("/jobs", response_model=dict, status_code=202)
async def submit_job(spec: JobSpec) -> dict[str, Any]:
    job = Job(spec=spec)
    _jobs[job.id] = job
    _save_jobs()  # Persist immediately
    await _scheduler.submit_job(job)
    return {
        "job_id":  job.id,
        "status":  job.status,
        "message": "Job accepted – optimizer will place it within seconds",
    }


@app.get("/jobs")
async def list_jobs() -> list[dict[str, Any]]:
    return [_job_view(j) for j in _jobs.values()]


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail=f"Job {job_id} not found")
    exec_ = _registry.get(job_id)
    return {
        **_job_view(job),
        "progress_pct": round((exec_.progress if exec_ else 0) * 100, 1),
    }


@app.get("/regions")
async def regions_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "region_id":        snap.region.id,
            "display_name":     snap.region.display_name,
            "provider":         snap.region.provider,
            "lat":              snap.region.lat,
            "lon":              snap.region.lon,
            "carbon_intensity": snap.carbon.carbon_intensity,
            "renewable_pct":    snap.carbon.renewable_pct,
            "spot_price_usd_hr":snap.price.spot_price_usd_hr,
            "on_demand_usd_hr": snap.price.on_demand_usd_hr,
            "availability":     snap.price.availability_score,
            "is_mock":          snap.carbon.is_mock,
            "composite_score":  snap.composite_score,
            "ts":               snap.carbon.timestamp.isoformat(),
        }
        for snap in _scheduler.snapshots.values()
    ]


@app.get("/forecast/{region_id:path}")
async def forecast_region(region_id: str) -> dict[str, Any]:
    fc = _predictor.forecast(region_id)
    return {
        "region_id":    fc.region_id,
        "generated_at": fc.generated_at.isoformat(),
        "model":        fc.model_version,
        "points": [
            {
                "ts":              p.timestamp.isoformat(),
                "carbon":          p.predicted_carbon,
                "carbon_lo":       p.carbon_lower,
                "carbon_hi":       p.carbon_upper,
                "price":           p.predicted_price,
                "price_lo":        p.price_lower,
                "price_hi":        p.price_upper,
            }
            for p in fc.points
        ],
    }


@app.get("/decisions")
async def decisions(limit: int = Query(default=50, le=200)) -> list[dict[str, Any]]:
    recent = _scheduler.decisions[-limit:][::-1]
    return [
        {
            "id":                  d.id,
            "job_id":              d.job_id,
            "evaluated_at":        d.evaluated_at.isoformat(),
            "best_region_id":      d.best_region_id,
            "start_offset_hours":  d.best_start_offset_hours,
            "cost_usd":            d.estimated_cost_usd,
            "carbon_kgco2":        d.estimated_carbon_kgco2,
            "savings_pct":         d.savings_vs_baseline_pct,
            "carbon_reduction_pct":d.carbon_reduction_pct,
            "trigger":             d.trigger,
            "jitter_s":            d.jitter_seconds,
            "alternatives":        d.ranked_alternatives,
        }
        for d in recent
    ]


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    all_jobs = list(_jobs.values())
    return {
        "total_jobs":          len(all_jobs),
        "completed_jobs":      sum(1 for j in all_jobs if j.status == JobStatus.DONE),
        "total_savings_usd":   round(sum(j.savings_usd for j in all_jobs), 2),
        "total_carbon_avoided_kgco2": round(
            sum(j.carbon_avoided_kgco2 for j in all_jobs), 3
        ),
        "total_migrations":    sum(j.migration_count for j in all_jobs),
        "optimizer_decisions": len(_scheduler.decisions),
    }

@app.get("/audit/records")
async def get_audit_records() -> list[dict[str, Any]]:
    return audit_engine.get_all_records()

@app.get("/audit/summary")
async def get_audit_summary() -> dict[str, Any]:
    return audit_engine.get_summary()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _job_view(j: Job) -> dict[str, Any]:
    return {
        "id":                j.id,
        "name":              j.spec.name,
        "status":            j.status,
        "gpu_count":         j.spec.gpu_count,
        "duration_hours":    j.spec.duration_hours,
        "current_region":    j.current_region_id,
        "migration_count":   j.migration_count,
        "total_cost_usd":    round(j.total_cost_usd, 4),
        "savings_usd":       round(j.savings_usd, 4),
        "carbon_kgco2":      round(j.total_carbon_kgco2, 4),
        "carbon_avoided_kgco2": round(j.carbon_avoided_kgco2, 4),
        "created_at":        j.created_at.isoformat(),
        "started_at":        j.started_at.isoformat() if j.started_at else None,
    }


# ── CLI entrypoint ─────────────────────────────────────────────────────────────

def run() -> None:
    uvicorn.run(
        "econode.api.main:app",
        host=_cfg.api_host,
        port=_cfg.api_port,
        reload=False,
        log_level=_cfg.econode_log_level.lower(),
    )


if __name__ == "__main__":
    run()
