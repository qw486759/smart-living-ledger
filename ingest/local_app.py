import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ingest.schema import ValidationError, validate_event

EVENTS_FILE = Path("local_events.jsonl")

app = FastAPI(title="Smart Living Ledger Local Ingest")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/events", response_model=None)
async def ingest_event(request: Request):
    payload: dict[str, Any] = await request.json()

    try:
        event = validate_event(payload)
    except ValidationError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": str(exc), "code": "VALIDATION_ERROR"},
        )

    with EVENTS_FILE.open("a", encoding="utf-8") as event_file:
        event_file.write(json.dumps(event, separators=(",", ":")) + "\n")

    # Mirror the Lambda success contract (ingest/handler.py) exactly so the
    # local and cloud ingest paths can't silently drift.
    return {"status": "ok", "device_id": event["device_id"], "ts": event["ts"]}
