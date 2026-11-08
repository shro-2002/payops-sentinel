"""Create 1-2 PayPal-WALLET-funded sandbox captures approved by the sandbox personal account (real buyer approval).

Usage (you run it; credentials stay in your .env):
  SANDBOX_BUYER_EMAIL=... SANDBOX_BUYER_PASSWORD=... in the repo-root .env, then
  cd backend && .venv/bin/python -m scripts.seed_wallet_captures [--count 2]
If PayPal shows a CAPTCHA or verification challenge the helper stops (exit 3) and nothing is faked.
"""

import argparse
import os
import subprocess
import uuid
from pathlib import Path

from app.api.routes import paypal_client
from app.config import get_settings
from app.db.session import SessionLocal
from app.integrations.paypal.client import approval_url, first_capture
from app.ledger.ingest import CaptureDims, order_funding_source, upsert_capture

ROOT = Path(__file__).resolve().parents[2]
RETURN = "http://localhost:3100/sandbox/return"
SPECS = [("29.00", dict(product_sku="LAMP-LED", product_category="home", region="NA", channel="web",
                        fulfillment_partner="NorthPost", customer_ref="cust-4410")),
         ("15.50", dict(product_sku="TEE-ORG", product_category="apparel", region="EU", channel="mobile",
                        fulfillment_partner="ParcelOne", customer_ref="cust-5521"))]


def env_with_buyer() -> dict:
    env = dict(os.environ)
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(("SANDBOX_BUYER_EMAIL=", "SANDBOX_BUYER_PASSWORD=")):
            k, v = line.split("=", 1)
            env.setdefault(k, v.strip())
    return env


def main(count: int) -> None:
    get_settings()
    pp = paypal_client()
    env = env_with_buyer()
    for amount, dims in SPECS[:count]:
        order = pp.create_order(amount=amount, currency="USD", request_id=f"payops-wallet-{uuid.uuid4()}",
                                custom_id="payops-wallet", return_url=RETURN).body
        link = approval_url(order)
        res = subprocess.run(["node", "scripts/approve-wallet-order.mjs", link, RETURN], cwd=ROOT / "frontend",
                             env=env, capture_output=True, text=True, timeout=180)
        if res.returncode != 0:
            raise SystemExit(f"approval stopped (exit {res.returncode}): {res.stderr.strip()[-400:]}")
        captured = pp.capture_order(order["id"], request_id=f"payops-wallet-cap-{order['id']}").body
        cap = first_capture(captured)
        live = pp.get_capture(cap["id"]).body
        with SessionLocal() as s:
            upsert_capture(s, live, dims=CaptureDims(**dims), origin="SANDBOX_LIVE", order_id=order["id"],
                           verified=True, funding_source=order_funding_source(captured))
            s.commit()
        print({"order": order["id"], "capture": cap["id"], "status": live["status"],
               "funding_source": order_funding_source(captured)})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=2)
    main(min(max(ap.parse_args().count, 1), 2))
