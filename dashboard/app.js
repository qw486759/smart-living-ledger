const API_BASE = (window.EIP_API_BASE || document.body.dataset.apiBase || '').replace(/\/$/, '');
const REFRESH_INTERVAL_MS = 30_000;
const TYPE_QUERY_LIMIT = 100;

let temperatureChart;
let plugChart;
let refreshTimer;

const elements = {
  errorBanner: document.getElementById('error-banner'),
  lastRefresh: document.getElementById('last-refresh'),
  refreshButton: document.getElementById('refresh-button'),
  tempLatest: document.getElementById('temp-latest'),
  plugLatest: document.getElementById('plug-latest'),
  motionState: document.getElementById('motion-state'),
  motionDevice: document.getElementById('motion-device'),
  motionTime: document.getElementById('motion-time'),
  voiceCommand: document.getElementById('voice-command'),
  voiceDevice: document.getElementById('voice-device'),
  voiceTime: document.getElementById('voice-time'),
};

function buildChartOptions() {
  const styles = getComputedStyle(document.documentElement);
  const muted = styles.getPropertyValue('--muted').trim();
  const border = styles.getPropertyValue('--border').trim();

  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#111827',
        borderColor: border,
        borderWidth: 1,
        titleColor: '#eef4ff',
        bodyColor: '#eef4ff',
      },
    },
    scales: {
      x: {
        ticks: { color: muted, maxRotation: 0, autoSkip: true },
        grid: { color: border },
      },
      y: {
        ticks: { color: muted },
        grid: { color: border },
        beginAtZero: false,
      },
    },
  };
}

function initializeCharts() {
  const styles = getComputedStyle(document.documentElement);
  const blue = styles.getPropertyValue('--blue').trim();
  const orange = styles.getPropertyValue('--orange').trim();
  const sharedOptions = buildChartOptions();

  temperatureChart = new Chart(document.getElementById('temperature-chart'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          data: [],
          borderColor: blue,
          backgroundColor: 'rgba(56, 189, 248, 0.14)',
          borderWidth: 2,
          fill: true,
          pointRadius: 3,
          tension: 0.35,
        },
      ],
    },
    options: sharedOptions,
  });

  plugChart = new Chart(document.getElementById('plug-chart'), {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        {
          data: [],
          backgroundColor: 'rgba(251, 146, 60, 0.68)',
          borderColor: orange,
          borderWidth: 1,
          borderRadius: 8,
        },
      ],
    },
    options: {
      ...sharedOptions,
      scales: {
        ...sharedOptions.scales,
        y: { ...sharedOptions.scales.y, beginAtZero: true },
      },
    },
  });
}

async function fetchEvents(params = {}) {
  if (!API_BASE) {
    throw new Error('Missing query API base URL. Set body[data-api-base] or window.EIP_API_BASE.');
  }

  const url = new URL(`${API_BASE}/events`);
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));

  const response = await fetch(url);
  const body = await response.json().catch(() => ({}));

  if (!response.ok) {
    const message = body.error || `Request failed with HTTP ${response.status}`;
    const code = body.code ? ` (${body.code})` : '';
    throw new Error(`${message}${code}`);
  }

  return Array.isArray(body.items) ? body.items : [];
}

function sortByTimestampAscending(items) {
  return [...items].sort((left, right) => left.ts - right.ts);
}

function sortByTimestampDescending(items) {
  return [...items].sort((left, right) => right.ts - left.ts);
}

