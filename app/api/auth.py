"""
Who is calling (contract §2).

The browser signs in with Firebase and sends the Firebase ID token:
  - Authorization: Bearer <token>       on every POST
  - ?access_token=<token>               on the SSE stream (EventSource can't send headers)

We verify it ourselves — no firebase-admin (it pulls in all of google-cloud):
  RS256 signature against Google's public certs, audience = our project,
  issuer = securetoken.google.com/<project>, not expired, has a subject (uid).

Then the uid is mapped to our own users row (created on first sign-in).

AUTH_MODE:
  firebase  (default)  verify as above
  demo                 no token needed; everyone is DEMO_USER_ID (tests, local curl)

With FIREBASE_AUTH_EMULATOR_HOST set (local emulator only) tokens are unsigned,
so the signature check is skipped and everything else is still checked.
"""
import logging
import os
import re
import time

import httpx
import jwt
from cryptography.x509 import load_pem_x509_certificate
from fastapi import Header, Query

from app.api.errors import ApiError
from app.db.repositories.users import UserRepository
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"

DEMO_USER_ID = os.getenv("DEMO_USER_ID", "eeb6ff6a-c66f-4874-a5aa-7c773962e14e")


def auth_mode() -> str:
    return os.getenv("AUTH_MODE", "firebase")


def project_id() -> str:
    return os.getenv("FIREBASE_PROJECT_ID", "mks-agent-console")


def emulator() -> bool:
    return bool(os.getenv("FIREBASE_AUTH_EMULATOR_HOST"))


# ---- Google's signing certs (rotate; cached for as long as Google says) --------------

_certs: dict[str, str] = {}
_certs_expire_at = 0.0


async def signing_certs() -> dict[str, str]:
    global _certs, _certs_expire_at

    if _certs and time.time() < _certs_expire_at:
        return _certs

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(CERTS_URL)
        response.raise_for_status()

    match = re.search(r"max-age=(\d+)", response.headers.get("cache-control", ""))
    _certs = response.json()
    _certs_expire_at = time.time() + (int(match.group(1)) if match else 3600)
    return _certs


async def verify_token(token: str) -> dict:
    """Claims of a valid Firebase ID token, or ApiError 401."""

    issuer = f"https://securetoken.google.com/{project_id()}"
    required = {"require": ["exp", "iat", "sub"]}

    try:
        if emulator():
            claims = jwt.decode(
                token,
                options={"verify_signature": False, "verify_exp": True, "verify_aud": True, "verify_iss": True, **required},
                audience=project_id(),
                issuer=issuer,
            )
        else:
            kid = jwt.get_unverified_header(token).get("kid")
            cert = (await signing_certs()).get(kid or "")
            if cert is None:
                raise jwt.InvalidTokenError("unknown signing key")

            claims = jwt.decode(
                token,
                load_pem_x509_certificate(cert.encode()).public_key(),
                algorithms=["RS256"],
                audience=project_id(),
                issuer=issuer,
                leeway=10,
                options=required,
            )

    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "unauthenticated", "Your sign-in expired. Please sign in again.", retryable=True) from exc
    except (jwt.InvalidTokenError, httpx.HTTPError) as exc:
        logger.warning("rejected token: %s", type(exc).__name__)
        raise ApiError(401, "unauthenticated", "Please sign in again.") from exc

    if not claims.get("sub"):
        raise ApiError(401, "unauthenticated", "Please sign in again.")

    return claims


def display_name(claims: dict) -> tuple[str, str]:
    name = (claims.get("name") or (claims.get("email") or "Traveller").split("@")[0]).strip()
    given, _, family = name.partition(" ")
    return given[:100] or "Traveller", family[:100] or "-"


# firebase uid -> users.id; the mapping never changes, so no DB hit after the first request
_user_ids: dict[str, str] = {}


async def current_user_id(
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None),
) -> str:
    """FastAPI dependency: our users.id (as str) for the caller."""

    if auth_mode() == "demo":
        return DEMO_USER_ID

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or access_token

    if not token:
        raise ApiError(401, "unauthenticated", "Please sign in.")

    claims = await verify_token(token)

    cached = _user_ids.get(claims["sub"])
    if cached:
        return cached

    given, family = display_name(claims)

    async with SessionLocal() as session:
        user = await UserRepository(session).get_or_create_by_firebase_uid(claims["sub"], given, family)
        await session.commit()

    _user_ids[claims["sub"]] = str(user.id)
    return _user_ids[claims["sub"]]
