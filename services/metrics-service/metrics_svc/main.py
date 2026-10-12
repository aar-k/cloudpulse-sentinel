"""Metrics Service: receives metrics, stores them in the database, forwards them for scoring."""
import json
import logging
import os
import uuid

import httpx
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, insert, select

from .analytics import waste_report
from .auth import ALL_ROLES, require_role
from .db import init_db, iso, make_engine, utcnow

log = logging.getLogger("metrics")
logging.basicConfig(level=logging.INFO)

INCIDENT_URL = os.getenv("INCIDENT_URL", "http://localhost:8002")
S3_BUCKET = os.getenv("S3_BUCKET", "")          # optional: archive raw metrics to S3
S3_BATCH_SIZE = int(os.getenv("S3_BATCH_SIZE", "50"))

app = FastAPI(title="Metrics Service")
engine = make_engine()
metadata = MetaData()
metrics = Table(
    "metrics", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("service", String(80), nullable=False, index=True),
    Column("ts", DateTime, nullable=False, index=True),
    Column("cpu", Float, nullable=False),
    Column("memory", Float, nullable=False),
    Column("latency_ms", Float, nullable=False),
    Column("error_rate", Float, nullable=False),
    Column("request_count", Float, nullable=False),
)

_buffer: list[dict] = []


class Metric(BaseModel):
    service: str
    cpu: float = Field(ge=0, le=100)
    memory: float = Field(ge=0, le=100)
    latency_ms: float = Field(ge=0)
    error_rate: float = Field(ge=0, le=100)
    request_count: float = Field(ge=0)


@app.on_event("startup")
def _startup():
    init_db(metadata, engine)


def flush_to_s3(client=None) -> int:
    """Upload buffered raw metrics to S3 as one JSON-lines object. Returns rows uploaded."""
    if not S3_BUCKET or not _buffer:
        return 0
    rows = list(_buffer)
    try:
        if client is None:
            import boto3
            client = boto3.client("s3")
        key = f"raw-metrics/{utcnow():%Y-%m-%d}/{uuid.uuid4().hex}.jsonl"
        body = "\n".join(json.dumps(r) for r in rows).encode()
        client.put_object(Bucket=S3_BUCKET, Key=key, Body=body)
        _buffer.clear()
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        log.warning("S3 upload failed (will retry later): %s", exc)
        return 0


@app.get("/health")
def health():
    return {"status": "ok", "service": "metrics-service", "s3_archive": bool(S3_BUCKET)}


@app.post("/metrics")
def ingest(m: Metric, _: dict = Depends(require_role("automation", "admin", "developer"))):
    row = m.model_dump()
    ts = utcnow()
    with engine.begin() as conn:
        conn.execute(insert(metrics).values(ts=ts, **row))
    if S3_BUCKET:
        _buffer.append({"ts": iso(ts), **row})
        if len(_buffer) >= S3_BATCH_SIZE:
            flush_to_s3()
    try:
        r = httpx.post(f"{INCIDENT_URL}/evaluate", json=row, timeout=5,
                       headers={"X-Internal-Key": os.getenv("INTERNAL_KEY", "")})
        return r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("incident-service unreachable: %s", exc)
        return {"stored": True, "evaluation": "incident-service unavailable"}


@app.get("/metrics/{service}")
def recent(service: str, limit: int = 120, _: dict = Depends(require_role(*ALL_ROLES))):
    q = (select(metrics).where(metrics.c.service == service)
         .order_by(metrics.c.ts.desc(), metrics.c.id.desc()).limit(limit))
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(q)]
    for r in rows:
        r["ts"] = iso(r["ts"])
    return list(reversed(rows))


@app.get("/analytics/waste")
def waste(hours: int = 24, cpu_threshold: float = 10.0, _: dict = Depends(require_role(*ALL_ROLES))):
    """Cost/waste intelligence: average and peak utilization, flagged under-used services."""
    with engine.connect() as conn:
        return waste_report(conn, metrics, hours=hours, cpu_threshold=cpu_threshold)
