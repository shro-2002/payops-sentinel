"""PayPal REST client (sandbox): OAuth, Orders v2, Captures, Refunds, webhook signature verification.

Only documented endpoints are used:
  POST /v1/oauth2/token
  POST /v2/checkout/orders                      (PayPal-Request-Id idempotency)
  GET  /v2/checkout/orders/{id}
  POST /v2/checkout/orders/{id}/capture         (PayPal-Request-Id idempotency)
  GET  /v2/payments/captures/{id}
  POST /v2/payments/captures/{id}/refund        (PayPal-Request-Id idempotency)
  GET  /v2/payments/refunds/{id}
  POST /v1/notifications/verify-webhook-signature
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

TOKEN_REFRESH_MARGIN_S = 120
DEFAULT_TIMEOUT_S = 20.0
SANDBOX_HOSTS = {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}


class PayPalError(Exception):
    """Base error. `retryable` says whether repeating the SAME request (same idempotency key) is safe."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.body = body
        self.retryable = retryable


class PayPalClientError(PayPalError):
    """4xx: the request was rejected. Not retryable without changing it."""


class PayPalServerError(PayPalError):
    """5xx: PayPal failed. Outcome unknown for writes; retry only with the same idempotency key."""


class PayPalTransportError(PayPalError):
    """Timeout / connection failure. Outcome UNKNOWN for writes; reconcile by GET before assuming anything."""


