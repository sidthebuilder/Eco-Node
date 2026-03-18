import createGlobe from 'https://esm.sh/cobe';

const API_BASE = 'http://localhost:8000';
let globe;
let chart;
let currentRegions = {};
let selectedRegionId = '';

// ── UI Elements ────────────────────────────────────────────────────────────
const els = {
    updated: document.getElementById('last-updated'),
    savings: document.getElementById('kpi-savings'),
    carbon: document.getElementById('kpi-carbon'),
    jobs: document.getElementById('kpi-jobs'),
    migrations: document.getElementById('kpi-migrations'),
    regions: document.getElementById('kpi-regions'),

    alphaSlider: document.getElementById('job-alpha'),
    alphaVal: document.getElementById('alpha-val'),
    betaVal: document.getElementById('beta-val'),
    jobForm: document.getElementById('job-form'),
    formMsg: document.getElementById('form-msg'),

    regionSelect: document.getElementById('region-select'),
    jobsTbody: document.getElementById('jobs-tbody'),
    decisionsTbody: document.getElementById('decisions-tbody'),
};

// ── Sliders ────────────────────────────────────────────────────────────────
els.alphaSlider.addEventListener('input', (e) => {
    const a = parseFloat(e.target.value);
    const b = 1.0 - a;
    els.alphaVal.textContent = a.toFixed(2);
    els.betaVal.textContent = b.toFixed(2);
});

// ── API Fetchers ───────────────────────────────────────────────────────────
async function fetchMetrics() {
    try {
        const res = await fetch(`${API_BASE}/metrics`);
        const data = await res.json();

        // Update KPIs with simple animation
        els.savings.textContent = data.total_savings_usd.toFixed(2);
        els.carbon.textContent = data.total_carbon_avoided_kgco2.toFixed(2);
        els.jobs.textContent = data.active_jobs || (data.total_jobs - data.completed_jobs) || 0;
        els.migrations.textContent = data.total_migrations;

        const now = new Date();
        els.updated.textContent = `Updated: ${now.toLocaleTimeString('en-US', { hour12: false })} UTC`;
    } catch (e) { console.error('Failed to fetch metrics:', e); }
}

async function fetchRegions() {
    try {
        const res = await fetch(`${API_BASE}/regions`);
        const data = await res.json();
        currentRegions = data;
        els.regions.textContent = Object.keys(data).length;

        // Update select dropdown if empty
        if (els.regionSelect.options.length <= 1) {
            els.regionSelect.innerHTML = '';
            for (const [id, snap] of Object.entries(data)) {
                const opt = document.createElement('option');
                opt.value = id;
                opt.textContent = snap.display_name;
                els.regionSelect.appendChild(opt);
            }
            if (!selectedRegionId && Object.keys(data).length > 0) {
                selectedRegionId = Object.keys(data)[0];
                els.regionSelect.value = selectedRegionId;
                fetchForecast(selectedRegionId);
            }
        }

        updateGlobeMarkers();
    } catch (e) { console.error('Failed to fetch regions:', e); }
}

async function fetchJobs() {
    try {
        const res = await fetch(`${API_BASE}/jobs`);
        const data = await res.json();

        const active = Object.values(data).filter(j =>
            !['DONE', 'FAILED'].includes(j.status)
        );

        if (active.length === 0) {
            els.jobsTbody.innerHTML = `<tr><td colspan="4" class="px-4 py-8 text-center text-xs text-textSecondary">No active jobs</td></tr>`;
            return;
        }

        els.jobsTbody.innerHTML = active.map(j => {
            const savings = j.savings_usd || 0;
            const savingsStr = savings > 0 ? `<span class="text-accent">+$${savings.toFixed(2)}</span>` : '-';

            let statusColor = 'text-textSecondary';
            if (j.status === 'RUNNING') statusColor = 'text-accent';
            if (j.status === 'MIGRATING') statusColor = 'text-warning';

            return `
                <tr class="border-b border-white/5 hover:bg-white/5 transition-colors">
                    <td class="px-4 py-3 text-white truncate max-w-[150px]">${j.spec.name}</td>
                    <td class="px-4 py-3 font-medium ${statusColor}">${j.status}</td>
                    <td class="px-4 py-3 text-xs">${j.current_region_id || 'PENDING'}</td>
                    <td class="px-4 py-3 text-right">${savingsStr}</td>
                </tr>
            `;
        }).join('');
    } catch (e) { console.error('Failed to fetch jobs:', e); }
}

