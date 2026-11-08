"""Four-eyes identity: the shared backend token is not enough to act as a named operator (audit finding S1)."""

import base64
import json
import secrets
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from app.api.identity import IdentityError, resolve_operator, signed_message
from app.config import get_settings
from app.main import app

TOKEN = "t" * 32
DECISION = "/api/v1/proposals/00000000-0000-0000-0000-000000000000/decision"


def keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return priv, base64.b64encode(pub).decode()


BODY = json.dumps({"approve": True, "details_hash": "0" * 64}).encode()


def signed(priv, operator: str, method: str, path: str, ts: int | None = None, body: bytes = BODY, query: str = "",
           nonce: str | None = None) -> dict:
    ts, nonce = str(ts or int(time.time())), nonce or secrets.token_urlsafe(16)
    sig = base64.b64encode(priv.sign(signed_message(operator, method, path, query, body, ts, nonce))).decode()
    return {"X-Operator": operator, "X-Operator-Ts": ts, "X-Operator-Sig": sig, "X-Operator-Nonce": nonce}


def resolve(h: dict, pub: str, method="POST", path=DECISION, local=False, body: bytes = BODY, query: str = ""):
    return resolve_operator(header=h.get("X-Operator", ""), ts=h.get("X-Operator-Ts", ""),
                            sig=h.get("X-Operator-Sig", ""), nonce=h.get("X-Operator-Nonce", ""), method=method,
                            path=path, query=query, body=body, public_key_b64=pub, local_console=local)


def test_valid_signature_yields_the_named_operator():
    priv, pub = keypair()
    assert resolve(signed(priv, "Bob", "POST", DECISION), pub) == "bob"


@pytest.mark.parametrize("tamper", ["unsigned", "other_key", "other_name", "other_path", "other_method", "stale",
                                    "other_body", "other_query"])
def test_forged_stale_or_rebodied_identity_is_rejected(tamper):
    priv, pub = keypair()
    h = signed(priv, "alice", "POST", DECISION)
    body, query = BODY, ""
    if tamper == "unsigned":
        h = {"X-Operator": "bob"}
    elif tamper == "other_key":
        h = signed(Ed25519PrivateKey.generate(), "bob", "POST", DECISION)
    elif tamper == "other_name":
        h["X-Operator"] = "bob"
    elif tamper == "other_path":
        h = signed(priv, "bob", "POST", "/api/v1/detection/run")
    elif tamper == "other_method":
        h = signed(priv, "bob", "GET", DECISION)
    elif tamper == "stale":
        h = signed(priv, "bob", "POST", DECISION, ts=int(time.time()) - 3600)
    elif tamper == "other_body":  # captured alice request, body swapped for a different action
        body = json.dumps({"approve": False, "details_hash": "1" * 64}).encode()
    elif tamper == "other_query":
        query = "limit=99"
    with pytest.raises(IdentityError):
        resolve(h, pub, body=body, query=query)


def test_exact_replay_of_a_signed_request_is_rejected():
    priv, pub = keypair()
    h = signed(priv, "alice", "POST", DECISION)
    assert resolve(h, pub) == "alice"
    with pytest.raises(IdentityError, match="already used"):
        resolve(h, pub)


def test_without_a_signing_key_the_header_is_ignored():
    assert resolve({"X-Operator": "bob"}, "") == "console"
    assert resolve({"X-Operator": "local-operator"}, "") == "console"
    assert resolve({"X-Operator": "local-operator"}, "", local=True) == "local-operator"
    assert resolve({"X-Operator": "bob"}, "", local=True) == "console"


def test_audit_probe2_token_plus_forged_header_cannot_approve():
    """Probe 2: holder of OPERATOR_TOKEN sends X-Operator: bob. With signing configured it is refused outright."""
    priv, pub = keypair()
    cfg = get_settings()
    cfg.operator_token, cfg.operator_identity_public_key = TOKEN, pub
    try:
        c = TestClient(app)
        auth = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
        forged = c.post(DECISION, headers={**auth, "X-Operator": "bob"}, content=BODY)
        assert forged.status_code == 401 and forged.json()["detail"]["code"] == "OPERATOR_IDENTITY_INVALID"
        genuine = c.post(DECISION, headers={**auth, **signed(priv, "bob", "POST", DECISION)}, content=BODY)
        assert genuine.status_code == 404  # identity accepted, then: proposal not found
    finally:
        cfg.operator_token, cfg.operator_identity_public_key = "", ""
