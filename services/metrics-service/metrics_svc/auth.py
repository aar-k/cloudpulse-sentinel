"""Login checks shared by all services (each service keeps its own identical copy).

Two ways to get in:
  1. A user token (JWT) from the auth service:  Authorization: Bearer <token>
  2. An internal key for service-to-service calls: X-Internal-Key: <INTERNAL_KEY>  (role "automation")
"""
import hmac
import os

import jwt
from fastapi import Depends, Header, HTTPException

ALL_ROLES = ("admin", "analyst", "developer", "readonly", "automation")


def current_user(authorization: str | None = Header(default=None),
                 x_internal_key: str | None = Header(default=None)) -> dict:
    internal = os.getenv("INTERNAL_KEY", "")
    if x_internal_key and internal and hmac.compare_digest(x_internal_key, internal):
        return {"name": "internal-service", "role": "automation", "email": "internal"}
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise HTTPException(500, "Server is missing JWT_SECRET")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Login required")
    try:
        data = jwt.decode(authorization.split(" ", 1)[1], secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token") from None
    return {"name": data.get("name", "unknown"), "role": data.get("role", ""), "email": data.get("sub", "")}


def require_role(*roles: str):
    """FastAPI dependency: only the listed roles may call the endpoint."""
    def check(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, f"Role '{user['role']}' is not allowed here. Allowed: {sorted(roles)}")
        return user
    return check
