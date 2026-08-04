from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


def json_value(value: Any) -> Any:
    """Convert benchmark evidence to a deterministic JSON-safe value.

    Missing numeric values become JSON null. Non-finite infinities fail closed.
    Dates retain ISO-8601 semantics instead of being coerced through locale- or
    repr-dependent strings.
    """
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            raise ValueError("non-finite infinity cannot enter evidence JSON")
        return value
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported evidence value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def install_panel_serialization(panel_module: Any) -> None:
    """Install the serializer only in the FDIC panel module.

    This avoids global monkeypatching of pandas or json while repairing the
    precise boundary that failed after the panel had been constructed.
    """
    panel_module.canonical = canonical_json
    panel_module.digest = digest_json
