"""PayPal Agent Toolkit (paypal-agent-toolkit 1.11.0), restricted to READ actions.

Why a wrapper: the toolkit's `PayPalAPI.run(method, ...)` executes ANY registered method (including create_order /
pay_order) regardless of `Configuration`; only its framework adapters filter by configuration. So we build the tool
set ourselves from the toolkit's registry, filtered by the toolkit's own `Configuration` + `is_tool_allowed`, and
dispatch only those tools' `execute` functions. Nothing else in the toolkit is reachable from here.

Enabled: orders.get (`get_order_details`), whose response carries the order's captures AND refunds. Transaction Search
(`list_transactions`) is deliberately not enabled: it lags or returns empty in sandbox.
"""

from __future__ import annotations

import json
from functools import lru_cache

from paypal_agent_toolkit.shared.configuration import Configuration, Context, is_tool_allowed
from paypal_agent_toolkit.shared.paypal_client import PayPalClient as _ToolkitClient
from paypal_agent_toolkit.shared.tools import tools as _TOOLKIT_TOOLS

from app.config import get_settings

READ_ONLY_CONFIGURATION = Configuration(actions={"orders": {"get": True}}, context=Context(sandbox=True))
# Every action verb we accept. A tool whose tags include anything else can never be enabled here.
READ_VERBS = {"get", "list", "show"}


def _readonly_tools() -> dict[str, dict]:
    allowed = {}
    for tool in _TOOLKIT_TOOLS:
        if not is_tool_allowed(tool, READ_ONLY_CONFIGURATION):
            continue
        verbs = {verb for product in tool.get("actions", {}).values() for verb, on in product.items() if on}
        if not verbs or not verbs <= READ_VERBS:
            raise RuntimeError(f"toolkit tool {tool.get('method')} carries non-read actions {verbs}; refusing")
        allowed[tool["method"]] = tool
    return allowed


READ_ONLY_TOOLS = _readonly_tools()


@lru_cache
def _client() -> _ToolkitClient:
    cfg = get_settings()
    return _ToolkitClient(client_id=cfg.paypal_client_id, secret=cfg.paypal_client_secret,
                          context=READ_ONLY_CONFIGURATION.context)


def run_readonly(method: str, params: dict) -> dict:
    """Dispatch only configuration-allowed read tools. Anything else raises before any network call."""
    tool = READ_ONLY_TOOLS.get(method)
    if tool is None:
        raise PermissionError(f"toolkit method {method!r} is not enabled (read-only configuration)")
    return json.loads(tool["execute"](_client(), params))


def order_snapshot(order_id: str) -> dict:
    """PayPal's own record of an order: status, captures, refunds (from the toolkit's `raw` payload).
    The toolkit's free-text `message` ("successfully captured") is dropped: it is constant, not a fact."""
    raw = run_readonly("get_order_details", {"order_id": order_id}).get("raw") or {}
    payments = (raw.get("purchase_units") or [{}])[0].get("payments") or {}

    def money(block: dict) -> dict:
        amount = block.get("amount") or {}
        return {"id": block.get("id"), "status": block.get("status"), "value": amount.get("value"),
                "currency": amount.get("currency_code")}

    return {"order_id": raw.get("id"), "order_status": raw.get("status"),
            "payment_source": next(iter((raw.get("payment_source") or {}).keys()), None),
            "captures": [money(c) for c in payments.get("captures", [])],
            "refunds": [money(r) for r in payments.get("refunds", [])]}
