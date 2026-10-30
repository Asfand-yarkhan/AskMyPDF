"""Firebase Authentication: verify ID tokens sent as `Authorization: Bearer <token>`.

Visitors are signed in anonymously by the frontend, so every request has a user id. Anonymous
users are guests with a few free trials; signing up links the same Firebase account to an email
or Google login, keeping its uid (and documents).

Tokens are verified against Google's public certificates (no service account needed). Without
FIREBASE_PROJECT_ID the API runs unauthenticated as a single local user, for development.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import urllib.request
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from google.auth import jwt

from app.config import Settings

logger = logging.getLogger(__name__)

CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
CERTS_TTL_S = 3600


@dataclass(frozen=True)
class User:
    uid: str
    is_guest: bool  # anonymous session, no login yet
    email: str | None = None
    # Email/password accounts must click the link Firebase emails them; until then they keep guest limits.
    email_verified: bool = True

    @property
    def is_member(self) -> bool:
        """A real, verified account: no trial limits."""
        return not self.is_guest and self.email_verified


LOCAL_USER = User(uid="local", is_guest=False)


class TokenVerifier:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._certs: dict[str, str] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _get_certs(self, refresh: bool = False) -> dict[str, str]:
        with self._lock:
            if refresh or not self._certs or time.time() - self._fetched_at > CERTS_TTL_S:
                with urllib.request.urlopen(CERTS_URL, timeout=10) as res:
                    self._certs = json.loads(res.read())
                self._fetched_at = time.time()
            return self._certs

    def verify(self, token: str) -> dict:
        """Return the token's claims, or raise ValueError."""
        try:
            claims = jwt.decode(token, certs=self._get_certs(), audience=self.project_id, clock_skew_in_seconds=10)
        except ValueError as exc:
            if "certificate" not in str(exc).lower():
                raise
            # Google rotated its keys since the last fetch.
            claims = jwt.decode(token, certs=self._get_certs(refresh=True), audience=self.project_id, clock_skew_in_seconds=10)
        if claims.get("iss") != f"https://securetoken.google.com/{self.project_id}" or not claims.get("sub"):
            raise ValueError("Token was not issued for this Firebase project")
        return claims


def user_from_claims(claims: dict) -> User:
    provider = (claims.get("firebase") or {}).get("sign_in_provider")
    # Google and other identity providers vouch for the address; passwords need the email link.
    verified = provider != "password" or bool(claims.get("email_verified"))
    return User(uid=claims["sub"], is_guest=provider == "anonymous", email=claims.get("email"), email_verified=verified)


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def current_user(request: Request) -> User:
    """FastAPI dependency: the signed-in (or anonymous) Firebase user."""
    verifier: TokenVerifier | None = request.app.state.verifier
    if verifier is None:
        return LOCAL_USER
    token = bearer_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in to continue.")
    try:
        return user_from_claims(verifier.verify(token))
    except Exception as exc:  # expired, malformed, wrong project, cert fetch failed
        logger.info("Rejected token: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Please sign in again.") from exc


def client_ip(request: Request) -> str:
    # uvicorn runs with --proxy-headers, so this is the visitor's address behind Railway's proxy.
    return request.client.host if request.client else "unknown"


# --- Signed file links -----------------------------------------------------------
# The PDF opens in a new browser tab, which cannot send an Authorization header, so document
# responses carry a short-lived signed token for the file URL instead.


def _file_signature(secret: bytes, doc_id: str, expires: int) -> str:
    digest = hmac.new(secret, f"{doc_id}:{expires}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def sign_file_token(secret: bytes, doc_id: str, ttl_s: int) -> str:
    expires = int(time.time()) + ttl_s
    return f"{expires}.{_file_signature(secret, doc_id, expires)}"


def verify_file_token(secret: bytes, doc_id: str, token: str) -> bool:
    expires_s, _, signature = token.partition(".")
    if not expires_s.isdigit() or int(expires_s) < time.time():
        return False
    return hmac.compare_digest(signature, _file_signature(secret, doc_id, int(expires_s)))


def load_or_create_secret(settings: Settings) -> bytes:
    if settings.file_url_secret:
        return settings.file_url_secret.get_secret_value().encode()
    path = settings.data_dir / "file_url_secret"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()
