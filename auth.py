"""Password hashing, JWT issue/verify, and the owner/admin access checks."""

import os
import secrets
from datetime import datetime, timedelta, timezone
from threading import RLock

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

SECRET_KEY = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(32)
ALGORITHM = "HS256"
TOKEN_MINUTES = 60
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

_users: dict[str, dict] = {}
_lock = RLock()
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())


def reset_users() -> None:
    """Clear every account and re-seed the hardcoded admin."""
    with _lock:
        _users.clear()
        _users[ADMIN_USERNAME] = {"hash": hash_password(ADMIN_PASSWORD), "role": "admin"}


def register_user(username: str, password: str) -> bool:
    """False when the username is already taken."""
    with _lock:
        if username in _users:
            return False
        _users[username] = {"hash": hash_password(password), "role": "student"}
        return True


def authenticate(username: str, password: str):
    """Return the user's role on a correct password, otherwise None."""
    user = _users.get(username)
    if user and bcrypt.checkpw(password.encode(), user["hash"]):
        return user["role"]
    return None


def create_token(username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": username, "role": role, "iat": now,
              "exp": now + timedelta(minutes=TOKEN_MINUTES)}
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status_code=401, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def optional_claims(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Decoded claims for a valid bearer token, or None when absent or invalid."""
    if creds is None:
        return None
    try:
        return jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def current_claims(claims=Depends(optional_claims)) -> dict:
    if not claims or not claims.get("sub"):
        raise unauthorized()
    return claims


def require_owner(student_id: str, claims: dict) -> None:
    """BOLA: the token's subject must be exactly this student."""
    if claims.get("sub") != student_id:
        raise unauthorized("Token does not belong to this student")


def require_owner_or_admin(student_id: str, claims: dict) -> None:
    if claims.get("role") == "admin":
        return
    require_owner(student_id, claims)


reset_users()
