import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError
from rules import ARRIVAL_GAP_SECONDS, evaluate, format_alert_message, is_new_arrival

logger = logging.getLogger()
logger.setLevel(logging.INFO)

METRIC_NAMESPACE = "EventDrivenIotPlatform"
STAGE = os.environ.get("STAGE", "dev")
ALERT_TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN")
PROJECTION_TABLE_NAME = os.environ.get("PROJECTION_TABLE_NAME")
ARRIVAL_GAP = int(os.environ.get("ARRIVAL_GAP_SECONDS", str(ARRIVAL_GAP_SECONDS)))
INTRUDER_GAP = int(os.environ.get("INTRUDER_GAP_SECONDS", str(ARRIVAL_GAP_SECONDS)))
# The alerter owns these state items to dedupe per-visit notices — separate key
# space from the entity projection (ENTITY#<id>), so it never races the projection
# writer. One marks Zeus's presence (arrivals), one marks any other animal at the
# door (co-presence or a solo intruder).
ARRIVAL_STATE_PK = "ALERT#zeus"
INTRUDER_STATE_PK = "ALERT#intruder"
ARRIVAL_STATE_SK = "STATE"
# "Another animal at the door" alerts, deduped per visit; other anomalies fire per hit.
INTRUDER_RULES = {"co_presence", "intruder_solo"}

cloudwatch = boto3.client("cloudwatch")
sns = boto3.client("sns")
projection_table = (
    boto3.resource("dynamodb").Table(PROJECTION_TABLE_NAME)
    if PROJECTION_TABLE_NAME
    else None
)


def lambda_handler(event: dict, context: Any) -> dict:
    """Evaluate each event-stored SNS message against the anomaly rules; on a
    hit, emit a structured log and a CloudWatch custom metric (observable in
    CloudWatch rather than an external notification channel)."""
    alerts = 0

    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])

        anomaly = evaluate(message["type"], message.get("payload", {}))
        if anomaly:
            rule = anomaly["rule"]
            # An "animal at the door" alert (co-presence or solo intruder) is
            # deduped per visit so a lingering cat doesn't alert every heartbeat;
            # other anomalies (temp/plug) fire on every hit.
            intruder_new = rule not in INTRUDER_RULES or _is_new_visit(
                message, INTRUDER_STATE_PK, INTRUDER_GAP
            )
            if intruder_new:
                alerts += 1
                _log(
                    "warning",
                    "anomaly_detected",
                    device_id=message.get("device_id"),
                    event_type=message["type"],
                    rule=rule,
                    detail=anomaly["detail"],
                    ts=message.get("ts"),
                )
                _publish_alert(anomaly, message, "Zeus welfare alert")

        # Stateful: first camera sighting of a new visit -> "Zeus is here" notice.
        arrival = _check_arrival(message)
        if arrival:
            alerts += 1
            _log(
                "info",
                "zeus_arrival",
                device_id=message.get("device_id"),
                detail=arrival["detail"],
                ts=message.get("ts"),
            )
            _publish_alert(arrival, message, "Zeus is here")

    return {"alerts": alerts}


def _check_arrival(message: dict) -> dict | None:
    """Return an `arrival` anomaly if this camera sighting starts a new visit."""
    if message.get("type") != "sighting":
        return None
    payload = message.get("payload", {})
    # Only real camera detections count as an arrival; manual check-ins mean the
    # human already saw Zeus and don't need to notify themselves.
    if payload.get("source") != "vision":
        return None
    if not _is_new_visit(message, ARRIVAL_STATE_PK, ARRIVAL_GAP):
        return None
    zone = payload.get("zone")
    return {"rule": "arrival", "detail": f"at {zone}" if zone else None}


def _is_new_visit(message: dict, state_pk: str, gap: int) -> bool:
    """True if this event begins a new visit for the given state marker. Without a
    usable timestamp we can't dedupe, so err on the side of notifying."""
    ts = _event_ts(message)
    if ts is None:
        return True
    return _advance_visit_state(state_pk, ts, gap) is True


def _advance_visit_state(state_pk: str, ts: int, gap: int) -> bool | None:
    """Conditionally advance a per-visit last-seen marker, atomically. Returns True
    if `ts` starts a new visit, False if it continues the current one, or None if
    it's an out-of-order/duplicate delivery (or no table) and should be ignored.

    The conditional UpdateItem means only the record that actually advances the
    timestamp proceeds, so concurrent deliveries can't double-fire."""
    if projection_table is None:
        return None
    try:
        response = projection_table.update_item(
            Key={"pk": state_pk, "device_id": ARRIVAL_STATE_SK},
            UpdateExpression="SET last_seen_ts = :ts",
            ConditionExpression="attribute_not_exists(last_seen_ts) OR last_seen_ts < :ts",
            ExpressionAttributeValues={":ts": ts},
            ReturnValues="UPDATED_OLD",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    old = response.get("Attributes", {}).get("last_seen_ts")
    prev_seen_ts = int(old) if old is not None else None
    return is_new_arrival(prev_seen_ts, ts, gap)


def _event_ts(message: dict) -> int | None:
    ts = message.get("ts")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    return int(ts)


def _publish_alert(anomaly: dict, message: dict, subject: str) -> None:
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
    if ALERT_TOPIC_ARN:
        sns.publish(
            TopicArn=ALERT_TOPIC_ARN,
            Subject=subject,
            Message=format_alert_message(
                anomaly,
                device_id=message.get("device_id", ""),
            ),
        )


def _log(level: str, event: str, **context: Any) -> None:
    payload = {"event": event, **{k: v for k, v in context.items() if v is not None}}
    getattr(logger, level)(json.dumps(payload, sort_keys=True))
