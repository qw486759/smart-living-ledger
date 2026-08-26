const INGEST_BASE = (window.EIP_INGEST_BASE || '').replace(/\/$/, '');
const DEVICE_ID = 'manual';

const statusBanner = document.getElementById('status-banner');

function nowTs() {
  return Math.floor(Date.now() / 1000);
}

function showStatus(message, isError) {
  statusBanner.textContent = message;
  statusBanner.hidden = false;
  statusBanner.classList.toggle('is-error', Boolean(isError));
  statusBanner.classList.toggle('is-ok', !isError);
}

async function postEvent(evt) {
  if (!INGEST_BASE) {
    throw new Error('Missing ingest API base. Set window.EIP_INGEST_BASE in config.js.');
  }
  // 'text/plain' keeps this a CORS "simple request" — no preflight OPTIONS,
  // which the API Gateway doesn't expose. The body is still JSON; the ingest
  // Lambda json.loads() the raw body regardless of Content-Type.
  const response = await fetch(`${INGEST_BASE}/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
    body: JSON.stringify(evt),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body.error || `HTTP ${response.status}`;
    const code = body.code ? ` (${body.code})` : '';
    throw new Error(`${message}${code}`);
  }
  return body;
}

async function submitForm(event, buildEvent, label) {
  event.preventDefault();
  const button = event.target.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await postEvent(buildEvent(new FormData(event.target)));
    showStatus(`${label} logged ✓`, false);
    event.target.reset();
  } catch (error) {
    showStatus(`${label} failed: ${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('sighting-form').addEventListener('submit', (event) =>
    submitForm(
      event,
      (form) => ({
        device_id: DEVICE_ID,
        type: 'sighting',
        payload: { zone: form.get('zone'), confidence: 1.0, source: 'manual' },
        ts: nowTs(),
      }),
      'Sighting',
    ),
  );

  document.getElementById('feeding-form').addEventListener('submit', (event) =>
    submitForm(
      event,
      (form) => {
        const payload = { grams: Number(form.get('grams')) };
        const duration = form.get('duration_s');
        if (duration) payload.duration_s = Number(duration);
        return { device_id: DEVICE_ID, type: 'feeding', payload, ts: nowTs() };
      },
      'Feeding',
    ),
  );
});
