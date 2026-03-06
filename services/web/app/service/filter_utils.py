import pandas as pd
from pandas.api.types import (
    is_numeric_dtype,
    is_bool_dtype,
    is_datetime64_any_dtype,
)
from typing import Optional

PUBLIC_TO_INTERNAL_FILTER_COLUMNS = {
    "Productivity": "_ProductivityNum",
    "Reject Ratio": "_RejectRatioNum",
    "Rework Ratio": "_ReworkRatioNum",
    "StartTime": "_StartTs",
    "StopTime": "_StopTs",
}

def _resolve_filter_column(df: pd.DataFrame, field: str) -> Optional[str]:
    mapped = PUBLIC_TO_INTERNAL_FILTER_COLUMNS.get(field, field)
    return mapped if mapped in df.columns else None


def _is_effectively_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _series_as_string(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str)


def _series_as_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _series_as_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _infer_filter_type(series: pd.Series, requested_type: Optional[str]) -> str:
    if requested_type in {"string", "number", "date", "boolean"}:
        return requested_type

    if is_bool_dtype(series):
        return "boolean"
    if is_numeric_dtype(series):
        return "number"
    if is_datetime64_any_dtype(series):
        return "date"

    # try datetime inference for object/string timestamp-like columns
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.notna().any() and parsed.notna().sum() >= max(1, len(series) // 2):
        return "date"

    return "string"


def _build_string_mask(series: pd.Series, cond) -> pd.Series:
    s = _series_as_string(series).str.lower()

    mask = pd.Series(True, index=series.index)

    if cond.equals is not None:
        mask &= s == str(cond.equals).lower()

    if cond.not_equals is not None:
        mask &= s != str(cond.not_equals).lower()

    if cond.contains is not None:
        mask &= s.str.contains(str(cond.contains).lower(), na=False, regex=False)

    if cond.not_contains is not None:
        mask &= ~s.str.contains(str(cond.not_contains).lower(), na=False, regex=False)

    if cond.starts_with is not None:
        mask &= s.str.startswith(str(cond.starts_with).lower(), na=False)

    if cond.ends_with is not None:
        mask &= s.str.endswith(str(cond.ends_with).lower(), na=False)

    if cond.in_list:
        allowed = {str(v).lower() for v in cond.in_list}
        mask &= s.isin(allowed)

    if cond.not_in:
        blocked = {str(v).lower() for v in cond.not_in}
        mask &= ~s.isin(blocked)

    if cond.is_empty:
        mask &= s.str.strip() == ""

    if cond.is_not_empty:
        mask &= s.str.strip() != ""

    if cond.between and len(cond.between) == 2:
        lo = str(cond.between[0]).lower() if cond.between[0] is not None else None
        hi = str(cond.between[1]).lower() if cond.between[1] is not None else None
        if lo is not None:
            mask &= s >= lo
        if hi is not None:
            mask &= s <= hi

    return mask


def _build_number_mask(series: pd.Series, cond) -> pd.Series:
    s = _series_as_number(series)
    mask = pd.Series(True, index=series.index)

    if cond.equals is not None:
        mask &= s == float(cond.equals)

    if cond.not_equals is not None:
        mask &= s != float(cond.not_equals)

    if cond.gt is not None:
        mask &= s > float(cond.gt)

    if cond.gte is not None:
        mask &= s >= float(cond.gte)

    if cond.lt is not None:
        mask &= s < float(cond.lt)

    if cond.lte is not None:
        mask &= s <= float(cond.lte)

    if cond.in_list:
        allowed = pd.to_numeric(pd.Series(cond.in_list), errors="coerce").dropna().tolist()
        mask &= s.isin(allowed)

    if cond.not_in:
        blocked = pd.to_numeric(pd.Series(cond.not_in), errors="coerce").dropna().tolist()
        mask &= ~s.isin(blocked)

    if cond.between and len(cond.between) == 2:
        lo = pd.to_numeric(pd.Series([cond.between[0]]), errors="coerce").iloc[0]
        hi = pd.to_numeric(pd.Series([cond.between[1]]), errors="coerce").iloc[0]
        if not pd.isna(lo):
            mask &= s >= lo
        if not pd.isna(hi):
            mask &= s <= hi

    if cond.is_empty:
        mask &= s.isna()

    if cond.is_not_empty:
        mask &= s.notna()

    return mask


def _build_date_mask(series: pd.Series, cond) -> pd.Series:
    s = _series_as_datetime(series)
    mask = pd.Series(True, index=series.index)

    def _dt(value):
        if value is None:
            return None
        ts = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(ts) else ts

    eq = _dt(cond.equals)
    neq = _dt(cond.not_equals)
    before = _dt(cond.before)
    after = _dt(cond.after)
    on_or_before = _dt(cond.on_or_before)
    on_or_after = _dt(cond.on_or_after)

    if eq is not None:
        mask &= s == eq

    if neq is not None:
        mask &= s != neq

    if after is not None:
        mask &= s > after

    if on_or_after is not None:
        mask &= s >= on_or_after

    if before is not None:
        mask &= s < before

    if on_or_before is not None:
        mask &= s <= on_or_before

    if cond.between and len(cond.between) == 2:
        lo = _dt(cond.between[0])
        hi = _dt(cond.between[1])
        if lo is not None:
            mask &= s >= lo
        if hi is not None:
            mask &= s <= hi

    if cond.in_list:
        allowed = pd.to_datetime(pd.Series(cond.in_list), errors="coerce").dropna().tolist()
        mask &= s.isin(allowed)

    if cond.not_in:
        blocked = pd.to_datetime(pd.Series(cond.not_in), errors="coerce").dropna().tolist()
        mask &= ~s.isin(blocked)

    if cond.is_empty:
        mask &= s.isna()

    if cond.is_not_empty:
        mask &= s.notna()

    return mask


def _build_boolean_mask(series: pd.Series, cond) -> pd.Series:
    s = series.astype("boolean")
    mask = pd.Series(True, index=series.index)

    def _to_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.strip().lower()
            if lower in {"true", "1", "yes"}:
                return True
            if lower in {"false", "0", "no"}:
                return False
        return value

    if cond.equals is not None:
        mask &= s == _to_bool(cond.equals)

    if cond.not_equals is not None:
        mask &= s != _to_bool(cond.not_equals)

    if cond.in_list:
        allowed = [_to_bool(v) for v in cond.in_list]
        mask &= s.isin(allowed)

    if cond.not_in:
        blocked = [_to_bool(v) for v in cond.not_in]
        mask &= ~s.isin(blocked)

    if cond.is_empty:
        mask &= s.isna()

    if cond.is_not_empty:
        mask &= s.notna()

    return mask


def apply_filters(df: pd.DataFrame, filters) -> pd.DataFrame:
    if not filters or df is None or df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    for field, cond in filters.items():
        if cond is None:
            continue

        col = _resolve_filter_column(df, field)
        if not col:
            # ignore unknown columns instead of failing
            continue

        series = df[col]
        filter_type = _infer_filter_type(series, getattr(cond, "type", None))

        if filter_type == "number":
            field_mask = _build_number_mask(series, cond)
        elif filter_type == "date":
            field_mask = _build_date_mask(series, cond)
        elif filter_type == "boolean":
            field_mask = _build_boolean_mask(series, cond)
        else:
            field_mask = _build_string_mask(series, cond)

        mask &= field_mask.fillna(False)

    return df[mask].copy()
