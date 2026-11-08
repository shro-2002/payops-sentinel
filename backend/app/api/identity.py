"""Operator identity for four-eyes: who is acting, as asserted by the console proxy.

The bearer OPERATOR_TOKEN proves "this request came through a trusted caller", not "this is alice". So a named
identity is accepted only with an Ed25519 signature from the console proxy over (operator, method, path, query,
sha256(body), timestamp, nonce). Each nonce is accepted once, so a captured request can't be replayed or re-bodied.
The backend holds only the PUBLIC key (OPERATOR_IDENTITY_PUBLIC_KEY), so holding the backend's env or token is not
enough to act as another operator.

Without a public key the X-Operator header is ignored and every caller is `operator:console`; four-eyes then
refuses self-approval, so the missing config fails closed. The one exception is the dev-only LOCAL_CONSOLE, whose
single identity `local-operator` is accepted and whose self-approvals are audited as FOUR_EYES_WAIVED_LOCAL_DEV.
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

MAX_SKEW_SECONDS = 60
NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")
NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
LOCAL_OPERATOR = "local-operator"


class IdentityError(ValueError):
    pass


def signed_message(operator: str, method: str, path: str, query: str, body: bytes, ts: str, nonce: str) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return f"v1\n{operator}\n{method.upper()}\n{path}\n{query}\n{digest}\n{ts}\n{nonce}".encode()


# ponytail: per-process nonce memory; with several backend workers use a shared store (Redis SET NX EX).
_seen_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()


def _consume_nonce(nonce: str, now: float) -> bool:
    with _nonce_lock:
        for expired in [n for n, exp in _seen_nonces.items() if exp < now]:
            del _seen_nonces[expired]
        if nonce in _seen_nonces:
            return False
        _seen_nonces[nonce] = now + 2 * MAX_SKEW_SECONDS
        return True


def _public_key(b64_der: str) -> Ed25519PublicKey:
    key = load_der_public_key(base64.b64decode(b64_der))
    if not isinstance(key, Ed25519PublicKey):
        raise IdentityError("OPERATOR_IDENTITY_PUBLIC_KEY is not an Ed25519 key")
    return key


def resolve_operator(*, header: str, ts: str, sig: str, nonce: str, method: str, path: str, query: str, body: bytes,
                     public_key_b64: str, local_console: bool, now: float | None = None) -> str:
    """Return the operator name, or raise IdentityError for a forged / stale / replayed / malformed identity."""
    if not public_key_b64:
        return LOCAL_OPERATOR if local_console and header == LOCAL_OPERATOR else "console"
    now = now or time.time()
    if not NAME_RE.fullmatch(header or "") or not ts.isdigit() or not sig or not NONCE_RE.fullmatch(nonce or ""):
        raise IdentityError("signed operator identity required")
    if abs(now - int(ts)) > MAX_SKEW_SECONDS:
        raise IdentityError("operator identity signature expired")
    try:
        _public_key(public_key_b64).verify(base64.b64decode(sig),
                                           signed_message(header, method, path, query, body, ts, nonce))
    except (InvalidSignature, ValueError) as e:
        raise IdentityError("operator identity signature invalid") from e
    if not _consume_nonce(nonce, now):  # only after a valid signature, so junk can't fill the set
        raise IdentityError("operator identity signature already used")
    return header.lower()
