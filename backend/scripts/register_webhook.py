"""Register a PayPal sandbox webhook for PAYMENT.CAPTURE.COMPLETED/REFUNDED and store its id in the root .env.

Usage: python -m scripts.register_webhook https://<public-host>
The URL must be public HTTPS (e.g. a cloudflared quick tunnel to the API). Quick-tunnel hostnames change on restart,
so re-run this after restarting the tunnel. Existing webhooks are listed, never deleted.
"""

import re
import sys
from pathlib import Path

from app.api.routes import paypal_client

EVENTS = ["PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.REFUNDED"]
ENV = Path(__file__).resolve().parents[2] / ".env"


def main(base: str) -> None:
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", base.rstrip("/")):
        raise SystemExit("expected a bare https://host URL")
    url = base.rstrip("/") + "/api/v1/webhooks/paypal"
    pp = paypal_client()
    existing = [w for w in pp.list_webhooks().body.get("webhooks", []) if w.get("url") == url]
    hook = existing[0] if existing else pp.create_webhook(url=url, event_types=EVENTS).body
    text = ENV.read_text()
    line = f"PAYPAL_WEBHOOK_ID={hook['id']}"
    text = re.sub(r"(?m)^PAYPAL_WEBHOOK_ID=.*$", line, text) if "PAYPAL_WEBHOOK_ID=" in text else text + f"\n{line}\n"
    ENV.write_text(text)
    print({"webhook_id": hook["id"], "url": url, "reused": bool(existing),
           "events": [e["name"] for e in hook.get("event_types", [])]})


if __name__ == "__main__":
    main(sys.argv[1])
