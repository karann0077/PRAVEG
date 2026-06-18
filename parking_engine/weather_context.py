"""Weather and rain-shelter context for parking hotspot rows.

This module is deliberately standalone so the V2 weather slice can be merged
into the central feature pipeline later without changing the existing trainer.
It fetches historical hourly rain from Open-Meteo for Bengaluru by default,
caches raw API payloads on disk, normalizes timestamps to local ``target_hour``,
and derives OSM bridge/underpass shelter features from available road metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests


BENGALURU_LATITUDE = 12.9716
BENGALURU_LONGITUDE = 77.5946
BENGALURU_TIMEZONE = "Asia/Kolkata"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_WEATHER_CACHE_DIR = Path("artifacts/weather/open_meteo")
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RAIN_THRESHOLD_MM = 0.0

_HOURLY_VARIABLES = ("rain", "precipitation")
_TAG_CONTAINER_COLUMNS = (
    "osm_tags",
    "tags",
    "road_tags",
    "road_metadata",
    "metadata",
    "osm_metadata",
)
_STRUCTURE_TAG_KEYS = (
    "bridge",
    "tunnel",
    "covered",
    "layer",
    "location",
    "structure",
    "man_made",
)
_TEXT_HINT_COLUMNS = (
    "road_name",
    "name",
    "junction_name",
    "representative_location",
    "location",
    "description",
)
_FALSEY_OSM_VALUES = {"", "0", "false", "no", "none", "null", "nan", "n/a", "unknown"}
_STRUCTURE_TEXT_RE = re.compile(
    r"\b("
    r"bridge|flyover|overpass|underpass|under\s+pass|underbridge|under\s+bridge|"
    r"subway|tunnel|viaduct|grade\s+separator|grade-separated"
    r")\b",
    flags=re.IGNORECASE,
)


__all__ = [
    "BENGALURU_LATITUDE",
    "BENGALURU_LONGITUDE",
    "BENGALURU_TIMEZONE",
    "fetch_bengaluru_hourly_weather",
    "fetch_open_meteo_hourly_weather",
    "is_underpass_or_bridge",
    "merge_weather_context",
]


def fetch_bengaluru_hourly_weather(
    start: str | date | datetime | pd.Timestamp,
    end: str | date | datetime | pd.Timestamp,
    **kwargs: Any,
) -> pd.DataFrame:
    """Fetch cached historical hourly rain for Bengaluru.

    Parameters are passed through to :func:`fetch_open_meteo_hourly_weather`.
    Date-only ``end`` values include the whole local day.
    """

    return fetch_open_meteo_hourly_weather(
        start,
        end,
        latitude=BENGALURU_LATITUDE,
        longitude=BENGALURU_LONGITUDE,
        timezone=BENGALURU_TIMEZONE,
        **kwargs,
    )


def fetch_open_meteo_hourly_weather(
    start: str | date | datetime | pd.Timestamp,
    end: str | date | datetime | pd.Timestamp,
    *,
    latitude: float = BENGALURU_LATITUDE,
    longitude: float = BENGALURU_LONGITUDE,
    timezone: str = BENGALURU_TIMEZONE,
    cache_dir: str | Path = DEFAULT_WEATHER_CACHE_DIR,
    rain_threshold_mm: float = DEFAULT_RAIN_THRESHOLD_MM,
    force_refresh: bool = False,
    allow_missing: bool = False,
    session: requests.Session | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """Fetch Open-Meteo archive rain, cache it, and return local hourly rows.

    Returns a DataFrame with ``target_hour``, ``rainfall_mm``, and
    ``is_raining``. ``target_hour`` is timezone-normalized to local naive
    timestamps, matching the existing modeling frame convention.
    """

    start_hour, end_hour = _normalize_hour_bounds(start, end, timezone)
    params = {
        "latitude": round(float(latitude), 6),
        "longitude": round(float(longitude), 6),
        "start_date": start_hour.date().isoformat(),
        "end_date": end_hour.date().isoformat(),
        "hourly": ",".join(_HOURLY_VARIABLES),
        "timezone": timezone,
    }
    cache_path = _cache_path(cache_dir, params)

    if cache_path.exists() and not force_refresh:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        client = session or requests
        response = client.get(
            OPEN_METEO_ARCHIVE_URL,
            params=params,
            headers={"User-Agent": "parking-enforcement-engine/0.1 weather-context"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            reason = payload.get("reason", "Open-Meteo returned an error")
            raise RuntimeError(str(reason))
        payload["_request"] = params
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

    return _payload_to_weather_frame(
        payload,
        start_hour=start_hour,
        end_hour=end_hour,
        timezone=timezone,
        rain_threshold_mm=rain_threshold_mm,
        allow_missing=allow_missing,
    )


def is_underpass_or_bridge(
    metadata: pd.DataFrame | pd.Series | Mapping[str, Any],
) -> pd.Series | bool:
    """Infer whether road metadata describes a bridge, flyover, or underpass.

    OSM tags such as ``bridge``, ``tunnel``, ``covered``, ``layer``, and
    ``location`` are preferred. When explicit tags are unavailable, road/name
    text is used as a fallback.
    """

    if isinstance(metadata, pd.DataFrame):
        values = metadata.apply(_metadata_row_is_structure, axis=1)
        return pd.Series(values.astype("int8"), index=metadata.index, name="is_underpass_or_bridge")
    if isinstance(metadata, pd.Series):
        return bool(_metadata_row_is_structure(metadata))
    return bool(_metadata_row_is_structure(pd.Series(dict(metadata))))


def merge_weather_context(
    modeling_frame: pd.DataFrame,
    *,
    segment_metadata: pd.DataFrame | None = None,
    weather: pd.DataFrame | None = None,
    start: str | date | datetime | pd.Timestamp | None = None,
    end: str | date | datetime | pd.Timestamp | None = None,
    latitude: float = BENGALURU_LATITUDE,
    longitude: float = BENGALURU_LONGITUDE,
    timezone: str = BENGALURU_TIMEZONE,
    cache_dir: str | Path = DEFAULT_WEATHER_CACHE_DIR,
    rain_threshold_mm: float = DEFAULT_RAIN_THRESHOLD_MM,
    force_refresh: bool = False,
    allow_missing_weather: bool = False,
) -> pd.DataFrame:
    """Merge weather and rain-shelter features into a modeling frame.

    The input must include ``target_hour``. If ``weather`` is omitted, hourly
    weather is fetched for the target-hour span. If segment metadata is supplied
    and both frames include ``segment_id``, bridge/underpass flags are joined by
    segment. Otherwise, the function tries to infer the flag from columns
    already present on ``modeling_frame``.
    """

    if "target_hour" not in modeling_frame.columns:
        raise KeyError("modeling_frame must include a target_hour column")

    frame = modeling_frame.copy()
    frame["target_hour"] = _coerce_target_hours(frame["target_hour"], timezone)
    if frame["target_hour"].isna().any():
        raise ValueError("modeling_frame contains target_hour values that could not be parsed")

    if frame.empty:
        return _empty_weather_enriched_frame(frame)

    if weather is None:
        weather_start = start if start is not None else frame["target_hour"].min()
        weather_end = end if end is not None else frame["target_hour"].max()
        weather_frame = fetch_open_meteo_hourly_weather(
            weather_start,
            weather_end,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            cache_dir=cache_dir,
            rain_threshold_mm=rain_threshold_mm,
            force_refresh=force_refresh,
            allow_missing=allow_missing_weather,
        )
    else:
        weather_frame = _prepare_weather_frame(weather, timezone, rain_threshold_mm)

    enriched = frame.merge(
        weather_frame[["target_hour", "rainfall_mm", "is_raining"]],
        on="target_hour",
        how="left",
    )
    missing_weather = enriched["rainfall_mm"].isna()
    if missing_weather.any() and not allow_missing_weather:
        sample = (
            enriched.loc[missing_weather, "target_hour"]
            .drop_duplicates()
            .sort_values()
            .head(5)
            .astype(str)
            .tolist()
        )
        raise ValueError(
            "Weather frame is missing rainfall for "
            f"{int(missing_weather.sum())} rows; sample target_hour values: {sample}"
        )
    enriched["rainfall_mm"] = pd.to_numeric(enriched["rainfall_mm"], errors="coerce").fillna(0.0)
    enriched["is_raining"] = (
        pd.to_numeric(enriched["is_raining"], errors="coerce").fillna(0).astype("int8")
    )

    enriched["is_underpass_or_bridge"] = _infer_structure_flags(enriched, segment_metadata)
    enriched["rain_shelter_bottleneck"] = (
        enriched["is_raining"].astype("int8") * enriched["is_underpass_or_bridge"].astype("int8")
    ).astype("int8")
    return enriched


def _normalize_hour_bounds(
    start: str | date | datetime | pd.Timestamp,
    end: str | date | datetime | pd.Timestamp,
    timezone: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_hour = _coerce_single_hour(start, timezone, end_of_day_if_date=False)
    end_hour = _coerce_single_hour(end, timezone, end_of_day_if_date=True)
    if pd.isna(start_hour) or pd.isna(end_hour):
        raise ValueError("start and end must be parseable datetimes")
    if end_hour < start_hour:
        raise ValueError("end must be greater than or equal to start")
    return start_hour, end_hour


def _coerce_single_hour(
    value: str | date | datetime | pd.Timestamp,
    timezone: str,
    *,
    end_of_day_if_date: bool,
) -> pd.Timestamp:
    date_only = _looks_date_only(value)
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(timezone).tz_localize(None)
    timestamp = timestamp.floor("h")
    if date_only and end_of_day_if_date:
        timestamp = timestamp + pd.Timedelta(hours=23)
    return timestamp


def _looks_date_only(value: object) -> bool:
    if isinstance(value, datetime):
        return False
    if isinstance(value, date):
        return True
    if isinstance(value, str):
        return bool(re.fullmatch(r"\s*\d{4}-\d{2}-\d{2}\s*", value))
    return False


def _coerce_target_hours(values: pd.Series, timezone: str) -> pd.Series:
    source = pd.Series(values, index=values.index if isinstance(values, pd.Series) else None)
    parsed = pd.to_datetime(source, errors="coerce")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_convert(timezone).dt.tz_localize(None)
        return parsed.dt.floor("h")
    if pd.api.types.is_datetime64_any_dtype(parsed):
        return parsed.dt.floor("h")
    return source.map(lambda value: _coerce_single_hour(value, timezone, end_of_day_if_date=False))


def _cache_path(cache_dir: str | Path, params: Mapping[str, Any]) -> Path:
    normalized = json.dumps(params, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    name = f"open_meteo_bengaluru_{params['start_date']}_{params['end_date']}_{digest}.json"
    return Path(cache_dir) / name


def _payload_to_weather_frame(
    payload: Mapping[str, Any],
    *,
    start_hour: pd.Timestamp,
    end_hour: pd.Timestamp,
    timezone: str,
    rain_threshold_mm: float,
    allow_missing: bool,
) -> pd.DataFrame:
    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping):
        raise ValueError("Open-Meteo payload does not contain an hourly section")
    if "time" not in hourly:
        raise ValueError("Open-Meteo hourly payload does not contain time")

    rain_values = hourly.get("rain", hourly.get("precipitation"))
    if rain_values is None:
        raise ValueError("Open-Meteo hourly payload does not contain rain or precipitation")

    weather = pd.DataFrame(
        {
            "target_hour": _coerce_target_hours(pd.Series(hourly["time"]), timezone),
            "rainfall_mm": pd.to_numeric(pd.Series(rain_values), errors="coerce"),
        }
    )
    weather = weather.dropna(subset=["target_hour"])
    weather = weather.drop_duplicates("target_hour", keep="last")
    weather = weather.loc[
        (weather["target_hour"] >= start_hour) & (weather["target_hour"] <= end_hour)
    ]

    expected_hours = pd.DataFrame(
        {"target_hour": pd.date_range(start_hour, end_hour, freq="h").to_series(index=None)}
    )
    weather = expected_hours.merge(weather, on="target_hour", how="left")
    missing = weather["rainfall_mm"].isna()
    if missing.any() and not allow_missing:
        sample = weather.loc[missing, "target_hour"].head(5).astype(str).tolist()
        raise ValueError(
            "Open-Meteo response is missing rainfall for "
            f"{int(missing.sum())} requested hours; sample target_hour values: {sample}"
        )
    weather["rainfall_mm"] = weather["rainfall_mm"].fillna(0.0).astype(float)
    weather["is_raining"] = (weather["rainfall_mm"] > float(rain_threshold_mm)).astype("int8")
    return weather[["target_hour", "rainfall_mm", "is_raining"]]


def _prepare_weather_frame(
    weather: pd.DataFrame,
    timezone: str,
    rain_threshold_mm: float,
) -> pd.DataFrame:
    if "target_hour" not in weather.columns:
        if "time" not in weather.columns:
            raise KeyError("weather must include target_hour or time")
        weather = weather.rename(columns={"time": "target_hour"})

    prepared = weather.copy()
    prepared["target_hour"] = _coerce_target_hours(prepared["target_hour"], timezone)
    if "rainfall_mm" not in prepared.columns:
        if "rain" in prepared.columns:
            prepared["rainfall_mm"] = prepared["rain"]
        elif "precipitation" in prepared.columns:
            prepared["rainfall_mm"] = prepared["precipitation"]
        else:
            raise KeyError("weather must include rainfall_mm, rain, or precipitation")
    prepared["rainfall_mm"] = pd.to_numeric(prepared["rainfall_mm"], errors="coerce")
    if "is_raining" not in prepared.columns:
        prepared["is_raining"] = (prepared["rainfall_mm"] > float(rain_threshold_mm)).astype("int8")
    else:
        prepared["is_raining"] = pd.to_numeric(prepared["is_raining"], errors="coerce").fillna(0)
        prepared["is_raining"] = (prepared["is_raining"] > 0).astype("int8")
    return prepared[["target_hour", "rainfall_mm", "is_raining"]].drop_duplicates(
        "target_hour", keep="last"
    )


def _empty_weather_enriched_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["rainfall_mm"] = pd.Series(dtype="float64")
    out["is_raining"] = pd.Series(dtype="int8")
    out["is_underpass_or_bridge"] = pd.Series(dtype="int8")
    out["rain_shelter_bottleneck"] = pd.Series(dtype="int8")
    return out


def _infer_structure_flags(
    frame: pd.DataFrame,
    segment_metadata: pd.DataFrame | None,
) -> pd.Series:
    fallback = is_underpass_or_bridge(frame)
    if not isinstance(fallback, pd.Series):
        fallback = pd.Series([int(bool(fallback))] * len(frame), index=frame.index)

    if segment_metadata is None or segment_metadata.empty:
        return fallback.astype("int8")

    meta_flags = is_underpass_or_bridge(segment_metadata)
    if not isinstance(meta_flags, pd.Series):
        return fallback.astype("int8")

    if "segment_id" in frame.columns and "segment_id" in segment_metadata.columns:
        flag_table = pd.DataFrame(
            {
                "segment_id": segment_metadata["segment_id"].astype(str),
                "_is_underpass_or_bridge": meta_flags.astype("float64"),
            }
        ).drop_duplicates("segment_id", keep="first")
        joined = pd.DataFrame({"segment_id": frame["segment_id"].astype(str)}, index=frame.index)
        joined = joined.merge(flag_table, on="segment_id", how="left")
        flags = pd.Series(joined["_is_underpass_or_bridge"].to_numpy(), index=frame.index)
        flags = flags.fillna(fallback.astype("float64"))
        return flags.fillna(0).astype("int8")

    if len(segment_metadata) == len(frame):
        flags = meta_flags.reset_index(drop=True).reindex(range(len(frame))).fillna(0)
        flags.index = frame.index
        return flags.astype("int8")

    return fallback.astype("int8")


def _metadata_row_is_structure(row: pd.Series) -> bool:
    tags = _extract_tags(row)
    if _positive_osm_tag(tags.get("bridge")):
        return True
    if _positive_osm_tag(tags.get("tunnel")):
        return True
    if _positive_osm_tag(tags.get("covered")):
        return True
    if _positive_osm_tag(tags.get("man_made")) and _clean_tag_value(tags.get("man_made")) == "bridge":
        return True
    if _clean_tag_value(tags.get("location")) in {"underground", "overground", "overhead"}:
        return True
    if _clean_tag_value(tags.get("structure")) in {"bridge", "flyover", "underpass", "tunnel", "viaduct"}:
        return True
    if _nonzero_layer(tags.get("layer")):
        return True

    text = " ".join(str(row.get(col, "")) for col in _TEXT_HINT_COLUMNS if col in row.index)
    return bool(_STRUCTURE_TEXT_RE.search(text))


def _extract_tags(row: pd.Series) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    for key, value in row.items():
        key_text = str(key).lower()
        if key_text in _TAG_CONTAINER_COLUMNS:
            tags.update(_parse_tag_container(value))
        elif key_text in _STRUCTURE_TAG_KEYS:
            tags[key_text] = value
        elif key_text.startswith("osm_") and key_text[4:] in _STRUCTURE_TAG_KEYS:
            tags[key_text[4:]] = value
        elif key_text.startswith("tag_") and key_text[4:] in _STRUCTURE_TAG_KEYS:
            tags[key_text[4:]] = value
    return tags


def _parse_tag_container(value: Any) -> dict[str, Any]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in _FALSEY_OSM_VALUES:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return _parse_key_value_text(text)

    if isinstance(parsed, Mapping):
        if isinstance(parsed.get("tags"), Mapping):
            parsed = parsed["tags"]
        return {str(key).lower(): val for key, val in parsed.items()}
    return {}


def _parse_key_value_text(text: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for part in re.split(r"[;,]", text):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        tags[key.strip().lower()] = value.strip()
    return tags


def _positive_osm_tag(value: Any) -> bool:
    cleaned = _clean_tag_value(value)
    if cleaned in _FALSEY_OSM_VALUES:
        return False
    return cleaned != ""


def _clean_tag_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip().lower()


def _nonzero_layer(value: Any) -> bool:
    cleaned = _clean_tag_value(value)
    if cleaned in _FALSEY_OSM_VALUES:
        return False
    try:
        return float(cleaned) != 0.0
    except ValueError:
        return False
