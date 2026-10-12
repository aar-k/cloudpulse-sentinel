"""AWS Lambda: turns an incident message from the SQS queue into an email through SNS.

Setup (see the guide): Python 3.12 runtime, environment variable SNS_TOPIC_ARN,
SQS queue as the trigger. Paste this whole file into the Lambda console editor.
"""
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def build_message(incident: dict) -> tuple[str, str]:
    subject = f"[{incident.get('severity', '?')}] CloudPulse incident {incident.get('id', '?')} on {incident.get('service', '?')}"
    lines = [
        f"Incident:   {incident.get('id')}",
        f"Service:    {incident.get('service')}",
        f"Severity:   {incident.get('severity')}",
        f"Risk score: {incident.get('risk_score')} / 100",
        f"Top signals: {', '.join(incident.get('top_signals', []))}",
        f"ML anomaly: {incident.get('ml_anomaly')}",
        f"Opened at:  {incident.get('opened_at')}",
    ]
    if incident.get("dashboard_url"):
        lines.append(f"Dashboard:  {incident['dashboard_url']}")
    return subject[:100], "\n".join(lines)


def handler(event, context=None, sns_client=None):
    client = sns_client or boto3.client("sns")
    topic_arn = os.environ["SNS_TOPIC_ARN"]
    records = event.get("Records", [])
    for record in records:
        incident = json.loads(record["body"])
        subject, message = build_message(incident)
        client.publish(TopicArn=topic_arn, Subject=subject, Message=message)
        logger.info("notification sent for %s", incident.get("id"))
    return {"processed": len(records)}
