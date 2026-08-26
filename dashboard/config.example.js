// Copy this file to config.js and set your API Gateway URLs.
// config.js is intentionally excluded from version control (.gitignore).

// Query API base — the dashboard reads /state and /events from here.
window.EIP_API_BASE = 'https://YOUR_QUERY_API_ID.execute-api.YOUR_REGION.amazonaws.com/dev';

// Ingest API base — the manual check-in page (checkin.html) POSTs /events here.
window.EIP_INGEST_BASE = 'https://YOUR_INGEST_API_ID.execute-api.YOUR_REGION.amazonaws.com/dev';