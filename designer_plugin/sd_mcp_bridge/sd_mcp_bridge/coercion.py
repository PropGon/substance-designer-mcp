"""Converts raw JSON into the scalar type a Designer property expects. Standard library only."""

from __future__ import annotations

import math
import re

# Stricter than float(), which would also accept "nan", "inf" and "1_000".
_NUMBER_RE = re.compile(r"^\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*$")


def coerce_scalar(type_id: str, raw: object):
    """Returns the converted value, or raises ValueError.

    MCP clients and models may send numbers and booleans as text ("5", "true"). The expected
    type is known here, so text is converted, while bool and number never stand in for each other.
    """
    if type_id == "string":
        if isinstance(raw, str):
            return raw
    elif type_id == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
    elif not isinstance(raw, bool):
        number = raw
        if isinstance(raw, str) and _NUMBER_RE.match(raw):
            number = float(raw)
        if isinstance(number, (int, float)) and math.isfinite(number):
            if type_id in ("float", "double"):
                return float(number)
            if type_id == "int" and float(number).is_integer():
                return int(number)
    raise ValueError(f"se esperaba {type_id}, no {raw!r}")
