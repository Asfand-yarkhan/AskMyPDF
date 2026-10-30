"""Accounts: guest trials, document ownership, signed file links and token handling."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import LOCAL_USER, User, current_user, sign_file_token, user_from_claims, verify_file_token
from app.registry import DocumentRegistry
from app.schemas import ChunkConfig, DocumentInfo, DocumentProfile
from app.usage import TrialExhausted, UsageTracker

GUEST = User(uid="guest-1", is_guest=True)
MEMBER = User(uid="member-1", is_guest=False, email="a@example.com")


def make_doc(doc_id: str) -> DocumentInfo:
    profile = DocumentProfile(
        page_count=1, total_words=10, avg_words_per_page=10, heading_count=0, heading_density=0,
        table_count=0, table_ratio=0, bullet_ratio=0, ocr_pages=0, is_scanned=False,
        technical_score=0, doc_type="general",
    )
    return DocumentInfo(
        doc_id=doc_id, filename=f"{doc_id}.pdf", size_bytes=1, page_count=1, chunk_count=1,
        created_at=datetime.now(timezone.utc),
        chunk_config=ChunkConfig(strategy="general", chunk_size=800, chunk_overlap=100, reason="test"),
        profile=profile, embedding_id="test",
    )


# --- Trials -------------------------------------------------------------------------


def test_guest_gets_limited_trials(tmp_path) -> None:
    usage = UsageTracker(tmp_path / "u.sqlite", guest_trials=3, ip_trials_per_day=10)
    remaining = [usage.consume(GUEST, "1.1.1.1").remaining for _ in range(3)]
    assert remaining == [2, 1, 0]
    with pytest.raises(TrialExhausted):
        usage.consume(GUEST, "1.1.1.1")
    assert usage.status(GUEST, "1.1.1.1").remaining == 0


def test_members_are_not_limited(tmp_path) -> None:
    usage = UsageTracker(tmp_path / "u.sqlite", guest_trials=1, ip_trials_per_day=1)
    for _ in range(5):
        assert usage.consume(MEMBER, "1.1.1.1") is None
    assert usage.status(MEMBER, "1.1.1.1") is None


def test_new_guest_on_same_network_hits_the_ip_cap(tmp_path) -> None:
    usage = UsageTracker(tmp_path / "u.sqlite", guest_trials=3, ip_trials_per_day=4)
    for _ in range(3):
        usage.consume(GUEST, "2.2.2.2")
    fresh = User(uid="guest-2", is_guest=True)  # cleared browser data: new anonymous account
    usage.consume(fresh, "2.2.2.2")
    with pytest.raises(TrialExhausted):
        usage.consume(fresh, "2.2.2.2")
    assert usage.consume(fresh, "3.3.3.3").remaining == 1  # another network is unaffected


# --- Ownership ----------------------------------------------------------------------


def test_documents_are_private_per_owner(tmp_path) -> None:
    registry = DocumentRegistry(tmp_path / "docs.json")
    registry.upsert(make_doc("aaaa1111"))
    registry.upsert(make_doc("bbbb2222"))
    registry.add_owner("aaaa1111", "alice")
    registry.add_owner("bbbb2222", "bob")
    assert [d.doc_id for d in registry.list("alice")] == ["aaaa1111"]
    assert not registry.is_owner("bbbb2222", "alice")
    assert len(registry.list()) == 2


def test_shared_pdf_survives_until_last_owner_deletes(tmp_path) -> None:
    registry = DocumentRegistry(tmp_path / "docs.json")
    registry.upsert(make_doc("aaaa1111"))
    registry.add_owner("aaaa1111", "alice")
    registry.add_owner("aaaa1111", "bob")
    assert registry.remove_owner("aaaa1111", "alice") is False
    assert registry.list("alice") == [] and len(registry.list("bob")) == 1
    assert registry.remove_owner("aaaa1111", "bob") is True


def test_owners_persist_and_transfer(tmp_path) -> None:
    path = tmp_path / "docs.json"
    registry = DocumentRegistry(path)
    registry.upsert(make_doc("aaaa1111"))
    registry.add_owner("aaaa1111", "guest-x")
    assert registry.transfer_owner("guest-x", "member-y") == 1
    reloaded = DocumentRegistry(path)
    assert reloaded.is_owner("aaaa1111", "member-y") and not reloaded.is_owner("aaaa1111", "guest-x")


def test_registry_reads_the_format_before_accounts(tmp_path) -> None:
    path = tmp_path / "docs.json"
    path.write_text(json.dumps({"aaaa1111": make_doc("aaaa1111").model_dump(mode="json")}), encoding="utf-8")
    registry = DocumentRegistry(path)
    assert registry.get("aaaa1111") is not None
    assert registry.list("anyone") == []  # unowned legacy documents are hidden from accounts


# --- Signed file links --------------------------------------------------------------


def test_file_tokens() -> None:
    secret = b"s3cret"
    token = sign_file_token(secret, "aaaa1111", ttl_s=60)
    assert verify_file_token(secret, "aaaa1111", token)
    assert not verify_file_token(secret, "bbbb2222", token)  # bound to one document
    assert not verify_file_token(b"other", "aaaa1111", token)
    assert not verify_file_token(secret, "aaaa1111", "garbage")
    expired = sign_file_token(secret, "aaaa1111", ttl_s=-1)
    assert not verify_file_token(secret, "aaaa1111", expired)


# --- Tokens -------------------------------------------------------------------------


def test_user_from_claims() -> None:
    guest = user_from_claims({"sub": "u1", "firebase": {"sign_in_provider": "anonymous"}})
    member = user_from_claims({"sub": "u2", "email": "x@y.z", "firebase": {"sign_in_provider": "google.com"}})
    assert guest.is_guest and not member.is_guest and member.email == "x@y.z"


class FakeVerifier:
    def verify(self, token: str) -> dict:
        if token != "good":
            raise ValueError("bad token")
        return {"sub": "u1", "firebase": {"sign_in_provider": "password"}, "exp": time.time() + 60}


def _client(verifier) -> TestClient:
    app = FastAPI()
    app.state.verifier = verifier

    @app.get("/who")
    def who(user: User = Depends(current_user)) -> dict:
        return {"uid": user.uid, "guest": user.is_guest}

    return TestClient(app)


def test_current_user_requires_a_valid_token_when_enabled() -> None:
    client = _client(FakeVerifier())
    assert client.get("/who").status_code == 401
    assert client.get("/who", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/who", headers={"Authorization": "Bearer good"}).json() == {"uid": "u1", "guest": False}


def test_without_firebase_everyone_is_the_local_user() -> None:
    assert _client(None).get("/who").json() == {"uid": LOCAL_USER.uid, "guest": False}


def test_password_accounts_need_a_verified_email() -> None:
    unverified = user_from_claims({"sub": "u3", "email": "x@y.z", "firebase": {"sign_in_provider": "password"}})
    verified = user_from_claims(
        {"sub": "u3", "email": "x@y.z", "email_verified": True, "firebase": {"sign_in_provider": "password"}}
    )
    google = user_from_claims({"sub": "u4", "email": "g@y.z", "firebase": {"sign_in_provider": "google.com"}})
    assert not unverified.is_guest and not unverified.is_member
    assert verified.is_member and google.is_member


def test_unverified_accounts_keep_guest_limits(tmp_path) -> None:
    usage = UsageTracker(tmp_path / "u.sqlite", guest_trials=2, ip_trials_per_day=10)
    pending = User(uid="guest-1", is_guest=False, email="x@y.z", email_verified=False)
    usage.consume(GUEST, "1.1.1.1")  # used one trial as a guest, then signed up with the same uid
    assert usage.consume(pending, "1.1.1.1").remaining == 0
    with pytest.raises(TrialExhausted):
        usage.consume(pending, "1.1.1.1")
    confirmed = User(uid="guest-1", is_guest=False, email="x@y.z", email_verified=True)
    assert usage.consume(confirmed, "1.1.1.1") is None
