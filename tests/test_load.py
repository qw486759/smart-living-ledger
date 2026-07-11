import logging
import requests
import time
import threading

TOTAL_EVENTS = 100
DURATION_SECONDS = 10

DEVICE_TYPES = [
    {"type": "motion", "payload": {"detected": True}},
    {"type": "plug", "payload": {"watt": 500.0}},
    {"type": "temp", "payload": {"celsius": 22.0, "humidity": 55.0}},
    {"type": "voice", "payload": {"command": "status check"}},
]

logger = logging.getLogger(__name__)

results = []
results_lock = threading.Lock()


def send_event(ingest_url, device_num):
    device_type = DEVICE_TYPES[device_num % len(DEVICE_TYPES)]
    payload = {
        "device_id": f"loadtest-device-{device_num:03d}",
        "type": device_type["type"],
        "payload": device_type["payload"],
        "ts": int(time.time()),
    }
    try:
        r = requests.post(ingest_url, json=payload, timeout=15)
        with results_lock:
            results.append(r.status_code)
    except Exception:
        with results_lock:
            results.append(0)  # 0 = connection error


def test_accepts_100_events_without_throttling(ingest_url):
    global results
    results = []

    threads = []
    interval = DURATION_SECONDS / TOTAL_EVENTS  # 0.1s between each

    start = time.time()

    for i in range(TOTAL_EVENTS):
        t = threading.Thread(target=send_event, args=(ingest_url, i))
        t.start()
        threads.append(t)
        time.sleep(interval)

    for t in threads:
        t.join(timeout=20)

    elapsed = time.time() - start

    total = len(results)
    success = results.count(200)
    failed = total - success
    errors = results.count(0)

    logger.info(
        "load_test_completed",
        extra={
            "total": total,
            "success": success,
            "failed_http": failed - errors,
            "connection_errors": errors,
            "elapsed_seconds": round(elapsed, 1),
        },
    )

    assert total == TOTAL_EVENTS, f"Only {total}/{TOTAL_EVENTS} requests completed"
    assert (
        success == TOTAL_EVENTS
    ), f"{failed} requests failed: status codes = {set(results)}"
