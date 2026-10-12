"""Incident Service: scores metrics, opens/closes incidents, stores the Incident Replay timeline."""
import json
import logging
import os
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, String, Table, insert,
                        select, update)

from . import ml
from .auth import ALL_ROLES, require_role
from .db import init_db, iso, make_engine, utcnow
from .risk import Sample, explain

log = logging.getLogger("incident")
logging.basicConfig(level=logging.INFO)

REMEDIATION_URL = os.getenv("REMEDIATION_URL", "http://localhost:8003")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN", "")      # optional direct email (no Lambda)
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")      # preferred: queue -> Lambda -> SNS email
NORMAL_SAMPLES_TO_RESOLVE = int(os.getenv("NORMAL_SAMPLES_TO_RESOLVE", "3"))

app = FastAPI(title="Incident Service")
engine = make_engine()
metadata = MetaData()

incidents = Table(
    "incidents", metadata,
    Column("id", String(40), primary_key=True),
    Column("service", String(80), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("risk_score", Float, nullable=False),
    Column("status", String(20), nullable=False, default="open"),
    Column("opened_at", DateTime, nullable=False),
    Column("resolved_at", DateTime),
    Column("normal_streak", Integer, nullable=False, default=0),
)
incident_events = Table(
    "incident_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(40), nullable=False, index=True),
    Column("event_type", String(60), nullable=False),
    Column("message", String(500), nullable=False),
    Column("ts", DateTime, nullable=False),
)

LATEST: dict[str, dict] = {}  # latest evaluation per service (live view only)


@app.on_event("startup")
def _startup():
    init_db(metadata, engine)


class Snapshot(BaseModel):
    service: str
    cpu: float = Field(ge=0, le=100)
    memory: float = Field(ge=0, le=100)
    latency_ms: float = Field(ge=0)
    error_rate: float = Field(ge=0, le=100)
    request_count: float = Field(ge=0)


class EventIn(BaseModel):
    event_type: str
    message: str


# ---------- helpers ----------
def add_event(conn, incident_id: str, event_type: str, message: str):
    conn.execute(insert(incident_events).values(
        incident_id=incident_id, event_type=event_type, message=message, ts=utcnow()))


def _new_incident_id(conn) -> str:
    prefix = f"INC-{datetime.now():%Y-%m%d}-"
    rows = conn.execute(select(incidents.c.id).where(incidents.c.id.like(prefix + "%"))).all()
    return f"{prefix}{len(rows) + 1:03d}"


def _post(url: str, payload: dict):
    """Best-effort call to another service. Never crashes incident handling."""
    try:
        httpx.post(url, json=payload, timeout=3,
                   headers={"X-Internal-Key": os.getenv("INTERNAL_KEY", "")})
    except Exception as exc:  # noqa: BLE001
        log.warning("call to %s failed: %s", url, exc)


def alert_channel() -> str:
    if SQS_QUEUE_URL:
        return "queued to SQS -> Lambda -> SNS email"
    if SNS_TOPIC_ARN:
        return "published to SNS email"
    return "logged only (no SQS/SNS configured)"


def notify(incident: dict, sqs_client=None):
    """Alert: always log it; send to the SQS queue (Lambda emails it) if configured."""
    log.warning("ALERT [%s] %s on %s risk=%s", incident["severity"], incident["id"],
                incident["service"], incident["risk_score"])
    try:
        if SQS_QUEUE_URL:
            client = sqs_client
            if client is None:
                import boto3
                client = boto3.client("sqs")
            client.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(incident))
        elif SNS_TOPIC_ARN:
            import boto3
            boto3.client("sns").publish(
                TopicArn=SNS_TOPIC_ARN, Subject="CloudPulse incident", Message=json.dumps(incident))
    except Exception as exc:  # noqa: BLE001
        log.warning("alert delivery failed: %s", exc)


def row_to_dict(r) -> dict:
    d = dict(r._mapping)
    for k in ("opened_at", "resolved_at", "ts"):
        if k in d:
            d[k] = iso(d[k])
    return d


# ---------- endpoints ----------
@app.get("/health")
def health():
    return {"status": "ok", "service": "incident-service", "ml_model": ml.predict(
        {"cpu": 1, "memory": 1, "latency_ms": 1, "error_rate": 0, "request_count": 1})["available"]}


@app.post("/predict")
def predict(s: Snapshot, _: dict = Depends(require_role(*ALL_ROLES))):
    return {"service": s.service, **{k: v for k, v in ml.predict(s.model_dump()).items()
                                     if k != "available"}}


