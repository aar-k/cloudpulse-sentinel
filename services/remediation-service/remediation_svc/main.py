"""Remediation Service: recommend -> policy check -> human approval -> execute -> verify -> audit.

Only two SAFE, non-destructive actions exist. Anything else is rejected by the policy check.
The "execute" step acts on the demo service by switching its simulated fault off.
"""
import logging
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import (Boolean, Column, DateTime, Integer, MetaData, String, Table, insert,
                        select, update)

from .auth import ALL_ROLES, require_role
from .db import init_db, iso, make_engine, utcnow

log = logging.getLogger("remediation")
logging.basicConfig(level=logging.INFO)

INCIDENT_URL = os.getenv("INCIDENT_URL", "http://localhost:8002")
ALLOWED_ACTIONS = {"restart_service", "scale_service"}   # the whole allow-list

app = FastAPI(title="Remediation Service")
engine = make_engine()
metadata = MetaData()
remediations = Table(
    "remediations", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(40), nullable=False, index=True),
    Column("service", String(80), nullable=False),
    Column("action", String(60), nullable=False),
    Column("status", String(20), nullable=False),     # recommended/approved/executed/rejected
    Column("recommended_at", DateTime, nullable=False),
    Column("approved_by", String(80)),
    Column("approved_at", DateTime),
    Column("executed_at", DateTime),
    Column("result", String(300)),
    Column("verified", Boolean, nullable=False, default=False),
)
demo_state = Table(
    "demo_state", metadata,
    Column("service", String(80), primary_key=True),
    Column("fault", Boolean, nullable=False, default=False),
)


@app.on_event("startup")
def _startup():
    init_db(metadata, engine)


class RecommendIn(BaseModel):
    incident_id: str
    service: str
    top_signals: list[str] = []


class FaultIn(BaseModel):
    service: str
    on: bool


def _event(incident_id: str, event_type: str, message: str):
    try:
        httpx.post(f"{INCIDENT_URL}/incidents/{incident_id}/events",
                   json={"event_type": event_type, "message": message}, timeout=3,
                   headers={"X-Internal-Key": os.getenv("INTERNAL_KEY", "")})
    except Exception as exc:  # noqa: BLE001
        log.warning("could not write timeline event: %s", exc)


def _row(r) -> dict:
    d = dict(r._mapping)
    for k in ("recommended_at", "approved_at", "executed_at"):
        d[k] = iso(d[k])
    return d


def _get(conn, rid: int):
    r = conn.execute(select(remediations).where(remediations.c.id == rid)).first()
    if r is None:
        raise HTTPException(404, "remediation not found")
    return r


def policy_check(action: str):
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, f"Policy: action '{action}' is not on the allow-list "
                                 f"{sorted(ALLOWED_ACTIONS)}")


@app.get("/health")
def health():
    return {"status": "ok", "service": "remediation-service", "allowed_actions": sorted(ALLOWED_ACTIONS)}


# ----- demo fault switch (used by the simulator and dashboard) -----
@app.post("/demo/fault")
def set_fault(f: FaultIn, _: dict = Depends(require_role("admin", "analyst", "developer"))):
    with engine.begin() as conn:
        exists = conn.execute(select(demo_state).where(demo_state.c.service == f.service)).first()
        if exists:
            conn.execute(update(demo_state).where(demo_state.c.service == f.service).values(fault=f.on))
        else:
            conn.execute(insert(demo_state).values(service=f.service, fault=f.on))
    return {"service": f.service, "fault": f.on}


@app.get("/demo/state/{service}")
def get_state(service: str, _: dict = Depends(require_role(*ALL_ROLES))):
    with engine.connect() as conn:
        r = conn.execute(select(demo_state).where(demo_state.c.service == service)).first()
    return {"service": service, "fault": bool(r.fault) if r else False}


# ----- remediation flow -----
@app.post("/remediations/recommend")
def recommend(r: RecommendIn, _: dict = Depends(require_role("automation", "admin"))):
    signals = " ".join(r.top_signals)
    action = "scale_service" if ("cpu" in signals or "traffic" in signals) else "restart_service"
    policy_check(action)
    with engine.begin() as conn:
        existing = conn.execute(select(remediations).where(
            remediations.c.incident_id == r.incident_id)).first()
        if existing:
            return _row(existing)
        res = conn.execute(insert(remediations).values(
            incident_id=r.incident_id, service=r.service, action=action, status="recommended",
            recommended_at=utcnow(), verified=False))
        rid = res.inserted_primary_key[0]
        row = _get(conn, rid)
    _event(r.incident_id, "remediation_recommended",
           f"Recommended action: {action} (needs human approval)")
    return _row(row)


@app.get("/remediations")
def list_remediations(incident_id: str | None = None, _: dict = Depends(require_role(*ALL_ROLES))):
    q = select(remediations).order_by(remediations.c.id.desc())
    if incident_id:
        q = q.where(remediations.c.incident_id == incident_id)
    with engine.connect() as conn:
        return [_row(r) for r in conn.execute(q)]


@app.post("/remediations/{rid}/approve")
def approve(rid: int, user: dict = Depends(require_role("admin", "analyst"))):
    with engine.begin() as conn:
        r = _get(conn, rid)
        policy_check(r.action)
        if r.status != "recommended":
            raise HTTPException(409, f"Cannot approve a remediation that is '{r.status}'")
        conn.execute(update(remediations).where(remediations.c.id == rid).values(
            status="approved", approved_by=user["name"], approved_at=utcnow()))
        incident_id = r.incident_id
    _event(incident_id, "remediation_approved", f"Approved by {user['name']} ({user['role']})")
    return {"ok": True, "status": "approved"}


@app.post("/remediations/{rid}/execute")
def execute(rid: int, user: dict = Depends(require_role("admin", "analyst"))):
    with engine.begin() as conn:
        r = _get(conn, rid)
        policy_check(r.action)
        if r.status != "approved":
            raise HTTPException(409, "Policy: a remediation must be approved by a human before it runs")
        # The safe action: clear the simulated fault on the demo service.
        exists = conn.execute(select(demo_state).where(demo_state.c.service == r.service)).first()
        if exists:
            conn.execute(update(demo_state).where(demo_state.c.service == r.service).values(fault=False))
        else:
            conn.execute(insert(demo_state).values(service=r.service, fault=False))
        result = f"{r.action} executed on demo service {r.service}"
        conn.execute(update(remediations).where(remediations.c.id == rid).values(
            status="executed", executed_at=utcnow(), result=result))
        incident_id = r.incident_id
    _event(incident_id, "remediation_executed", f"{result} (run by {user['name']})")
    return {"ok": True, "status": "executed", "result": result}


@app.post("/remediations/verify/{incident_id}")
def verify(incident_id: str, _: dict = Depends(require_role("automation", "admin"))):
    """Called by the incident service when metrics are normal again."""
    with engine.begin() as conn:
        conn.execute(update(remediations).where(
            remediations.c.incident_id == incident_id, remediations.c.status == "executed"
        ).values(verified=True))
    _event(incident_id, "remediation_verified", "Metrics normal after remediation: verified")
    return {"ok": True}
