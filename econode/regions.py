"""
econode – Cloud Region Registry
Static catalog of all supported cloud regions with geo-coordinates
and ElectricityMaps zone mappings. Extend freely.
"""
from __future__ import annotations

from econode.models import CloudRegion, Provider

# fmt: off
_RAW: list[dict] = [
    # ── AWS ───────────────────────────────────────────────────────────────────
    dict(id="aws:us-east-1",      provider=Provider.AWS,   region_code="us-east-1",
         display_name="AWS US East (N. Virginia)",   lat=38.89,  lon=-77.04,
         zone="US-MIDA-PJM",      gpu_types=["p4d.24xlarge","p3.8xlarge"]),
    dict(id="aws:us-west-2",      provider=Provider.AWS,   region_code="us-west-2",
         display_name="AWS US West (Oregon)",         lat=45.52,  lon=-122.68,
         zone="US-NW-PACW",       gpu_types=["p4d.24xlarge","g5.48xlarge"]),
    dict(id="aws:eu-west-1",      provider=Provider.AWS,   region_code="eu-west-1",
         display_name="AWS EU (Ireland)",             lat=53.33,  lon=-6.25,
         zone="IE",               gpu_types=["p3.8xlarge"]),
    dict(id="aws:ap-southeast-1", provider=Provider.AWS,   region_code="ap-southeast-1",
         display_name="AWS AP (Singapore)",          lat=1.35,   lon=103.82,
         zone="SG",               gpu_types=["p3.8xlarge"]),
    dict(id="aws:eu-north-1",     provider=Provider.AWS,   region_code="eu-north-1",
         display_name="AWS EU (Stockholm)",           lat=59.33,  lon=18.07,
         zone="SE",               gpu_types=["p3.8xlarge"]),
    # ── GCP ───────────────────────────────────────────────────────────────────
    dict(id="gcp:us-west1",       provider=Provider.GCP,   region_code="us-west1",
         display_name="GCP US West (Oregon)",         lat=45.59,  lon=-122.71,
         zone="US-NW-PACW",       gpu_types=["a100-80gb","t4"]),
    dict(id="gcp:us-central1",    provider=Provider.GCP,   region_code="us-central1",
         display_name="GCP US Central (Iowa)",        lat=41.88,  lon=-93.10,
         zone="US-MIDW-MISO",     gpu_types=["a100-80gb","v100"]),
    dict(id="gcp:europe-west4",   provider=Provider.GCP,   region_code="europe-west4",
         display_name="GCP Europe West (Netherlands)",lat=52.38,  lon=4.90,
         zone="NL",               gpu_types=["a100-80gb"]),
    dict(id="gcp:europe-west1",   provider=Provider.GCP,   region_code="europe-west1",
         display_name="GCP Europe West (Belgium)",   lat=50.85,  lon=4.35,
         zone="BE",               gpu_types=["t4"]),
    # ── Azure ─────────────────────────────────────────────────────────────────
    dict(id="azure:eastus",       provider=Provider.AZURE, region_code="eastus",
         display_name="Azure East US (Virginia)",     lat=37.38,  lon=-79.46,
         zone="US-MIDA-PJM",      gpu_types=["Standard_ND96asr_v4"]),
    dict(id="azure:westeurope",   provider=Provider.AZURE, region_code="westeurope",
         display_name="Azure West Europe (Netherlands)",lat=52.38,lon=4.90,
         zone="NL",               gpu_types=["Standard_ND96asr_v4"]),
    dict(id="azure:germanywestcentral", provider=Provider.AZURE,
         region_code="germanywestcentral",
         display_name="Azure Germany West Central",  lat=50.11,  lon=8.68,
         zone="DE",               gpu_types=["Standard_NC24rs_v3"]),
    dict(id="azure:francecentral",provider=Provider.AZURE, region_code="francecentral",
         display_name="Azure France Central (Paris)", lat=48.85,  lon=2.35,
         zone="FR",               gpu_types=["Standard_NC24rs_v3"]),
]
# fmt: on

REGIONS: dict[str, CloudRegion] = {
    d["id"]: CloudRegion(**d) for d in _RAW
}