async function fetchDecisions() {
    try {
        const res = await fetch(`${API_BASE}/decisions`);
        const data = await res.json(); // returns array

        if (data.length === 0) {
            els.decisionsTbody.innerHTML = `<tr><td colspan="4" class="px-4 py-8 text-center text-xs text-textSecondary">No recent decisions</td></tr>`;
            return;
        }

        // Show last 5
        const recent = data.slice(-5).reverse();

        els.decisionsTbody.innerHTML = recent.map(d => {
            const time = new Date(d.evaluated_at).toLocaleTimeString('en-US', { hour12: false });
            const isMig = d.trigger === 'mid_run';
            const action = isMig ?
                `<span class="px-2 py-0.5 bg-warning/20 text-warning rounded text-[10px] uppercase font-bold">Migration</span>` :
                `<span class="px-2 py-0.5 bg-accent/20 text-accent rounded text-[10px] uppercase font-bold">Placement</span>`;

            return `
                <tr class="border-b border-white/5 hover:bg-white/5 transition-colors">
                    <td class="px-4 py-3 text-xs">${time}</td>
                    <td class="px-4 py-3">${action}</td>
                    <td class="px-4 py-3 text-white">${d.best_region_id}</td>
                    <td class="px-4 py-3 text-right text-xs">
                        <div class="text-accent">${d.savings_vs_baseline_pct.toFixed(1)}% cost\u2193</div>
                        <div class="text-white/70">${d.carbon_reduction_pct.toFixed(1)}% CO\u2082\u2193</div>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (e) { console.error('Failed to fetch decisions:', e); }
}

async function fetchForecast(regionId) {
    if (!regionId) return;
    try {
        const res = await fetch(`${API_BASE}/forecast/${regionId}`);
        const data = await res.json();
        updateChart(data);
    } catch (e) { console.error('Failed to fetch forecast:', e); }
}

// ── Submit Job ─────────────────────────────────────────────────────────────
els.jobForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    // Animate button
    const btn = e.target.querySelector('button');
    const originalText = btn.innerHTML;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Submitting`;
    lucide.createIcons();

    const a = parseFloat(els.alphaSlider.value);

    const payload = {
        name: document.getElementById('job-name').value,
        gpu_count: parseInt(document.getElementById('job-gpus').value, 10),
        duration_hours: parseFloat(document.getElementById('job-duration').value),
        deadline_hours: parseFloat(document.getElementById('job-deadline').value),
        budget_usd: parseFloat(document.getElementById('job-budget').value),
        cost_weight: a,
        carbon_weight: 1.0 - a
    };

    try {
        const res = await fetch(`${API_BASE}/jobs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            els.formMsg.textContent = 'Job successfully scheduled';
            els.formMsg.classList.replace('opacity-0', 'opacity-100');
            setTimeout(() => els.formMsg.classList.replace('opacity-100', 'opacity-0'), 3000);
            fetchJobs();
        }
    } catch (err) {
        console.error(err);
    } finally {
        btn.innerHTML = originalText;
    }
});

// ── Globe Visualization (Cobe) ─────────────────────────────────────────────
let phi = 0;
let globeOptions = {
    devicePixelRatio: 2,
    width: 0,
    height: 0,
    phi: 0,
    theta: 0.3,
    dark: 1,
    diffuse: 1.2,
    mapSamples: 16000,
    mapBrightness: 3,
    baseColor: [0.1, 0.1, 0.15],      // Very dark blue/grey
    markerColor: [0, 0.83, 0.66],     // Accent default
    glowColor: [0.03, 0.03, 0.05],    // Dark glow
    markers: [],
    onRender: (state) => {
        state.phi = phi;
        phi += 0.003; // Auto-rotate
    }
};

function initGlobe() {
    const canvas = document.getElementById('cobe');
    const container = document.getElementById('globe-container');

    const updateSize = () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        canvas.width = w * 2;
        canvas.height = h * 2;
        canvas.style.width = w + 'px';
        canvas.style.height = h + 'px';
        globeOptions.width = w * 2;
        globeOptions.height = h * 2;
    };

    updateSize();
    window.addEventListener('resize', () => {
        updateSize();
        if (globe) { globe.destroy(); globe = createGlobe(canvas, globeOptions); }
    });

    globe = createGlobe(canvas, globeOptions);
}

function updateGlobeMarkers() {
    if (!globe) return;

    const markers = [];
    for (const snap of Object.values(currentRegions)) {
        // Map carbon intensity [0, 700] to a color gradient [Green -> Yellow -> Red]
        const c = snap.carbon_intensity;
        let r, g, b;
        if (c < 300) {
            // Accent teal: #00d4aa -> rgb(0, 212, 170) -> [0, 0.83, 0.66]
            r = 0; g = 0.83; b = 0.66;
        } else if (c < 500) {
            // Warning amber: #f59e0b -> [0.96, 0.62, 0.04]
            r = 0.96; g = 0.62; b = 0.04;
        } else {
            // Danger red: #ef4444 -> [0.93, 0.26, 0.26]
            r = 0.93; g = 0.26; b = 0.26;
        }

        // Cobe marker takes [lat, lon, size]
        // Base size 0.05, max 0.12 depending on price relative
        markers.push({
            location: [snap.lat, snap.lon],
            size: 0.06 + (Math.random() * 0.04), // Random jitter for now
        });

        // Cobe v1.2 only supports one global markerColor unfortunately.
        // We set the base to the accent color, but it doesn't do per-marker colors easily
        // without custom shaders. We'll use the accent color globally for the slick look.
    }

    globeOptions.markers = markers;
    // We must recreate the globe to update markers in Cobe v1
    const canvas = document.getElementById('cobe');
    globe.destroy();
    globe = createGlobe(canvas, globeOptions);
}

// ── Chart.js Setup ─────────────────────────────────────────────────────────
function initChart() {
    const ctx = document.getElementById('forecast-chart').getContext('2d');

    // Set global defaults for dark theme
    Chart.defaults.color = '#7a8fa6';
    Chart.defaults.font.family = "'Inter', sans-serif";

    chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Carbon (gCO₂/kWh)',
                    yAxisID: 'y',
                    borderColor: '#00d4aa',
                    backgroundColor: 'rgba(0, 212, 170, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.4,
                    data: []
                },
                {
                    label: 'Price ($/hr)',
                    yAxisID: 'y1',
                    borderColor: '#7a8fa6',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: false,
                    tension: 0.1,
                    data: []
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { boxWidth: 12, usePointStyle: true } },
                tooltip: {
                    backgroundColor: 'rgba(9, 9, 11, 0.9)',
                    titleColor: '#fff',
                    bodyColor: '#a1a1aa',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    padding: 10
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
                    ticks: { maxTicksLimit: 6 }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
                    title: { display: true, text: 'gCO₂/kWh' },
                    min: 0
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false }, // only draw grid lines for one axis
                    title: { display: true, text: 'Price ($/hr)' },
                    min: 0
                }
            }
        }
    });

    els.regionSelect.addEventListener('change', (e) => {
        selectedRegionId = e.target.value;
        fetchForecast(selectedRegionId);
    });
}

function updateChart(forecastData) {
    if (!chart || !forecastData || !forecastData.points) return;

    const labels = [];
    const carbon = [];
    const price = [];

    forecastData.points.forEach(pt => {
        const d = new Date(pt.ts);
        labels.push(d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false }));
        carbon.push(pt.carbon);
        price.push(pt.price);
    });

    chart.data.labels = labels;
    chart.data.datasets[0].data = carbon;
    chart.data.datasets[1].data = price;
    chart.update();
}

// ── Boot ───────────────────────────────────────────────────────────────────
initGlobe();
initChart();

async function poll() {
    await Promise.all([
        fetchMetrics(),
        fetchRegions(),
        fetchJobs(),
        fetchDecisions()
    ]);

    // Refresh forecast for selected region every few polls
    if (selectedRegionId && Math.random() < 0.2) {
        fetchForecast(selectedRegionId);
    }
}

// Initial fetch
poll();

// Poll every 5s
setInterval(poll, 5000);