function formatTime(ts) {
  if (!ts) return '--';
  return new Date(ts * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatHour(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function updateTemperatureChart(items) {
  const readings = sortByTimestampAscending(items)
    .filter((item) => Number.isFinite(Number(item.payload?.celsius)))
    .slice(-40);

  temperatureChart.data.labels = readings.map((item) => formatHour(item.ts));
  temperatureChart.data.datasets[0].data = readings.map((item) => Number(item.payload.celsius));
  temperatureChart.update();

  const latest = sortByTimestampDescending(readings)[0];
  elements.tempLatest.textContent = latest ? `${Number(latest.payload.celsius).toFixed(1)} °C` : '-- °C';
}

function updatePlugChart(items) {
  const hourlyBuckets = new Map();

  items.forEach((item) => {
    const watts = Number(item.payload?.watt);
    if (!Number.isFinite(watts) || !item.ts) return;

    const bucketStartMs = Math.floor(item.ts / 3600) * 3600 * 1000;
    const bucket = hourlyBuckets.get(bucketStartMs) || { total: 0, count: 0 };
    bucket.total += watts;
    bucket.count += 1;
    hourlyBuckets.set(bucketStartMs, bucket);
  });

  const buckets = [...hourlyBuckets.entries()]
    .sort(([left], [right]) => left - right)
    .slice(-12);

  plugChart.data.labels = buckets.map(([bucketStartMs]) =>
    new Date(bucketStartMs).toLocaleTimeString([], { hour: '2-digit' }),
  );
  plugChart.data.datasets[0].data = buckets.map(([, bucket]) =>
    Math.round(bucket.total / bucket.count),
  );
  plugChart.update();

  const latest = sortByTimestampDescending(items).find((item) => Number.isFinite(Number(item.payload?.watt)));
  elements.plugLatest.textContent = latest ? `${Number(latest.payload.watt).toFixed(0)} W` : '-- W';
}

function updateMotionStatus(items) {
  const latest = sortByTimestampDescending(items)[0];

  if (!latest) {
    elements.motionState.textContent = 'No motion data';
    elements.motionDevice.textContent = 'Device unavailable';
    elements.motionTime.textContent = '--';
    return;
  }

  elements.motionState.textContent = latest.payload?.detected ? 'Detected' : 'Clear';
  elements.motionDevice.textContent = latest.device_id || 'Unknown device';
  elements.motionTime.textContent = formatTime(latest.ts);
}

function updateVoiceStatus(items) {
  const latest = sortByTimestampDescending(items)[0];

  if (!latest) {
    elements.voiceCommand.textContent = 'No command data';
    elements.voiceDevice.textContent = 'Device unavailable';
    elements.voiceTime.textContent = '--';
    return;
  }

  elements.voiceCommand.textContent = latest.payload?.command || 'Unknown command';
  elements.voiceDevice.textContent = latest.device_id || 'Unknown device';
  elements.voiceTime.textContent = formatTime(latest.ts);
}

function showError(message) {
  elements.errorBanner.textContent = message;
  elements.errorBanner.hidden = false;
}

function clearError() {
  elements.errorBanner.textContent = '';
  elements.errorBanner.hidden = true;
}

async function refreshDashboard() {
  elements.refreshButton.disabled = true;

  try {
    const [temperatureEvents, plugEvents, motionEvents, voiceEvents] = await Promise.all([
      fetchEvents({ type: 'temp', limit: TYPE_QUERY_LIMIT }),
      fetchEvents({ type: 'plug', limit: TYPE_QUERY_LIMIT }),
      fetchEvents({ type: 'motion', limit: TYPE_QUERY_LIMIT }),
      fetchEvents({ type: 'voice', limit: TYPE_QUERY_LIMIT }),
    ]);

    updateTemperatureChart(temperatureEvents);
    updatePlugChart(plugEvents);
    updateMotionStatus(motionEvents);
    updateVoiceStatus(voiceEvents);
    elements.lastRefresh.textContent = `Updated ${new Date().toLocaleTimeString()}`;
    clearError();
  } catch (error) {
    showError(`Dashboard refresh failed: ${error.message}`);
  } finally {
    elements.refreshButton.disabled = false;
  }
}

function startAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshDashboard, REFRESH_INTERVAL_MS);
}

window.addEventListener('DOMContentLoaded', () => {
  initializeCharts();
  elements.refreshButton.addEventListener('click', refreshDashboard);
  refreshDashboard();
  startAutoRefresh();
});
