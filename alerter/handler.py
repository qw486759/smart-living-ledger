import json
import logging
import os
from typing import Any

import boto3
from rules import evaluate

logger = logging.getLogger()
logger.setLevel(logging.INFO)

METRIC_NAMESPACE = "SmartLivingLedger"
STAGE = os.environ.get("STAGE", "dev")

cloudwatch = boto3.client("cloudwatch")


def lambda_handler(event: dict, context: Any) -> dict:
    """Evaluate each event-stored SNS message against the anomaly rules; on a
    hit, emit a structured log and a CloudWatch custom metric (observable in
    CloudWatch rather than an external notification channel)."""
    alerts = 0

    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        anomaly = evaluate(message["type"], message.get("payload", {}))
        if not anomaly:
            continue

        alerts += 1
        _log(
            "warning",
            "anomaly_detected",
            device_id=message.get("device_id"),
            event_type=message["type"],
            rule=anomaly["rule"],
            detail=anomaly["detail"],
            ts=message.get("ts"),
        )
        cloudwatch.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AnomalyDetected",
                    "Dimensions": [
                        {"Name": "Stage", "Value": STAGE},
                        {"Name": "AnomalyType", "Value": anomaly["rule"]},
                    ],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )

    return {"alerts": alerts}


def _log(level: str, event: str, **context: Any) -> None:
    payload = {"event": event, **{k: v for k, v in context.items() if v is not None}}
    getattr(logger, level)(json.dumps(payload, sort_keys=True))