@app.post("/evaluate")
def evaluate(s: Snapshot, _: dict = Depends(require_role("automation", "admin"))):
    snap = s.model_dump()
    rule = explain(Sample(s.cpu, s.memory, s.latency_ms, s.error_rate, s.request_count))
    mlr = ml.predict(snap)
    severity = rule["severity"]
    triggered = severity in ("High", "Critical") or (severity == "Moderate" and mlr["anomaly"])

    result = {"service": s.service, **rule, "ml": mlr, "incident_id": None, "action": "none"}

    after_commit = []   # calls to other services run only AFTER the database commit

    with engine.begin() as conn:
        open_inc = conn.execute(select(incidents).where(
            incidents.c.service == s.service, incidents.c.status == "open")).first()

        if triggered and open_inc is None:
            inc_id = _new_incident_id(conn)
            conn.execute(insert(incidents).values(
                id=inc_id, service=s.service, severity=severity, risk_score=rule["risk_score"],
                status="open", opened_at=utcnow(), normal_streak=0))
            for name, comp in rule["components"].items():
                if comp >= 60:
                    add_event(conn, inc_id, f"signal_{name}",
                              f"{name} risk {comp:.0f}/100 ({_raw(name, snap)})")
            add_event(conn, inc_id, "anomaly_detected",
                      f"Rules: risk {rule['risk_score']} ({severity}). "
                      f"Top signals: {', '.join(rule['top_signals'])}")
            if mlr["available"]:
                add_event(conn, inc_id, "ml_score_recorded",
                          f"ML anomaly={mlr['anomaly']} score={mlr['anomaly_score']} "
                          f"signals={mlr['signals']}")
            add_event(conn, inc_id, "incident_created",
                      f"Incident {inc_id} opened, severity {severity}")
            add_event(conn, inc_id, "alert_generated", f"Alert {alert_channel()}")
            result.update(incident_id=inc_id, action="incident_created")
            incident = {"id": inc_id, "service": s.service, "severity": severity,
                        "risk_score": rule["risk_score"], "top_signals": rule["top_signals"],
                        "ml_anomaly": mlr["anomaly"], "opened_at": iso(utcnow()),
                        "dashboard_url": os.getenv("DASHBOARD_URL", "")}
            after_commit.append(lambda: notify(incident))
            after_commit.append(lambda: _post(
                f"{REMEDIATION_URL}/remediations/recommend",
                {"incident_id": inc_id, "service": s.service, "top_signals": rule["top_signals"]}))

        elif open_inc is not None:
            result["incident_id"] = open_inc.id
            if triggered or severity != "Low":
                conn.execute(update(incidents).where(incidents.c.id == open_inc.id).values(
                    normal_streak=0, risk_score=max(open_inc.risk_score, rule["risk_score"])))
                result["action"] = "incident_ongoing"
            else:
                streak = open_inc.normal_streak + 1
                if streak >= NORMAL_SAMPLES_TO_RESOLVE:
                    add_event(conn, open_inc.id, "metrics_normalized",
                              f"Risk back to Low ({rule['risk_score']}) for {streak} samples")
                    add_event(conn, open_inc.id, "incident_resolved", "Incident resolved automatically")
                    conn.execute(update(incidents).where(incidents.c.id == open_inc.id).values(
                        status="resolved", resolved_at=utcnow(), normal_streak=streak))
                    result["action"] = "incident_resolved"
                    resolved_id = open_inc.id
                    after_commit.append(lambda: _post(
                        f"{REMEDIATION_URL}/remediations/verify/{resolved_id}", {}))
                else:
                    conn.execute(update(incidents).where(incidents.c.id == open_inc.id).values(
                        normal_streak=streak))
                    result["action"] = "recovering"

    for call in after_commit:
        call()

    LATEST[s.service] = {**result, "health_score": round(100 - rule["risk_score"], 1),
                         "metrics": snap, "updated_at": iso(utcnow())}
    return result


def _raw(name: str, snap: dict) -> str:
    key = {"cpu": "cpu", "memory": "memory", "latency": "latency_ms",
           "error": "error_rate", "traffic": "request_count"}[name]
    return f"{key}={snap[key]:.1f}"


@app.get("/latest")
def latest(_: dict = Depends(require_role(*ALL_ROLES))):
    return list(LATEST.values())


@app.get("/incidents")
def list_incidents(status: str | None = None, _: dict = Depends(require_role(*ALL_ROLES))):
    q = select(incidents).order_by(incidents.c.opened_at.desc())
    if status:
        q = q.where(incidents.c.status == status)
    with engine.connect() as conn:
        return [row_to_dict(r) for r in conn.execute(q)]


@app.get("/incidents/{incident_id}/replay")
def replay(incident_id: str, _: dict = Depends(require_role(*ALL_ROLES))):
    with engine.connect() as conn:
        inc = conn.execute(select(incidents).where(incidents.c.id == incident_id)).first()
        if inc is None:
            raise HTTPException(404, "incident not found")
        events = conn.execute(select(incident_events).where(
            incident_events.c.incident_id == incident_id).order_by(
            incident_events.c.ts, incident_events.c.id)).all()
    return {"incident": row_to_dict(inc), "events": [row_to_dict(e) for e in events]}


@app.post("/incidents/{incident_id}/events")
def add_incident_event(incident_id: str, e: EventIn,
                       _: dict = Depends(require_role("automation", "admin"))):
    with engine.begin() as conn:
        if conn.execute(select(incidents.c.id).where(incidents.c.id == incident_id)).first() is None:
            raise HTTPException(404, "incident not found")
        add_event(conn, incident_id, e.event_type, e.message)
    return {"ok": True}


@app.post("/incidents/{incident_id}/resolve")
def resolve(incident_id: str, user: dict = Depends(require_role("admin", "analyst"))):
    with engine.begin() as conn:
        inc = conn.execute(select(incidents).where(incidents.c.id == incident_id)).first()
        if inc is None:
            raise HTTPException(404, "incident not found")
        if inc.status == "resolved":
            return {"ok": True, "status": "resolved"}
        add_event(conn, incident_id, "incident_resolved", f"Incident resolved manually by {user['name']}")
        conn.execute(update(incidents).where(incidents.c.id == incident_id).values(
            status="resolved", resolved_at=utcnow()))
    return {"ok": True, "status": "resolved"}
