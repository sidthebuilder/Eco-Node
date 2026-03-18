"""
EcoNode Dashboard – Streamlit + Plotly
Real-time 3D globe showing carbon intensity, spot prices, and live migrations.
Auto-refreshes every 30s. Uses the FastAPI backend as data source.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EcoNode | Carbon-Cost Arbitrage Engine",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "http://localhost:8000"

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.metric-card {
    background: linear-gradient(135deg, #0f1923 0%, #162032 100%);
    border: 1px solid #1e3448;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 0.8rem;
}
.metric-value {
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(90deg, #00d4aa, #0095ff);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.metric-label {
    font-size: 0.75rem;
    color: #7a8fa6;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.status-running  { color: #00d4aa; font-weight: 600; }
.status-migrating{ color: #f59e0b; font-weight: 600; }
.status-queued   { color: #7a8fa6; }
.status-done     { color: #6366f1; }
.badge-demo {
    background: #f59e0b22;
    color: #f59e0b;
    border: 1px solid #f59e0b44;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.06em;
}
</style>
""", unsafe_allow_html=True)


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def _get(path: str) -> Any:
    try:
        with httpx.Client(base_url=API_BASE, timeout=5) as c:
            r = c.get(path)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return None


def fetch_all():
    health    = _get("/health")    or {}
    regions   = _get("/regions")   or []
    jobs      = _get("/jobs")      or []
    decisions = _get("/decisions?limit=20") or []
    metrics   = _get("/metrics")   or {}
    return health, regions, jobs, decisions, metrics


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.shields.io/badge/EcoNode-v0.1-00d4aa?style=for-the-badge", use_column_width=False)
    st.markdown("### Project EcoNode")
    st.markdown(
        "Autonomous Carbon-Cost Arbitrage Engine for AI Compute.\n\n"
        "_First unified engine combining spatial + temporal workload arbitrage._"
    )
    st.divider()
    st.markdown("**Submit Demo Job**")
    with st.form("job_form"):
        job_name     = st.text_input("Job name", value="llama3-finetune")
        gpu_count    = st.slider("GPUs", 1, 64, 8)
        duration     = st.number_input("Duration (hours)", min_value=0.5, max_value=72.0, value=4.0)
        deadline     = st.number_input("Deadline (hours)", min_value=1.0, max_value=168.0, value=12.0)
        budget       = st.number_input("Budget ($)", min_value=1.0, max_value=10000.0, value=200.0)
        cost_w       = st.slider("Cost weight α", 0.0, 1.0, 0.6, 0.05)
        carbon_w     = round(1.0 - cost_w, 2)
        st.caption(f"Carbon weight β = {carbon_w}")
        submitted = st.form_submit_button("Submit Job", use_container_width=True)
        if submitted:
            payload = {
                "name": job_name, "gpu_count": gpu_count,
                "duration_hours": duration, "deadline_hours": deadline,
                "budget_usd": budget, "cost_weight": cost_w, "carbon_weight": carbon_w,
            }
            try:
                with httpx.Client(base_url=API_BASE, timeout=10) as c:
                    r = c.post("/jobs", json=payload)
                    r.raise_for_status()
                    d = r.json()
                st.success(f"Job submitted: `{d['job_id'][:8]}…`")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"API error: {e}\n\nMake sure EcoNode API is running on {API_BASE}")

    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (30s)", value=True)
    if st.button("Refresh Now"):
        st.cache_data.clear()
        st.rerun()


# ── Main panel ────────────────────────────────────────────────────────────────

health, regions, jobs, decisions, metrics = fetch_all()
demo_mode = health.get("demo_mode", True)

# Header
col_h1, col_h2 = st.columns([4, 1])
with col_h1:
    st.markdown("## EcoNode Live Dashboard")
    st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')} UTC")
with col_h2:
    if demo_mode:
        st.markdown('<span class="badge-demo">DEMO MODE</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="color:#00d4aa">● LIVE</span>', unsafe_allow_html=True)

# ── KPI row ───────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
kpis = [
    (k1, f"${metrics.get('total_savings_usd', 0):.2f}",   "Cost Saved"),
    (k2, f"{metrics.get('total_carbon_avoided_kgco2', 0):.2f} kg", "CO₂ Avoided"),
    (k3, str(metrics.get("total_jobs", 0)),                "Jobs Managed"),
    (k4, str(metrics.get("total_migrations", 0)),          "Migrations"),
    (k5, str(len(regions)),                                "Regions Online"),
]
for col, val, label in kpis:
    with col:
        st.markdown(
            f'<div class="metric-card"><div class="metric-value">{val}</div>'
            f'<div class="metric-label">{label}</div></div>',
            unsafe_allow_html=True,
        )

st.divider()

# ── Globe + Forecast side-by-side ─────────────────────────────────────────────
left, right = st.columns([3, 2])

