from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _coerce_scalar(value: Any, errors: str) -> float:
    if value is None or value is pd.NA:
        return float("nan")
    try:
        if isinstance(value, str) and not value.strip():
            return float("nan")
        return float(value)
    except (TypeError, ValueError, OverflowError):
        if errors == "coerce":
            return float("nan")
        raise


def safe_to_numeric(
    arg: Any,
    errors: str = "raise",
    downcast: str | None = None,
    dtype_backend: Any = None,
) -> Any:
    """Deterministic numeric conversion used by FIN-ABS-004.

    The hosted pandas build observed during the benchmark returned a bound
    method in the first element of otherwise numeric arrays. This replacement
    is deliberately small: it preserves Series/Index shape and name, fast-paths
    numeric dtypes, and supports the `raise`/`coerce` behavior used here. It
    never imputes or changes a valid numeric value.
    """
    del downcast, dtype_backend
    if errors not in {"raise", "coerce", "ignore"}:
        raise ValueError(f"invalid errors policy: {errors}")
    if np.isscalar(arg) and not isinstance(arg, (pd.Series, pd.Index)):
        if errors == "ignore":
            try:
                return _coerce_scalar(arg, "raise")
            except (TypeError, ValueError, OverflowError):
                return arg
        return _coerce_scalar(arg, errors)

    if isinstance(arg, pd.Series):
        if pd.api.types.is_numeric_dtype(arg.dtype):
            values = arg.to_numpy(dtype=float, na_value=np.nan, copy=True)
        else:
            try:
                values = np.asarray(arg.to_numpy(copy=False), dtype=float)
            except (TypeError, ValueError, OverflowError):
                if errors == "ignore":
                    return arg.copy()
                values = np.fromiter(
                    (_coerce_scalar(value, errors) for value in arg.array),
                    dtype=float,
                    count=len(arg),
                )
        return pd.Series(values, index=arg.index, name=arg.name)

    if isinstance(arg, pd.Index):
        series = pd.Series(arg.to_numpy(copy=False), name=arg.name)
        converted = safe_to_numeric(series, errors=errors)
        if converted is series:
            return arg.copy()
        return pd.Index(converted.to_numpy(), name=arg.name)

    array = np.asarray(arg)
    if np.issubdtype(array.dtype, np.number):
        return array.astype(float, copy=True)
    try:
        return array.astype(float)
    except (TypeError, ValueError, OverflowError):
        if errors == "ignore":
            return arg
        return np.fromiter(
            (_coerce_scalar(value, errors) for value in array.ravel()),
            dtype=float,
            count=array.size,
        ).reshape(array.shape)


def install_safe_numeric_conversion() -> None:
    probe = pd.Series([100.0, 110.0])
    try:
        observed = pd.to_numeric(probe, errors="coerce")
        healthy = (
            isinstance(observed, pd.Series)
            and len(observed) == 2
            and float(observed.iloc[0]) == 100.0
            and float(observed.iloc[1]) == 110.0
        )
    except Exception:
        healthy = False
    if not healthy:
        pd.to_numeric = safe_to_numeric  # type: ignore[assignment]
