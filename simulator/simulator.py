import json
import logging
import os
import random
import threading
import time
from typing import Any, Callable

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_raw_url = os.environ.get("SLL_INGEST_URL", "").strip()
if not _raw_url:
    raise RuntimeError(
        "SLL_INGEST_URL environment variable is not set.\n"
        "Run with: $env:SLL_INGEST_URL='https://your-api-url/dev'"
    )
BASE_URL = _raw_url.rstrip("/")
INGEST_URL = f"{BASE_URL}/events"

RETRY_LIMIT = 3
BASE_RETRY_DELAY_SECONDS = 0.5
MAX_RETRY_DELAY_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 5

PayloadFactory = Callable[[], dict[str, Any]]


def make_motion_payload() -> dict[str, bool]:
    return {"detected": random.choice([True, False])}


def make_plug_payload() -> dict[str, float]:
    return {"watt": round(random.uniform(0.0, 2400.0), 2)}


def make_temp_payload() -> dict[str, float]:
    return {
        "celsius": round(random.uniform(18.0, 30.0), 2),
        "humidity": round(random.uniform(40.0, 80.0), 2),
    }


def make_voice_payload() -> dict[str, str]:
    return {
        "command": random.choice(["turn on lights", "set temperature", "status check"])
    }


DEVICE_CONFIG = [
    {
        "device_id": "motion-sensor-001",
        "type": "motion",
        "payload_fn": make_motion_payload,
    },
    {"device_id": "smart-plug-001", "type": "plug", "payload_fn": make_plug_payload},
    {"device_id": "temp-sensor-001", "type": "temp", "payload_fn": make_temp_payload},
    {
        "device_id": "voice-device-001",
        "type": "voice",
        "payload_fn": make_voice_payload,
    },
]


def send_event(event: dict[str, Any]) -> bool:
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = requests.post(
                INGEST_URL, json=event, timeout=REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code == 200:
                _log_event("info", "event_delivered", event, attempt=attempt)
                return True

            _log_event(
                "warning",
                "event_rejected",
                event,
                attempt=attempt,
                status_code=response.status_code,
                response_body=response.text[:200],
            )
        except requests.exceptions.Timeout:
            _log_event("warning", "event_delivery_timeout", event, attempt=attempt)
        except requests.exceptions.ConnectionError as exc:
            _log_event(
                "warning",
                "event_delivery_connection_error",
                event,
                attempt=attempt,
                error=str(exc),
            )

        if attempt < RETRY_LIMIT:
            delay = _retry_delay_seconds(attempt)
            _log_event(
                "info",
                "event_retry_scheduled",
                event,
                attempt=attempt,
                delay_seconds=delay,
            )
            time.sleep(delay)

    _write_dead_letter(event)
    _log_event("error", "event_delivery_failed", event, attempts=RETRY_LIMIT)
    return False


DEAD_LETTER_PATH = os.path.join(os.path.dirname(__file__), "dead_letter.jsonl")


def _write_dead_letter(event: dict[str, Any]) -> None:
    try:
        with open(DEAD_LETTER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        logger.info(
            json.dumps(
                {
                    "event": "dead_letter_written",
                    "device_id": event.get("device_id"),
                    "ts": event.get("ts"),
                    "path": DEAD_LETTER_PATH,
                }
            )
        )
    except OSError as exc:
        logger.error(
            json.dumps(
                {
                    "event": "dead_letter_write_failed",
                    "device_id": event.get("device_id"),
                    "ts": event.get("ts"),
                    "error": str(exc),
                }
            )
        )


def _retry_delay_seconds(attempt: int) -> float:
    exponential_delay = BASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
    jitter = random.uniform(0, BASE_RETRY_DELAY_SECONDS)
    return round(min(exponential_delay + jitter, MAX_RETRY_DELAY_SECONDS), 3)


def device_loop(config: dict[str, Any]) -> None:
    device_id = config["device_id"]
    event_type = config["type"]
    payload_fn: PayloadFactory = config["payload_fn"]

    logger.info(
        json.dumps(
            {
                "event": "device_loop_started",
                "device_id": device_id,
                "event_type": event_type,
            }
        )
    )

    while True:
        event = {
            "device_id": device_id,
            "type": event_type,
            "payload": payload_fn(),
            "ts": int(time.time()),
        }
        send_event(event)
        time.sleep(random.uniform(1, 5))


def main() -> None:
    logger.info(
        json.dumps(
            {
                "event": "simulator_started",
                "device_count": len(DEVICE_CONFIG),
                "ingest_url": INGEST_URL,
            }
        )
    )

    for config in DEVICE_CONFIG:
        thread = threading.Thread(
            target=device_loop,
            args=(config,),
            name=config["device_id"],
            daemon=True,
        )
        thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info(
            json.dumps({"event": "simulator_stopped", "reason": "keyboard_interrupt"})
        )


def _log_event(
    level: str, event_name: str, event: dict[str, Any], **context: Any
) -> None:
    payload = {
        "event": event_name,
        "device_id": event.get("device_id"),
        "event_type": event.get("type"),
        "ts": event.get("ts"),
        **context,
    }
    getattr(logger, level)(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
