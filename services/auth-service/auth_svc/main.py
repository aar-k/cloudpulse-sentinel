"""Auth Service: users, roles, password login, JWT tokens."""
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, insert, select

from .auth import ALL_ROLES, current_user, require_role
from .db import init_db, iso, make_engine, utcnow

log = logging.getLogger("auth")
logging.basicConfig(level=logging.INFO)

ROLES = ("admin", "analyst", "developer", "readonly", "automation")
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "8"))

app = FastAPI(title="Auth Service")
engine = make_engine()
metadata = MetaData()
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(80), nullable=False),
    Column("email", String(120), nullable=False, unique=True),
    Column("password_hash", String(300), nullable=False),
    Column("role", String(20), nullable=False),
    Column("status", String(20), nullable=False, default="active"),
    Column("created_at", DateTime, nullable=False),
)


# ---------- password hashing (scrypt from the Python standard library) ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def make_token(email: str, name: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": email, "name": name, "role": role, "iat": now,
               "exp": now + timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


@app.on_event("startup")
def _startup():
    init_db(metadata, engine)
    seed_password = os.getenv("SEED_PASSWORD", "")
    with engine.begin() as conn:
        if conn.execute(select(users.c.id).limit(1)).first() is None:
            if not seed_password:
                log.warning("No users exist and SEED_PASSWORD is not set: nobody can log in.")
                return
            for name, email, role in (
                ("Admin User", "admin@cloudpulse.local", "admin"),
                ("Analyst User", "analyst@cloudpulse.local", "analyst"),
                ("Developer User", "developer@cloudpulse.local", "developer"),
                ("Read-only User", "viewer@cloudpulse.local", "readonly"),
            ):
                conn.execute(insert(users).values(
                    name=name, email=email, password_hash=hash_password(seed_password),
                    role=role, status="active", created_at=utcnow()))
            log.info("Seeded 4 demo users.")


class LoginIn(BaseModel):
    email: str
    password: str


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=100)
    role: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service"}


@app.post("/login")
def login(body: LoginIn):
    with engine.connect() as conn:
        u = conn.execute(select(users).where(users.c.email == body.email.lower())).first()
    ok = bool(u) and u.status == "active" and verify_password(body.password, u.password_hash)
    if not ok:
        raise HTTPException(401, "Wrong email or password")
    return {"access_token": make_token(u.email, u.name, u.role), "token_type": "bearer",
            "name": u.name, "role": u.role, "expires_in_hours": TOKEN_HOURS}


@app.get("/me")
def me(user: dict = Depends(current_user)):
    return user


@app.get("/users")
def list_users(_: dict = Depends(require_role("admin"))):
    with engine.connect() as conn:
        rows = conn.execute(select(users).order_by(users.c.id)).all()
    return [{"id": r.id, "name": r.name, "email": r.email, "role": r.role,
             "status": r.status, "created_at": iso(r.created_at)} for r in rows]


@app.post("/users", status_code=201)
def create_user(body: NewUser, _: dict = Depends(require_role("admin"))):
    if body.role not in ROLES:
        raise HTTPException(400, f"Role must be one of {list(ROLES)}")
    with engine.begin() as conn:
        if conn.execute(select(users.c.id).where(users.c.email == body.email.lower())).first():
            raise HTTPException(409, "Email already exists")
        conn.execute(insert(users).values(
            name=body.name, email=body.email.lower(), password_hash=hash_password(body.password),
            role=body.role, status="active", created_at=utcnow()))
    return {"ok": True, "email": body.email.lower(), "role": body.role}


__all__ = ["app", "ALL_ROLES"]