with left:
    st.markdown("### Live Region Map")
    if regions:
        import pandas as pd
        df = pd.DataFrame(regions)
        # Colour by carbon intensity (green=low, red=high)
        fig = go.Figure()
        fig.add_trace(go.Scattergeo(
            lat=df["lat"],
            lon=df["lon"],
            text=[
                f"<b>{r['display_name']}</b><br>"
                f"Carbon: {r['carbon_intensity']:.0f} gCO₂/kWh<br>"
                f"Renewable: {r['renewable_pct']:.0f}%<br>"
                f"Spot: ${r['spot_price_usd_hr']:.3f}/GPU-hr<br>"
                f"Provider: {r['provider'].upper()}"
                for r in regions
            ],
            mode="markers",
            marker=dict(
                size=14,
                color=df["carbon_intensity"],
                colorscale=[[0, "#00d4aa"], [0.5, "#f59e0b"], [1, "#ef4444"]],
                cmin=0, cmax=700,
                colorbar=dict(
                    title=dict(text="gCO₂/kWh", font=dict(color="#7a8fa6")),
                    tickfont=dict(color="#7a8fa6"),
                ),
                line=dict(width=1, color="#1e3448"),
                opacity=0.9,
            ),
            hoverinfo="text",
            name="Regions",
        ))
        # Draw migration arcs if there are recent decisions
        for dec in decisions[:3]:
            src_r = next((r for r in regions if r["region_id"] == dec.get("job_id", "")), None)
            dst_r = next((r for r in regions if r["region_id"] == dec.get("best_region_id", "")), None)
            if src_r and dst_r and src_r != dst_r:
                fig.add_trace(go.Scattergeo(
                    lat=[src_r["lat"], dst_r["lat"]],
                    lon=[src_r["lon"], dst_r["lon"]],
                    mode="lines",
                    line=dict(width=2, color="#6366f1"),
                    opacity=0.6,
                    showlegend=False,
                ))

        fig.update_layout(
            geo=dict(
                showland=True, landcolor="#0d1f2d",
                showocean=True, oceancolor="#070e18",
                showcoastlines=True, coastlinecolor="#1e3448",
                showcountries=True, countrycolor="#1e3448",
                bgcolor="#070e18",
                projection_type="orthographic",
                showframe=False,
            ),
            paper_bgcolor="#0a1628",
            plot_bgcolor="#0a1628",
            margin=dict(l=0, r=0, t=0, b=0),
            height=420,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Waiting for region data… (API may be starting up)")

with right:
    st.markdown("### 📈 24h Forecast")
    if regions:
        region_names = {r["region_id"]: r["display_name"] for r in regions}
        sel_region = st.selectbox(
            "Region",
            options=list(region_names.keys()),
            format_func=lambda x: region_names.get(x, x),
            label_visibility="collapsed",
        )
        fc_data = _get(f"/forecast/{sel_region}")
        if fc_data and fc_data.get("points"):
            import pandas as pd
            pts = fc_data["points"]
            fc_df = pd.DataFrame(pts)
            fc_df["ts"] = pd.to_datetime(fc_df["ts"])
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=fc_df["ts"], y=fc_df["carbon"],
                name="Carbon (gCO₂/kWh)",
                line=dict(color="#00d4aa", width=2),
                fill="tonexty" if len(fig2.data) > 0 else None,
            ))
            fig2.add_trace(go.Scatter(
                x=pd.concat([fc_df["ts"], fc_df["ts"][::-1]]),
                y=pd.concat([fc_df["carbon_hi"], fc_df["carbon_lo"][::-1]]),
                fill="toself", fillcolor="rgba(0,212,170,0.08)",
                line=dict(color="rgba(255,255,255,0)"),
                showlegend=False, name="CI band",
            ))
            fig2.add_trace(go.Scatter(
                x=fc_df["ts"], y=fc_df["price"] * 100,
                name="Price (¢/GPU-hr)",
                line=dict(color="#f59e0b", width=2, dash="dot"),
                yaxis="y2",
            ))
            fig2.update_layout(
                paper_bgcolor="#0a1628", plot_bgcolor="#0a1628",
                font=dict(color="#7a8fa6"),
                xaxis=dict(showgrid=False, gridcolor="#1e3448"),
                yaxis=dict(title="gCO₂/kWh", gridcolor="#1e3448", showgrid=True),
                yaxis2=dict(
                    title="¢/GPU-hr", overlaying="y", side="right",
                    showgrid=False,
                ),
                legend=dict(bgcolor="rgba(0,0,0,0)", x=0, y=1),
                margin=dict(l=0, r=60, t=10, b=0),
                height=420,
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Forecast available after first poll cycle (~5 min)")
    else:
        st.info("No regions loaded")

st.divider()

# ── Active Jobs Table ─────────────────────────────────────────────────────────
bot_left, bot_right = st.columns([3, 2])

with bot_left:
    st.markdown("### Active Jobs")
    if jobs:
        import pandas as pd
        jdf = pd.DataFrame([{
            "Name":          j["name"],
            "Status":        j["status"],
            "Region":        (j.get("current_region") or "—").split(":")[-1],
            "Progress":      f"{j.get('progress_pct', 0):.0f}%",
            "Savings ($)":   f"${j['savings_usd']:.2f}",
            "CO₂ Avoided":  f"{j['carbon_avoided_kgco2']:.3f} kg",
            "Migrations":    j["migration_count"],
        } for j in jobs])
        st.dataframe(jdf, use_container_width=True, hide_index=True)
    else:
        st.info("No jobs yet. Submit one from the sidebar →")

with bot_right:
    st.markdown("### Region Leaderboard")
    if regions:
        import pandas as pd
        ldf = pd.DataFrame([{
            "Region":    r["display_name"].split("(")[-1].rstrip(")"),
            "Carbon":    f"{r['carbon_intensity']:.0f}",
            "Spot $":    f"${r['spot_price_usd_hr']:.3f}",
            "Renewable": f"{r['renewable_pct']:.0f}%",
        } for r in sorted(regions, key=lambda x: x["carbon_intensity"])])
        st.dataframe(ldf, use_container_width=True, hide_index=True)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()
