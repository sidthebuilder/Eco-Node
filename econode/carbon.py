"""
econode – Carbon Intensity Client
Wraps ElectricityMaps REST API v3.
Falls back to stochastic mock when ELECTRICITY_MAPS_KEY is not set.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timezone
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from econode.config import get_settings
from econode.models import CarbonSnapshot
from econode.regions import REGIONS

log = logging.getLogger(__name__)
_settings = get_settings()

# Realistic baseline carbon intensities (gCO2eq/kWh) per ElectricityMaps zone
# sourced from electricitymaps.com/data-portal public dataset
_ZONE_BASELINES: dict[str, float] = {
    "US-MIDA-PJM":   350.0,  # AWS us-east-1 (mid-Atlantic)
    "US-NW-PACW":    120.0,  # AWS us-west-2 (Pacific NW – hydro-heavy)
    "US-CAL-CISO":   200.0,  # GCP us-west1 (California)
    "US-TEX-ERCO":   390.0,  # Texas
    "DE":            350.0,  # Azure germanywestcentral
    "FR":             60.0,  # France – nuclear-heavy
    "SE":             15.0,  # Sweden – near-zero
    "SG":            430.0,  # Singapore
    "IN-SO":         720.0,  # India South
    "AU-NSW":        580.0,  # Australia Sydney
    "BR-CS":         120.0,  # Brazil – hydro-heavy
    "JP-TK":         480.0,  # Japan Tokyo
}


def _mock_carbon(zone: str, ts: datetime) -> CarbonSnapshot:
    """
    Generate realistic carbon intensity with diurnal variation.
    Pattern: peak demand morning/evening, cleaner overnight.
    Small region-correlated perturbation prevents thundering-herd artefacts.
    """
    base = _ZONE_BASELINES.get(zone, 300.0)
    hour = ts.hour
    # diurnal wave  (peak at 8am and 6pm)
    diurnal = 0.15 * math.sin(2 * math.pi * (hour - 2) / 24)
    # uncorrelated noise per zone (seeded by zone hash so stable across calls)
    rng = random.Random(hash(zone) ^ int(ts.timestamp() / 300))
    noise = rng.gauss(0, 0.05)
    ci = max(5.0, base * (1 + diurnal + noise))
    renewable_pct = max(0.0, min(100.0, 100 * (1 - ci / 900)))
    return CarbonSnapshot(
        region_id=f"_mock_{zone}",
        zone=zone,
        timestamp=ts,
        carbon_intensity=round(ci, 2),
        renewable_pct=round(renewable_pct, 1),
        data_source="mock",
        is_mock=True,
    )


class CarbonClient:
    """
    Async client for carbon intensity data.
    Live mode: ElectricityMaps API v3.
    Demo mode: deterministic stochastic mock with diurnal patterns.
    """

    def __init__(self) -> None:
        self._live = _settings.has_electricity_maps
        self._base = _settings.electricity_maps_base_url
        headers = {}
        if self._live:
            headers["auth-token"] = _settings.electricity_maps_key or ""
        self._http = httpx.AsyncClient(
            base_url=self._base,
            headers=headers,
            timeout=10.0,
        )
        if not self._live:
            log.warning("No ELECTRICITY_MAPS_KEY – carbon client in mock mode")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def latest(self, zone: str) -> CarbonSnapshot:
        """Fetch (or mock) the current carbon intensity for a zone."""
        if not self._live:
            return _mock_carbon(zone, datetime.now(timezone.utc))
        return await self._fetch_latest(zone)

    async def latest_all(self) -> dict[str, CarbonSnapshot]:
        """Fetch carbon snapshots for all configured regions concurrently, keyed by region_id."""
        async def _fetch_for_region(region_id: str, zone: str) -> tuple[str, CarbonSnapshot]:
            snap = await self.latest(zone)
            snap.region_id = region_id  # override zone-based id with the actual region_id
            return region_id, snap

        tasks = [
            _fetch_for_region(r.id, r.zone)
            for r in REGIONS.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, CarbonSnapshot] = {}
        for result in results:
            if isinstance(result, Exception):
                log.warning("Carbon fetch failed: %s", result)
            else:
                region_id, snap = result  # type: ignore[misc]
                out[region_id] = snap
        return out

    async def forecast(self, zone: str, hours: int = 24) -> list[CarbonSnapshot]:
        """Return hourly carbon forecast (live or synthetic)."""
        if not self._live:
            now = datetime.now(timezone.utc)
            return [
                _mock_carbon(zone, now.replace(hour=(now.hour + h) % 24, minute=0, second=0, microsecond=0))
                for h in range(hours)
            ]
        return await self._fetch_forecast(zone, hours)

    async def close(self) -> None:
        await self._http.aclose()

    # ── Internal ───────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _fetch_latest(self, zone: str) -> CarbonSnapshot:
        resp = await self._http.get(
            "/carbon-intensity/latest",
            params={"zone": zone},
        )
        resp.raise_for_status()
        data = resp.json()
        return CarbonSnapshot(
            region_id=zone,
            zone=zone,
            timestamp=datetime.fromisoformat(data["datetime"].replace("Z", "+00:00")),
            carbon_intensity=float(data["carbonIntensity"]),
            renewable_pct=float(data.get("renewablePercentage", 0.0)),
            data_source="electricitymaps",
            is_mock=False,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _fetch_forecast(self, zone: str, hours: int) -> list[CarbonSnapshot]:
        resp = await self._http.get(
            "/carbon-intensity/forecast",
            params={"zone": zone},
        )
        resp.raise_for_status()
        entries = resp.json().get("forecast", [])[:hours]
        return [
            CarbonSnapshot(
                region_id=zone,
                zone=zone,
                timestamp=datetime.fromisoformat(e["datetime"].replace("Z", "+00:00")),
                carbon_intensity=float(e["carbonIntensity"]),
                renewable_pct=float(e.get("renewablePercentage", 0.0)),
                data_source="electricitymaps",
                is_mock=False,
            )
            for e in entries
        ]
