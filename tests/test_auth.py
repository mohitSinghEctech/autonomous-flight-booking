"""Firebase ID tokens: verified for real (RS256 + our own test key), mapped to users, sessions owned."""
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.api import auth
from app.core.logging import redact
from app.db.models import User
from app.db.session import SessionLocal

PROJECT = "test-project"


def make_signer():
    """A private key + the x509 cert Google would publish for it."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


KEY, CERT = make_signer()
OTHER_KEY, _ = make_signer()


def token(uid: str, *, key=KEY, kid="k1", aud=PROJECT, expires_in=3600, name="Mira Shah") -> str:
    now = int(time.time())
    claims = {
        "iss": f"https://securetoken.google.com/{aud}", "aud": aud, "sub": uid,
        "iat": now, "exp": now + expires_in, "auth_time": now, "name": name,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def firebase(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)

    async def certs():
        return {"k1": CERT}

    monkeypatch.setattr(auth, "signing_certs", certs)
    monkeypatch.setattr(auth, "_user_ids", {})


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


async def test_no_token_is_401(api, firebase):
    response = await api.post("/api/sessions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("bad", [
    lambda uid: token(uid, key=OTHER_KEY),          # signed by someone else
    lambda uid: token(uid, aud="another-project"),  # meant for another app
    lambda uid: token(uid, expires_in=-60),         # expired
    lambda uid: token(uid, kid="unknown"),          # key Google never published
    lambda uid: "not-a-jwt",
])
async def test_invalid_tokens_are_401(api, firebase, bad):
    response = await api.post("/api/sessions", headers=bearer(bad(uuid.uuid4().hex)))
    assert response.status_code == 401


async def test_first_sign_in_creates_the_user_once(api, firebase):
    uid = uuid.uuid4().hex

    first = await api.post("/api/sessions", headers=bearer(token(uid)))
    auth._user_ids.clear()                           # force the DB path again
    second = await api.post("/api/sessions", headers=bearer(token(uid)))

    assert first.status_code == second.status_code == 201
    async with SessionLocal() as session:
        users = (await session.execute(select(User).where(User.firebase_uid == uid))).scalars().all()
    assert len(users) == 1
    assert (users[0].given_name, users[0].family_name) == ("Mira", "Shah")


async def test_someone_elses_conversation_is_404(api, firebase):
    alice, bob = token(uuid.uuid4().hex), token(uuid.uuid4().hex)

    thread_id = (await api.post("/api/sessions", headers=bearer(alice))).json()["thread_id"]

    as_bob = await api.post(f"/api/sessions/{thread_id}/messages", headers=bearer(bob),
                            json={"text": "hi", "client_id": "client-1"})
    stream_as_bob = await api.get(f"/api/sessions/{thread_id}/stream", params={"access_token": bob})

    assert as_bob.status_code == 404
    assert stream_as_bob.status_code == 404
    assert as_bob.json()["error"]["code"] == "session_not_found"


async def test_stream_accepts_the_token_in_the_query(api, server, firebase):
    alice = token(uuid.uuid4().hex)
    thread_id = (await api.post("/api/sessions", headers=bearer(alice))).json()["thread_id"]

    async with api.stream("GET", f"/api/sessions/{thread_id}/stream", params={"access_token": alice}) as response:
        assert response.status_code == 200


async def test_emulator_tokens_are_unsigned_but_still_checked(api, firebase, monkeypatch):
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")
    now = int(time.time())
    claims = {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, "sub": uuid.uuid4().hex,
              "iat": now, "exp": now + 600}

    good = jwt.encode(claims, key=None, algorithm="none")
    wrong_app = jwt.encode({**claims, "aud": "x", "iss": "https://securetoken.google.com/x"}, key=None, algorithm="none")

    assert (await api.post("/api/sessions", headers=bearer(good))).status_code == 201
    assert (await api.post("/api/sessions", headers=bearer(wrong_app))).status_code == 401


def test_tokens_never_reach_the_logs():
    jwt_like = token("u1")
    line = f'GET /stream?access_token={jwt_like}&x=1 Authorization: Bearer {jwt_like}'

    cleaned = redact(line)

    assert jwt_like not in cleaned
    assert "access_token=[REDACTED]&x=1" in cleaned


async def test_every_response_carries_a_request_id(api):
    response = await api.get("/api/health", headers={"X-Request-ID": "trace-me"})
    assert response.headers["X-Request-ID"] == "trace-me"
    assert response.json()["database"] == "ok"
