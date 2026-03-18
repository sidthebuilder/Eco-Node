"""
econode – Unit Tests
Covers: models validation, mock carbon/price generation, optimizer SOAD scoring,
and thundering-herd jitter uniqueness.
No real cloud credentials needed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from econode.models import (
    CarbonSnapshot, CloudRegion, Job, JobSpec, OptimizationDecision, Provider
)
from econode.regions import REGIONS


# ── Model validation ──────────────────────────────────────────────────────────

def test_job_spec_weights_must_sum_to_one():
    """cost_weight + carbon_weight must equal 1.0"""
    with pytest.raises(Exception):
        JobSpec(
            name="bad", gpu_count=4, duration_hours=2,
            deadline_hours=8, budget_usd=100,
            cost_weight=0.6, carbon_weight=0.6,   # sums to 1.2
        )


def test_job_spec_valid():
    spec = JobSpec(
        name="llama3-run", gpu_count=8, duration_hours=4,
        deadline_hours=24, budget_usd=500,
        cost_weight=0.7, carbon_weight=0.3,
    )
    assert spec.cost_weight + spec.carbon_weight == pytest.approx(1.0)


def test_job_savings_property():
    spec = JobSpec(name="t", gpu_count=1, duration_hours=1,
                   deadline_hours=4, budget_usd=50,
                   cost_weight=0.5, carbon_weight=0.5)
    job = Job(spec=spec)
    job.baseline_cost_usd = 10.0
    job.total_cost_usd = 4.0
    assert job.savings_usd == pytest.approx(6.0)
    job.total_cost_usd = 15.0   # over-spend shouldn't give negative savings
    assert job.savings_usd == 0.0


# ── Region registry ───────────────────────────────────────────────────────────

def test_regions_loaded():
    assert len(REGIONS) >= 12


def test_regions_have_coords():
    for rid, region in REGIONS.items():
        assert -90 <= region.lat <= 90, f"{rid} has invalid lat"
        assert -180 <= region.lon <= 180, f"{rid} has invalid lon"


def test_regions_have_zones():
    for rid, region in REGIONS.items():
        assert region.zone, f"{rid} missing zone"


# ── Mock carbon client ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_carbon_mock_returns_snapshots():
    from econode.carbon import CarbonClient
    client = CarbonClient()   # will be mock (no API key in test env)
    snap = await client.latest("US-MIDA-PJM")
    assert snap.carbon_intensity > 0
    assert 0 <= snap.renewable_pct <= 100
    assert snap.is_mock
    await client.close()


@pytest.mark.asyncio
async def test_carbon_mock_all_regions():
    from econode.carbon import CarbonClient
    client = CarbonClient()
    snaps = await client.latest_all()
    assert len(snaps) == len(REGIONS)
    await client.close()


@pytest.mark.asyncio
async def test_carbon_forecast_length():
    from econode.carbon import CarbonClient
    client = CarbonClient()
    fc = await client.forecast("SE", hours=24)
    assert len(fc) == 24
    await client.close()


# ── Mock pricing client ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pricing_mock_all_regions():
    from econode.pricing import PricingClient
    client = PricingClient()
    prices = await client.latest_all()
    assert len(prices) == len(REGIONS)
    for rid, snap in prices.items():
        assert snap.spot_price_usd_hr > 0
        assert snap.on_demand_usd_hr >= snap.spot_price_usd_hr


# ── Optimizer ─────────────────────────────────────────────────────────────────

def _make_snapshot(region: CloudRegion, carbon: float, price: float):
    from econode.models import CarbonSnapshot, PriceSnapshot, RegionSnapshot
    now = datetime.now(timezone.utc)
    return RegionSnapshot(
        region=region,
        carbon=CarbonSnapshot(
            region_id=region.id, zone=region.zone, timestamp=now,
            carbon_intensity=carbon, renewable_pct=80, is_mock=True
        ),
        price=PriceSnapshot(
            region_id=region.id, instance_type="test", timestamp=now,
            spot_price_usd_hr=price, on_demand_usd_hr=price * 3,
            availability_score=0.9, is_mock=True
        ),
    )


def test_optimizer_picks_cleanest_region():
    from econode.optimizer import econodeOptimizer
    regions_list = list(REGIONS.values())[:4]
    # Give us one obviously clean, cheap region
    snapshots = {
        r.id: _make_snapshot(r, carbon=100 + i * 200, price=1.0 + i * 0.5)
        for i, r in enumerate(regions_list)
    }
    spec = JobSpec(name="test", gpu_count=4, duration_hours=2,
                   deadline_hours=12, budget_usd=500,
                   cost_weight=0.3, carbon_weight=0.7)  # carbon-biased
    job = Job(spec=spec)
    optimizer = econodeOptimizer()
    decision = optimizer.evaluate(job, forecasts={}, snapshots=snapshots)
    # Should pick the first region (lowest carbon=100)
    assert decision.best_region_id == regions_list[0].id
    assert decision.savings_vs_baseline_pct >= 0
    assert decision.carbon_reduction_pct >= 0


def test_optimizer_thundering_herd_jitter_unique():
    """Different job IDs must get different jitter values."""
    from econode.optimizer import econodeOptimizer
    jitters = {econodeOptimizer._jitter_seconds(f"job-{i}") for i in range(20)}
    # With 20 random jobs across ±1800s window, expect at least 15 unique values
    assert len(jitters) >= 15


def test_optimizer_budget_exceeded_falls_back():
    """When budget is extremely tight, optimizer should still return a decision."""
    from econode.optimizer import econodeOptimizer
    regions_list = list(REGIONS.values())[:3]
    snapshots = {r.id: _make_snapshot(r, 300, 3.0) for r in regions_list}
    spec = JobSpec(name="tight-budget", gpu_count=1, duration_hours=1,
                   deadline_hours=2, budget_usd=0.01,   # intentionally tiny
                   cost_weight=0.5, carbon_weight=0.5)
    job = Job(spec=spec)
    optimizer = econodeOptimizer()
    decision = optimizer.evaluate(job, forecasts={}, snapshots=snapshots)
    assert decision.best_region_id in snapshots
