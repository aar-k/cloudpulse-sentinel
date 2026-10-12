import json

import handler


class FakeSNS:
    def __init__(self):
        self.published = []

    def publish(self, **kw):
        self.published.append(kw)


def sqs_event(*incidents):
    return {"Records": [{"body": json.dumps(i)} for i in incidents]}


def test_lambda_publishes_one_email_per_incident(monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:ap-south-1:123:cloudpulse-alerts")
    fake = FakeSNS()
    inc = {"id": "INC-9", "service": "payment-api", "severity": "Critical", "risk_score": 93.0,
           "top_signals": ["cpu", "error"], "ml_anomaly": True, "opened_at": "2026-10-14T10:00:00Z"}
    result = handler.handler(sqs_event(inc, {**inc, "id": "INC-10"}), None, sns_client=fake)
    assert result == {"processed": 2}
    assert len(fake.published) == 2
    first = fake.published[0]
    assert first["TopicArn"].endswith("cloudpulse-alerts")
    assert "[Critical]" in first["Subject"] and "INC-9" in first["Subject"]
    assert "cpu, error" in first["Message"] and "93.0" in first["Message"]


def test_lambda_with_no_records_does_nothing(monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn")
    assert handler.handler({}, None, sns_client=FakeSNS()) == {"processed": 0}