@dataclass(frozen=True)
class PayPalResponse:
    status: int
    body: dict[str, Any]
    debug_id: str | None


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S,
                 transport: httpx.BaseTransport | None = None):
        if not client_id or not client_secret:
            raise ValueError("PayPal credentials missing")
        if httpx.URL(base_url).host not in SANDBOX_HOSTS:
            # ponytail: hard sandbox lock; lift deliberately with a reviewed config flag if live ever matters.
            raise ValueError("PayOps Sentinel only talks to the PayPal sandbox")
        self._id = client_id
        self._secret = client_secret
        self._base = base_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout_s, transport=transport)
        self._token: str | None = None
        self._token_expiry = 0.0
        self._lock = threading.Lock()

    # ---- auth -------------------------------------------------------------------------------
    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._token_expiry - TOKEN_REFRESH_MARGIN_S:
                return self._token
            try:
                r = self._http.post(f"{self._base}/v1/oauth2/token", auth=(self._id, self._secret),
                                    data={"grant_type": "client_credentials"})
            except httpx.HTTPError as e:
                raise PayPalTransportError("oauth transport failure", retryable=True) from e
            if r.status_code != 200:
                raise PayPalClientError("oauth rejected", status=r.status_code, body=_safe_json(r))
            data = r.json()
            self._token = data["access_token"]
            self._token_expiry = time.monotonic() + int(data.get("expires_in", 0))
            return self._token

    def _request(self, method: str, path: str, *, json: dict | None = None, request_id: str | None = None,
                 _retried_auth: bool = False) -> PayPalResponse:
        headers = {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            r = self._http.request(method, f"{self._base}{path}", json=json, headers=headers)
        except httpx.TimeoutException as e:
            raise PayPalTransportError(f"{method} {path} timed out; outcome unknown", retryable=True) from e
        except httpx.HTTPError as e:
            raise PayPalTransportError(f"{method} {path} transport failure", retryable=True) from e
        if r.status_code == 401 and not _retried_auth:
            with self._lock:
                self._token = None
            return self._request(method, path, json=json, request_id=request_id, _retried_auth=True)
        body = _safe_json(r)
        debug_id = r.headers.get("Paypal-Debug-Id")
        if r.status_code >= 500:
            raise PayPalServerError(f"{method} {path} -> {r.status_code}", status=r.status_code, body=body,
                                    retryable=True)
        if r.status_code >= 400:
            raise PayPalClientError(f"{method} {path} -> {r.status_code}", status=r.status_code, body=body,
                                    retryable=r.status_code == 429)
        return PayPalResponse(r.status_code, body if isinstance(body, dict) else {}, debug_id)

    # ---- orders -----------------------------------------------------------------------------
    def create_order(self, *, amount: str, currency: str, request_id: str, custom_id: str | None = None,
                     invoice_id: str | None = None, description: str | None = None,
                     payment_source: dict | None = None, return_url: str | None = None,
                     cancel_url: str | None = None) -> PayPalResponse:
        unit: dict[str, Any] = {"amount": {"currency_code": currency, "value": amount}}
        if custom_id:
            unit["custom_id"] = custom_id
        if invoice_id:
            unit["invoice_id"] = invoice_id
        if description:
            unit["description"] = description[:127]
        body: dict[str, Any] = {"intent": "CAPTURE", "purchase_units": [unit]}
        if payment_source:
            body["payment_source"] = payment_source
        elif return_url:
            body["payment_source"] = {"paypal": {"experience_context": {
                "return_url": return_url, "cancel_url": cancel_url or return_url,
                "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"}}}
        return self._request("POST", "/v2/checkout/orders", json=body, request_id=request_id)

    def get_order(self, order_id: str) -> PayPalResponse:
        return self._request("GET", f"/v2/checkout/orders/{_seg(order_id)}")

    def capture_order(self, order_id: str, *, request_id: str) -> PayPalResponse:
        return self._request("POST", f"/v2/checkout/orders/{_seg(order_id)}/capture", json={}, request_id=request_id)

    # ---- captures / refunds -----------------------------------------------------------------
    def get_capture(self, capture_id: str) -> PayPalResponse:
        return self._request("GET", f"/v2/payments/captures/{_seg(capture_id)}")

    def refund_capture(self, capture_id: str, *, amount: str, currency: str, request_id: str,
                       invoice_id: str | None = None, note_to_payer: str | None = None) -> PayPalResponse:
        body: dict[str, Any] = {"amount": {"value": amount, "currency_code": currency}}
        if invoice_id:
            body["invoice_id"] = invoice_id
        if note_to_payer:
            body["note_to_payer"] = note_to_payer[:255]
        return self._request("POST", f"/v2/payments/captures/{_seg(capture_id)}/refund", json=body,
                             request_id=request_id)

    def get_refund(self, refund_id: str) -> PayPalResponse:
        return self._request("GET", f"/v2/payments/refunds/{_seg(refund_id)}")

    # ---- webhooks ---------------------------------------------------------------------------
    def create_webhook(self, *, url: str, event_types: list[str]) -> PayPalResponse:
        """POST /v1/notifications/webhooks: subscribe this REST app to events delivered to `url` (HTTPS)."""
        return self._request("POST", "/v1/notifications/webhooks",
                             json={"url": url, "event_types": [{"name": n} for n in event_types]})

    def list_webhooks(self) -> PayPalResponse:
        return self._request("GET", "/v1/notifications/webhooks")

    def verify_webhook_signature(self, *, headers: dict[str, str], event: dict, webhook_id: str) -> bool:
        """True only when PayPal answers verification_status == SUCCESS. HTTP 200 alone proves nothing."""
        h = {k.lower(): v for k, v in headers.items()}
        required = ["paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig",
                    "paypal-transmission-time"]
        if not webhook_id or any(not h.get(k) for k in required):
            return False
        body = {"auth_algo": h["paypal-auth-algo"], "cert_url": h["paypal-cert-url"],
                "transmission_id": h["paypal-transmission-id"], "transmission_sig": h["paypal-transmission-sig"],
                "transmission_time": h["paypal-transmission-time"], "webhook_id": webhook_id,
                "webhook_event": event}
        r = self._request("POST", "/v1/notifications/verify-webhook-signature", json=body)
        return r.body.get("verification_status") == "SUCCESS"


def approval_url(order_body: dict) -> str | None:
    for link in order_body.get("links", []):
        if link.get("rel") in ("payer-action", "approve"):
            return link.get("href")
    return None


def first_capture(order_body: dict) -> dict | None:
    for unit in order_body.get("purchase_units", []):
        caps = unit.get("payments", {}).get("captures", [])
        if caps:
            return caps[0]
    return None


def _seg(value: str) -> str:
    # Provider ids are uppercase alphanumerics; refuse anything that could alter the path.
    if not value or not value.replace("-", "").isalnum():
        raise ValueError("invalid PayPal resource id")
    return value


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:500]}
