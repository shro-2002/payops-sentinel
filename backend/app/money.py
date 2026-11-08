"""Exact money handling: integer minor units only. Strings at the PayPal boundary, never floats."""

import re
from decimal import ROUND_HALF_UP, Decimal

AMOUNT_RE = re.compile(r"[0-9]{1,9}(\.[0-9]{1,2})?")

SUPPORTED = {"USD": 2, "EUR": 2, "GBP": 2}


def to_minor(value: str, currency: str) -> int:
    exp = SUPPORTED.get(currency)
    if exp is None:
        raise ValueError(f"unsupported currency {currency}")
    if not isinstance(value, str) or not AMOUNT_RE.fullmatch(value):
        raise ValueError(f"invalid amount {value!r}: expected plain decimal like 12.34")
    d = Decimal(value)
    if d != d.quantize(Decimal(1).scaleb(-exp)):
        raise ValueError(f"amount {value} has more precision than {currency} allows")
    return int((d * (10 ** exp)).to_integral_value(rounding=ROUND_HALF_UP))


def to_str(minor: int, currency: str) -> str:
    exp = SUPPORTED[currency]
    return str((Decimal(minor) / (10 ** exp)).quantize(Decimal(1).scaleb(-exp)))
