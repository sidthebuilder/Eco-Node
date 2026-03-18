"""
econode – Domain Models
All typed Pydantic v2 objects that flow through every module.
No dict passing anywhere.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────────────

class Provider(str, Enum):
    AWS   = "aws"
    GCP   = "gcp"
    AZURE = "azure"
    ONPREM = "onprem"


class JobStatus(str, Enum):
    QUEUED        = "QUEUED"
    RUNNING       = "RUNNING"
    CHECKPOINTING = "CHECKPOINTING"
    MIGRATING     = "MIGRATING"
    DONE          = "DONE"
    FAILED        = "FAILED"


# ── Cloud Region ───────────────────────────────────────────────────────────────

class CloudRegion(BaseModel):
    """A specific provider + region tuple, with lat/lon for globe rendering."""
    id: str                        # e.g. "aws:us-east-1"
    provider: Provider
    region_code: str               # e.g. "us-east-1"
    display_name: str              # e.g. "AWS US East (N. Virginia)"
    lat: float
    lon: float
    zone: str                      # ElectricityMaps zone code, e.g. "US-MIDA-PJM"
    gpu_types: list[str] = Field(default_factory=list)  # e.g. ["p3.8xlarge"]

    @property
    def key(self) -> str:
        return self.id


# ── Snapshots ──────────────────────────────────────────────────────────────────

class CarbonSnapshot(BaseModel):
    """Point-in-time carbon intensity reading for a region."""
    region_id: str
    zone: str
    timestamp: datetime
    carbon_intensity: float        # gCO2eq/kWh
    renewable_pct: float           # 0‒100
    data_source: str = "electricitymaps"
    is_mock: bool = False


class PriceSnapshot(BaseModel):
    """Spot price for a specific GPU instance type in a region."""
    region_id: str
    instance_type: str
    timestamp: datetime
    spot_price_usd_hr: float       # USD per GPU-hour
    on_demand_usd_hr: float
    availability_score: float      # 0‒1 (1 = very available)
    is_mock: bool = False


class RegionSnapshot(BaseModel):
    """Combined view of a region at a point in time."""
    region: CloudRegion
    carbon: CarbonSnapshot
    price: PriceSnapshot
    composite_score: float = 0.0   # filled by optimizer


# ── Forecast ───────────────────────────────────────────────────────────────────

class ForecastPoint(BaseModel):
    """Single hour forecast value."""
    timestamp: datetime
    predicted_carbon: float        # gCO2eq/kWh
    predicted_price: float         # USD/hr
    carbon_lower: float            # 80% CI lower
    carbon_upper: float            # 80% CI upper
    price_lower: float
    price_upper: float


class Forecast(BaseModel):
    """24-hour ahead forecast for a region (SOAD scheduling horizon)."""
    region_id: str
    generated_at: datetime
    horizon_hours: int = 24
    points: list[ForecastPoint]
    model_version: str = "prophet-v1"


# ── Job ────────────────────────────────────────────────────────────────────────

class JobSpec(BaseModel):
    """User-submitted job specification."""
    name: str
    gpu_count: int = Field(ge=1, le=1024)
    gpu_type: str = "a100"
    duration_hours: float = Field(gt=0)
    deadline_hours: float = Field(gt=0)
    budget_usd: float = Field(gt=0)
    cost_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    carbon_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    interruptible: bool = True
    preferred_providers: list[Provider] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("carbon_weight")
    @classmethod
    def weights_sum_to_one(cls, v: float, info) -> float:
        cost_w = info.data.get("cost_weight", 0.6)
        if abs(cost_w + v - 1.0) > 1e-6:
            raise ValueError(
                f"cost_weight ({cost_w}) + carbon_weight ({v}) must equal 1.0"
            )
        return v


class Job(BaseModel):
    """Runtime job object with mutable state."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    spec: JobSpec
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_region_id: Optional[str] = None
    checkpoint_path: Optional[str] = None
    migration_count: int = 0
    total_cost_usd: float = 0.0
    total_carbon_kgco2: float = 0.0
    baseline_cost_usd: float = 0.0      # what on-demand would have cost
    baseline_carbon_kgco2: float = 0.0
    error: Optional[str] = None

    @property
    def savings_usd(self) -> float:
        return max(0.0, self.baseline_cost_usd - self.total_cost_usd)

    @property
    def carbon_avoided_kgco2(self) -> float:
        return max(0.0, self.baseline_carbon_kgco2 - self.total_carbon_kgco2)


# ── Optimization Decision ──────────────────────────────────────────────────────

class OptimizationDecision(BaseModel):
    """Output of the SOAD optimizer for a job at an evaluation tick."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    best_region_id: str
    best_start_offset_hours: float    # 0 = now, >0 = defer
    estimated_cost_usd: float
    estimated_carbon_kgco2: float
    savings_vs_baseline_pct: float
    carbon_reduction_pct: float
    ranked_alternatives: list[str]    # region_ids in order
    trigger: str = "scheduled"        # "scheduled" | "mid_run" | "deadline_pressure"
    jitter_seconds: int = 0           # thundering-herd mitigation offset
