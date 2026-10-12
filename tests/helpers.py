import os
from datetime import datetime, timedelta, timezone

import jwt


def token(role: str, name: str | None = None, hours: int = 1) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": f"{role}@test", "name": name or f"{role}-user", "role": role,
                       "iat": now, "exp": now + timedelta(hours=hours)},
                      os.environ["JWT_SECRET"], algorithm="HS256")


def auth(role: str, name: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token(role, name)}"}


def internal() -> dict:
    return {"X-Internal-Key": os.environ["INTERNAL_KEY"]}
