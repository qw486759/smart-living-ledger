const API_BASE = (window.EIP_API_BASE || document.body.dataset.apiBase || '').replace(/\/$/, '');
const REFRESH_INTERVAL_MS = 30_000;
const EVENT_QUERY_LIMIT = 200;
const ENTITY_ID = 'zeus';
const NO_SIGHTING_ALERT_HOURS = 24;

let intakeChart;
let sightingsChart;
let refreshTimer;

const elements = {
  errorBanner: document.getElementById('error-banner'),
  lastRefresh: document.getElementById('last-refresh'),
  refreshButton: document.getElementById('refresh-button'),
  welfareState: document.getElementById('welfare-state'),
  welfareDetail: document.getElementById('welfare-detail'),
  lastSeen: document.getElementById('last-seen'),
  lastSeenZone: document.getElementById('last-seen-zone'),
  lastSeenMeta: document.getElementById('last-seen-meta'),
  intakeLatest: document.getElementById('intake-latest'),
  sightingsTotal: document.getElementById('sightings-total'),
  visitsGallery: document.getElementById('visits-gallery'),
  visitsCount: document.getElementById('visits-count'),
  intrudersGallery: document.getElementById('intruders-gallery'),
  intrudersCount: document.getElementById('intruders-count'),
  lightbox: document.getElementById('lightbox'),
  lightboxImg: document.getElementById('lightbox-img'),
  lightboxCaption: document.getElementById('lightbox-caption'),
};

const GALLERY_LIMIT = 12;
const SIGHTINGS_FETCH_LIMIT = 50;

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
      x: { ticks: { color: muted, maxRotation: 0, autoSkip: true }, grid: { color: border } },
      y: { ticks: { color: muted }, grid: { color: border }, beginAtZero: true },
    },
  };
}

function initializeCharts() {
  const styles = getComputedStyle(document.documentElement);
  const blue = styles.getPropertyValue('--blue').trim();
  const orange = styles.getPropertyValue('--orange').trim();
  const sharedOptions = buildChartOptions();

  intakeChart = new Chart(document.getElementById('intake-chart'), {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        data: [],
        borderColor: blue,
        backgroundColor: 'rgba(56, 189, 248, 0.14)',
        borderWidth: 2,
        fill: true,
        pointRadius: 3,
        tension: 0.35,
      }],
    },
    options: sharedOptions,
  });

  sightingsChart = new Chart(document.getElementById('sightings-chart'), {
    type: 'bar',
    data: {
      labels: [],
      datasets: [{
        data: [],
        backgroundColor: 'rgba(251, 146, 60, 0.68)',
        borderColor: orange,
        borderWidth: 1,
        borderRadius: 8,
      }],
    },
    options: sharedOptions,
  });
}

async function fetchJson(path, params = {}) {
  if (!API_BASE) {
    throw new Error('Missing query API base URL. Set window.EIP_API_BASE in config.js.');
  }
  const url = new URL(`${API_BASE}${path}`);
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));

  const response = await fetch(url);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body.error || `Request failed with HTTP ${response.status}`;
    const code = body.code ? ` (${body.code})` : '';
    throw new Error(`${message}${code}`);
  }
  return body;
}

async function fetchEntityState() {
  const body = await fetchJson('/state', { entity: ENTITY_ID });
  return body.state || null;
}

async function fetchEventsByType(type) {
  const body = await fetchJson('/events', { type, limit: EVENT_QUERY_LIMIT });
  return Array.isArray(body.items) ? body.items : [];
}

async function fetchRecentVisits() {
  // Fetch more raw sightings than we show, since many collapse into a few visits.
  const body = await fetchJson('/sightings', { limit: SIGHTINGS_FETCH_LIMIT });
  return Array.isArray(body.items) ? body.items : [];
}

async function fetchRecentIntrusions() {
  const body = await fetchJson('/intrusions', { limit: GALLERY_LIMIT });
  return Array.isArray(body.items) ? body.items : [];
}

