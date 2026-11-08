"""In-memory PayPal fake for unit tests. Mirrors observed sandbox behaviour (see docs/API_FEASIBILITY.md):
same PayPal-Request-Id returns the same refund; refunds beyond remaining -> 422 REFUND_AMOUNT_EXCEEDED.
Never presented as evidence of real integration; live tests are marked `live`."""

from decimal import Decimal

from app.integrations.paypal.client import PayPalClientError, PayPalResponse, PayPalTransportError


class FakePayPal:
    def __init__(self):
        self.captures: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.refund_calls = 0
        self.fail_next_refund_with_timeout = False
        self.fail_get_capture = False

    def add_capture(self, cid: str, amount: str, currency: str = "USD", status: str = "COMPLETED"):
        self.captures[cid] = {"id": cid, "status": status, "amount": {"value": amount, "currency_code": currency},
                              "refunded": Decimal("0")}

    def get_capture(self, cid):
        if self.fail_get_capture:
            raise PayPalTransportError("timeout")
        c = self.captures[cid]
        return PayPalResponse(200, {k: v for k, v in c.items() if k != "refunded"}, None)

    def refund_capture(self, cid, *, amount, currency, request_id, invoice_id=None, note_to_payer=None):
        self.refund_calls += 1
        if request_id in self.by_key:
            return PayPalResponse(200, self.refunds[self.by_key[request_id]], None)
        if self.fail_next_refund_with_timeout:
            self.fail_next_refund_with_timeout = False
            # simulate: PayPal created it, but our client never saw the response
            self._create(cid, amount, currency, request_id)
            raise PayPalTransportError("timed out; outcome unknown")
        c = self.captures[cid]
        if c["refunded"] + Decimal(amount) > Decimal(c["amount"]["value"]):
            raise PayPalClientError("422", status=422, body={"details": [{"issue": "REFUND_AMOUNT_EXCEEDED"}]})
        return PayPalResponse(201, self._create(cid, amount, currency, request_id), None)

    def _create(self, cid, amount, currency, key):
        rid = f"FAKEREF{len(self.refunds) + 1:04d}"
        body = {"id": rid, "status": "COMPLETED", "amount": {"value": amount, "currency_code": currency},
                "create_time": "2026-11-07T17:59:00Z"}
        self.refunds[rid], self.by_key[key] = body, rid
        c = self.captures[cid]
        c["refunded"] += Decimal(amount)
        c["status"] = "REFUNDED" if c["refunded"] == Decimal(c["amount"]["value"]) else "PARTIALLY_REFUNDED"
        return body

    def get_refund(self, rid):
        return PayPalResponse(200, self.refunds[rid], None)
