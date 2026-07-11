import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ingest import local_app  # noqa: E402


def test_local_ingest_app_writes_valid_event_to_jsonl(tmp_path, monkeypatch):
    events_file = tmp_path / "local_events.jsonl"
    monkeypatch.setattr(local_app, "EVENTS_FILE", events_file)
    client = TestClient(local_app.app)

    response = client.post(
        "/events",
        json={
            "device_id": "local-motion-001",
            "type": "motion",
            "payload": {"detected": True},
            "ts": 1_900_000_000,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"message": "ok", "device_id": "local-motion-001"}
    assert '"device_id":"local-motion-001"' in events_file.read_text()


def test_local_ingest_app_returns_validation_error_contract():
    client = TestClient(local_app.app)

    response = client.post(
        "/events",
        json={
            "device_id": "local-plug-001",
            "type": "plug",
            "payload": {"watt": -1},
            "ts": 1_900_000_000,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "watt" in response.json()["error"]