function formatTime(ts) {
  if (!ts) return '--';
  return new Date(ts * 1000).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function formatHourLabel(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit' });
}

function hoursSince(ts) {
  return (Date.now() / 1000 - ts) / 3600;
}

function renderWelfare(state) {
  if (!state || !state.last_sighting_ts) {
    elements.welfareState.textContent = 'Unknown';
    elements.welfareDetail.textContent = 'No sightings yet';
    return;
  }
  const gap = hoursSince(state.last_sighting_ts);
  if (gap > NO_SIGHTING_ALERT_HOURS) {
    elements.welfareState.textContent = 'Attention';
    elements.welfareDetail.textContent = `Not seen for ${gap.toFixed(1)}h (> ${NO_SIGHTING_ALERT_HOURS}h)`;
  } else {
    elements.welfareState.textContent = 'OK';
    elements.welfareDetail.textContent = `Seen ${gap.toFixed(1)}h ago`;
  }
}

function renderLastSeen(state) {
  if (!state || !state.last_sighting_ts) {
    elements.lastSeen.textContent = '--';
    elements.lastSeenZone.textContent = '--';
    elements.lastSeenMeta.textContent = '--';
    return;
  }
  elements.lastSeen.textContent = formatTime(state.last_sighting_ts);
  elements.lastSeenZone.textContent = state.last_sighting_zone || '--';
  const source = state.last_sighting_source || '--';
  const conf = state.last_sighting_confidence;
  const confText = conf != null ? ` · ${(Number(conf) * 100).toFixed(0)}% conf` : '';
  elements.lastSeenMeta.textContent = `${source}${confText}`;
}

function renderIntake(feedings) {
  const sorted = [...feedings].sort((left, right) => left.ts - right.ts).slice(-20);
  intakeChart.data.labels = sorted.map((item) => formatTime(item.ts));
  intakeChart.data.datasets[0].data = sorted.map((item) => Number(item.payload?.grams) || 0);
  intakeChart.update();

  const latest = [...feedings].sort((left, right) => right.ts - left.ts)[0];
  elements.intakeLatest.textContent = latest ? `${(Number(latest.payload?.grams) || 0).toFixed(0)} g` : '-- g';
}

function renderSightings(sightings) {
  const dayAgo = Date.now() / 1000 - 24 * 3600;
  const recent = sightings.filter((item) => item.ts >= dayAgo);

  const buckets = new Map();
  recent.forEach((item) => {
    const hourStart = Math.floor(item.ts / 3600) * 3600;
    buckets.set(hourStart, (buckets.get(hourStart) || 0) + 1);
  });

  const entries = [...buckets.entries()].sort(([left], [right]) => left - right);
  sightingsChart.data.labels = entries.map(([hourStart]) => formatHourLabel(hourStart));
  sightingsChart.data.datasets[0].data = entries.map(([, count]) => count);
  sightingsChart.update();

  elements.sightingsTotal.textContent = `${recent.length} / 24h`;
}

function makePhotoEl(imageUrl, missingClass, caption = '') {
  const photo = document.createElement('div');
  photo.className = 'visit-photo';
  if (imageUrl) {
    const img = document.createElement('img');
    img.loading = 'lazy';
    img.alt = 'Camera frame';
    img.src = imageUrl;
    // A vision frame can be gone (S3 lifecycle) → fall back to the missing tile.
    img.addEventListener('error', () => { photo.classList.add(missingClass); img.remove(); });
    img.addEventListener('click', () => openLightbox(imageUrl, caption));
    photo.appendChild(img);
  } else {
    photo.classList.add(missingClass);
  }
  return photo;
}

function openLightbox(src, caption = '') {
  elements.lightboxImg.src = src;
  elements.lightboxCaption.textContent = caption;
  elements.lightbox.hidden = false;
}

function closeLightbox() {
  elements.lightbox.hidden = true;
  elements.lightboxImg.removeAttribute('src');
}

// Sightings closer together in time than this belong to the same visit — Zeus
// sitting in one spot produces many near-identical frames, so we collapse a run
// of them into one card showing the time span instead of N duplicate cards.
const VISIT_GAP_MS = 15 * 60 * 1000;

function clockOnly(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function groupIntoVisits(items) {
  // `items` arrive newest-first; start a new visit whenever the gap to the
  // previous (more recent) sighting exceeds VISIT_GAP_MS.
  const groups = [];
  let current = [];
  items.forEach((item) => {
    const prev = current[current.length - 1];
    if (prev && (prev.ts - item.ts) * 1000 > VISIT_GAP_MS) {
      groups.push(current);
      current = [];
    }
    current.push(item);
  });
  if (current.length) groups.push(current);
  return groups;
}

function buildVisitCard(group) {
  const rep = group[0];                          // newest sighting = representative photo
  const payload = rep.payload || {};
  const withOthers = group.some((g) => (g.payload || {}).others_present === true);
  const isManual = group.every((g) => (g.payload || {}).source === 'manual');
  const startTs = group[group.length - 1].ts;    // oldest in the visit
  const endTs = group[0].ts;                      // newest in the visit
  const count = group.length;
  const timeText = count > 1 ? `${formatTime(startTs)} – ${clockOnly(endTs)}` : formatTime(endTs);

  const card = document.createElement('article');
  card.className = 'visit-card';
  if (withOthers) card.classList.add('visit-card--alert');
  if (isManual) card.classList.add('visit-card--manual');

  const caption = `${withOthers ? 'Zeus + another animal' : 'Zeus'} · ${timeText}${payload.zone ? ' · ' + payload.zone : ''}`;
  const photo = makePhotoEl(rep.image_url, isManual ? 'visit-photo--manual' : 'visit-photo--missing', caption);
  if (withOthers) {
    const flag = document.createElement('span');
    flag.className = 'visit-flag';
    const n = Number(payload.animal_count) || 2;
    flag.textContent = `Another animal · ${n} in frame`;
    photo.appendChild(flag);
  }
  card.appendChild(photo);

  const body = document.createElement('div');
  body.className = 'visit-body';

  const title = document.createElement('p');
  title.className = 'visit-title';
  title.textContent = withOthers ? 'Zeus + another animal' : isManual ? 'Manual check-in' : 'Zeus was here';
  body.appendChild(title);

  const time = document.createElement('p');
  time.className = 'visit-time';
  time.textContent = timeText;
  body.appendChild(time);

  const meta = document.createElement('p');
  meta.className = 'visit-meta';
  if (count > 1) {
    meta.textContent = `${count} sightings · ${payload.zone || '--'}`;
  } else {
    const conf = payload.confidence;
    const confText = conf != null ? `${Math.round(Number(conf) * 100)}% match · ` : '';
    meta.textContent = `${confText}${payload.zone || '--'} · ${payload.source || '--'}`;
  }
  body.appendChild(meta);

  card.appendChild(body);
  return card;
}

function renderVisits(sightings) {
  const visits = groupIntoVisits(sightings);
  elements.visitsCount.textContent = visits.length ? `${visits.length} visit${visits.length > 1 ? 's' : ''}` : '--';
  elements.visitsGallery.replaceChildren();

  if (!visits.length) {
    const empty = document.createElement('p');
    empty.className = 'visits-empty';
    empty.textContent = 'No sightings yet — start the edge bridge when Zeus is around.';
    elements.visitsGallery.appendChild(empty);
    return;
  }
  visits.forEach((group) => elements.visitsGallery.appendChild(buildVisitCard(group)));
}

function buildIntruderCard(item) {
  const payload = item.payload || {};
  const count = Number(payload.animal_count) || 1;

  const card = document.createElement('article');
  card.className = 'visit-card visit-card--alert';
  card.appendChild(
    makePhotoEl(item.image_url, 'visit-photo--missing', `Another animal · ${formatTime(item.ts)} · ${payload.zone || ''}`)
  );

  const body = document.createElement('div');
  body.className = 'visit-body';

  const title = document.createElement('p');
  title.className = 'visit-title';
  title.textContent = 'Another animal';
  body.appendChild(title);

  const time = document.createElement('p');
  time.className = 'visit-time';
  time.textContent = formatTime(item.ts);
  body.appendChild(time);

  const meta = document.createElement('p');
  meta.className = 'visit-meta';
  const conf = payload.confidence;
  const confText = conf != null ? `${Math.round(Number(conf) * 100)}% conf · ` : '';
  meta.textContent = `${count} in frame · ${confText}${payload.zone || '--'}`;
  body.appendChild(meta);

  card.appendChild(body);
  return card;
}

function renderIntruders(intruders) {
  elements.intrudersCount.textContent = intruders.length ? `${intruders.length} recent` : '--';
  elements.intrudersGallery.replaceChildren();

  if (!intruders.length) {
    const empty = document.createElement('p');
    empty.className = 'visits-empty';
    empty.textContent = 'No intruders detected.';
    elements.intrudersGallery.appendChild(empty);
    return;
  }
  intruders.forEach((item) => elements.intrudersGallery.appendChild(buildIntruderCard(item)));
}

function updateScrollButtons(scroller) {
  const gallery = scroller.querySelector('.visits-gallery');
  const prev = scroller.querySelector('.scroll-prev');
  const next = scroller.querySelector('.scroll-next');
  const overflow = gallery.scrollWidth - gallery.clientWidth;
  const scrollable = overflow > 2;
  prev.hidden = !scrollable || gallery.scrollLeft <= 1;      // hide "newer" at the left edge
  next.hidden = !scrollable || gallery.scrollLeft >= overflow - 1; // hide "older" at the right edge
}

function refreshScrollers() {
  document.querySelectorAll('.gallery-scroller').forEach(updateScrollButtons);
}

function wireScrollers() {
  document.querySelectorAll('.gallery-scroller').forEach((scroller) => {
    const gallery = scroller.querySelector('.visits-gallery');
    const amount = () => Math.max(gallery.clientWidth * 0.8, 240);
    scroller.querySelector('.scroll-prev').addEventListener('click', () =>
      gallery.scrollBy({ left: -amount(), behavior: 'smooth' }));
    scroller.querySelector('.scroll-next').addEventListener('click', () =>
      gallery.scrollBy({ left: amount(), behavior: 'smooth' }));
    gallery.addEventListener('scroll', () => updateScrollButtons(scroller));
  });
  window.addEventListener('resize', refreshScrollers);
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
    const [state, feedings, sightings, visits, intruders] = await Promise.all([
      fetchEntityState(),
      fetchEventsByType('feeding'),
      fetchEventsByType('sighting'),
      fetchRecentVisits(),
      fetchRecentIntrusions(),
    ]);
    renderWelfare(state);
    renderLastSeen(state);
    renderIntake(feedings);
    renderSightings(sightings);
    renderVisits(visits);
    renderIntruders(intruders);
    refreshScrollers();
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
  wireScrollers();
  elements.refreshButton.addEventListener('click', refreshDashboard);
  // Lightbox: click anywhere on the overlay to close, or press Escape.
  elements.lightbox.addEventListener('click', closeLightbox);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !elements.lightbox.hidden) closeLightbox();
  });
  refreshDashboard();
  startAutoRefresh();
});
