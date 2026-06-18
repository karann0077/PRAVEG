"""Legal parking supply and overflow-risk helpers.

This module is intentionally independent from the central feature pipeline so
the V2 parking-supply slice can be integrated later without touching training
or config code. It fetches OSM ``amenity=parking`` features for Bengaluru,
estimates legal capacity, and joins nearest legal supply to modeled road
segments with a cKDTree in EPSG:32643 meters.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree
from shapely import wkt
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform


BENGALURU_PLACE = "Bengaluru, Karnataka, India"
DEFAULT_PARKING_CACHE = Path("artifacts/osm/bengaluru_parking.json")
DEFAULT_PARKING_CAPACITY = 8.0
PARKING_AREA_PER_SPACE_M2 = 15.0
EPSG32643_CENTRAL_MERIDIAN_DEG = 75.0

_CACHE_VERSION = "parking_supply_v1"
_USER_AGENT = "parking-enforcement-engine/0.1"
_CAPACITY_TAGS = (
    "capacity",
    "capacity:car",
    "capacity:cars",
    "capacity:motorcar",
    "capacity:motor_vehicle",
)
_VOLUME_COLUMNS = (
    "historical_volume",
    "segment_total_events",
    "event_count",
    "count_total",
    "predicted_total",
    "volume",
)


def fetch_bengaluru_parking_supply(
    cache_path: str | Path = DEFAULT_PARKING_CACHE,
    place: str = BENGALURU_PLACE,
    source: Literal["auto", "overpass", "osmnx"] = "auto",
    refresh: bool = False,
    timeout: int = 240,
) -> pd.DataFrame:
    """Fetch or load Bengaluru OSM ``amenity=parking`` supply.

    Parameters
    ----------
    cache_path:
        JSON cache path. Existing normalized caches are reused unless
        ``refresh=True``.
    place:
        OSMnx place name used when the optional OSMnx stack is installed.
    source:
        ``"auto"`` tries OSMnx when installed and falls back to Overpass.
        ``"overpass"`` and ``"osmnx"`` force one backend.
    refresh:
        Ignore an existing cache and fetch again.
    timeout:
        HTTP timeout for the Overpass request.

    Returns
    -------
    pandas.DataFrame
        One row per legal parking feature with ``lat``, ``lon``,
        ``geometry_wkt``, ``area_m2``, ``estimated_capacity``, and
        ``capacity_source`` columns.
    """

    cache = Path(cache_path)
    if cache.exists() and not refresh:
        return _load_parking_cache(cache)

    if source not in {"auto", "overpass", "osmnx"}:
        raise ValueError("source must be one of: 'auto', 'overpass', 'osmnx'")

    errors: list[str] = []
    parking: pd.DataFrame | None = None
    source_used = source

    if source in {"auto", "osmnx"}:
        try:
            parking = _fetch_parking_from_osmnx(place)
            source_used = "osmnx"
        except ModuleNotFoundError as exc:
            errors.append(f"osmnx unavailable: {exc}")
            if source == "osmnx":
                raise RuntimeError("OSMnx is not installed.") from exc
        except Exception as exc:
            errors.append(f"osmnx failed: {exc}")
            if source == "osmnx":
                raise

    if parking is None and source in {"auto", "overpass"}:
        try:
            parking = _fetch_parking_from_overpass(timeout=timeout)
            source_used = "overpass"
        except Exception as exc:
            errors.append(f"overpass failed: {exc}")
            raise RuntimeError(
                "Unable to fetch Bengaluru legal parking supply. "
                + "; ".join(errors)
            ) from exc

    if parking is None:
        raise RuntimeError("Unable to fetch Bengaluru legal parking supply. " + "; ".join(errors))

    parking = estimate_parking_capacity(parking, default_capacity=DEFAULT_PARKING_CAPACITY)
    parking["source"] = source_used
    _write_parking_cache(parking, cache, source_used)
    return parking.reset_index(drop=True)


def estimate_parking_capacity(
    parking_supply: pd.DataFrame,
    default_capacity: float = DEFAULT_PARKING_CAPACITY,
    area_per_space_m2: float = PARKING_AREA_PER_SPACE_M2,
) -> pd.DataFrame:
    """Estimate legal parking capacity from OSM tags or polygon area.

    OSM ``capacity`` tags are preferred. When no usable capacity tag is present
    and polygon or multipolygon geometry exists, area is measured in
    EPSG:32643 meters and divided by ``area_per_space_m2``. Rows without usable
    capacity tags or polygon area receive ``default_capacity``.
    """

    frame = parking_supply.copy()
    if frame.empty:
        for col in ["capacity_tag", "area_m2", "estimated_capacity", "capacity_source"]:
            if col not in frame.columns:
                frame[col] = pd.Series(dtype="float64" if col != "capacity_source" else "object")
        return frame

    capacities: list[float] = []
    capacity_tags: list[str] = []
    areas: list[float] = []
    sources: list[str] = []

    for _, row in frame.iterrows():
        tags = _row_tags(row)
        capacity_tag_value = _first_present_tag(tags, _CAPACITY_TAGS)
        parsed_capacity = _parse_capacity(capacity_tag_value)
        geometry = _row_geometry(row)
        area_m2 = _area_m2_epsg32643(geometry)

        if parsed_capacity is not None:
            capacity = parsed_capacity
            source = "osm_capacity_tag"
        elif area_m2 is not None and area_m2 > 0:
            capacity = max(1.0, area_m2 / float(area_per_space_m2))
            source = "polygon_area_imputed"
        else:
            capacity = float(default_capacity)
            source = "conservative_default"

        capacities.append(float(capacity))
        capacity_tags.append("" if capacity_tag_value is None else str(capacity_tag_value))
        areas.append(float(area_m2) if area_m2 is not None else np.nan)
        sources.append(source)

    frame["capacity_tag"] = capacity_tags
    frame["area_m2"] = areas
    frame["estimated_capacity"] = capacities
    frame["capacity_source"] = sources
    return frame


def lookup_nearest_legal_parking(
    segments: pd.DataFrame,
    parking_supply: pd.DataFrame,
    segment_lat_col: str | None = None,
    segment_lon_col: str | None = None,
    default_capacity: float = DEFAULT_PARKING_CAPACITY,
) -> pd.DataFrame:
    """Attach nearest legal parking distance and capacity to segment centers."""

    segment_centers = _segment_centers(segments, segment_lat_col, segment_lon_col)
    result = segment_centers[["segment_id"]].copy()
    result["dist_to_legal_parking_m"] = np.nan
    result["legal_parking_capacity"] = 0.0

    parking = estimate_parking_capacity(parking_supply, default_capacity=default_capacity)
    parking_centers = _parking_centers(parking)
    if segment_centers.empty or parking_centers.empty:
        return result

    parking_x, parking_y = _project_lonlat_to_epsg32643(
        parking_centers["lon"].to_numpy(dtype=float),
        parking_centers["lat"].to_numpy(dtype=float),
    )
    segment_x, segment_y = _project_lonlat_to_epsg32643(
        segment_centers["lon"].to_numpy(dtype=float),
        segment_centers["lat"].to_numpy(dtype=float),
    )

    tree = cKDTree(np.column_stack([parking_x, parking_y]))
    distances, indices = tree.query(np.column_stack([segment_x, segment_y]), k=1)

    nearest_capacity = parking_centers["estimated_capacity"].to_numpy(dtype=float)[indices]
    result["dist_to_legal_parking_m"] = distances.astype(float)
    result["legal_parking_capacity"] = nearest_capacity.astype(float)
    return result


def compute_legal_parking_overflow(
    segments: pd.DataFrame,
    historical_volume: pd.DataFrame | pd.Series | Mapping[str, float] | None = None,
    parking_supply: pd.DataFrame | None = None,
    parking_cache_path: str | Path = DEFAULT_PARKING_CACHE,
    source: Literal["auto", "overpass", "osmnx"] = "auto",
    volume_column: str | None = None,
    segment_lat_col: str | None = None,
    segment_lon_col: str | None = None,
    default_capacity: float = DEFAULT_PARKING_CAPACITY,
    distance_pressure_m: float = 500.0,
    volume_scale: float | None = None,
) -> pd.DataFrame:
    """Return legal-parking overflow features for modeled segments.

    The returned frame contains only:
    ``segment_id``, ``dist_to_legal_parking_m``, ``legal_parking_capacity``,
    and ``overflow_risk_index``.

    ``overflow_risk_index`` is a bounded 0-100 index. It increases with
    historical segment volume and distance to the nearest legal parking, and it
    decreases as nearby legal capacity grows.
    """

    if parking_supply is None:
        parking_supply = fetch_bengaluru_parking_supply(
            cache_path=parking_cache_path,
            source=source,
        )

    nearest = lookup_nearest_legal_parking(
        segments=segments,
        parking_supply=parking_supply,
        segment_lat_col=segment_lat_col,
        segment_lon_col=segment_lon_col,
        default_capacity=default_capacity,
    )
    volume = _historical_volume_by_segment(
        segments=segments,
        historical_volume=historical_volume,
        volume_column=volume_column,
    )
    nearest = nearest.merge(volume, on="segment_id", how="left")
    nearest["historical_volume"] = nearest["historical_volume"].fillna(0.0).clip(lower=0.0)

    nearest["overflow_risk_index"] = _overflow_risk_index(
        historical_volume=nearest["historical_volume"].to_numpy(dtype=float),
        distance_m=nearest["dist_to_legal_parking_m"].to_numpy(dtype=float),
        capacity=nearest["legal_parking_capacity"].to_numpy(dtype=float),
        default_capacity=default_capacity,
        distance_pressure_m=distance_pressure_m,
        volume_scale=volume_scale,
    )
    return nearest[
        [
            "segment_id",
            "dist_to_legal_parking_m",
            "legal_parking_capacity",
            "overflow_risk_index",
        ]
    ].reset_index(drop=True)


def _fetch_parking_from_overpass(timeout: int) -> pd.DataFrame:
    query = """
    [out:json][timeout:120];
    area["name"="Bengaluru"]["boundary"="administrative"]->.searchArea;
    (
      node["amenity"="parking"](area.searchArea);
      way["amenity"="parking"](area.searchArea);
      relation["amenity"="parking"](area.searchArea);
    );
    out tags center geom;
    """
    query = query.replace("[timeout:120]", f"[timeout:{int(timeout)}]")
    response = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return _parse_overpass_payload(payload)


def _fetch_parking_from_osmnx(place: str) -> pd.DataFrame:
    import osmnx as ox

    features = ox.features_from_place(place, tags={"amenity": "parking"})
    if features.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    features = features.reset_index()
    for _, row in features.iterrows():
        geometry = row.get("geometry")
        if geometry is None or geometry.is_empty:
            continue
        element_type = str(row.get("element_type", row.get("osmid", "feature")))
        osmid = row.get("osmid", row.get("id", ""))
        tags = {
            str(key): _json_safe(value)
            for key, value in row.drop(labels=["geometry"], errors="ignore").items()
            if pd.notna(value)
        }
        point = geometry.representative_point()
        rows.append(
            {
                "parking_id": f"{element_type}_{osmid}",
                "osm_type": element_type,
                "osm_id": str(osmid),
                "name": str(tags.get("name", "")),
                "amenity": "parking",
                "parking": str(tags.get("parking", "")),
                "lat": float(point.y),
                "lon": float(point.x),
                "geometry_wkt": geometry.wkt,
                "tags_json": json.dumps(tags, sort_keys=True),
            }
        )
    return pd.DataFrame(rows).drop_duplicates("parking_id").reset_index(drop=True)


def _parse_overpass_payload(payload: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {}) or {}
        geometry = _overpass_geometry(element)
        point = _element_point(element, geometry)
        if point is None:
            continue
        osm_type = str(element.get("type", "feature"))
        osm_id = str(element.get("id", ""))
        rows.append(
            {
                "parking_id": f"{osm_type}_{osm_id}",
                "osm_type": osm_type,
                "osm_id": osm_id,
                "name": str(tags.get("name", "")),
                "amenity": str(tags.get("amenity", "")),
                "parking": str(tags.get("parking", "")),
                "lat": float(point.y),
                "lon": float(point.x),
                "geometry_wkt": geometry.wkt if geometry is not None else point.wkt,
                "tags_json": json.dumps(tags, sort_keys=True),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "parking_id",
                "osm_type",
                "osm_id",
                "name",
                "amenity",
                "parking",
                "lat",
                "lon",
                "geometry_wkt",
                "tags_json",
            ]
        )
    return pd.DataFrame(rows).drop_duplicates("parking_id").reset_index(drop=True)


def _overpass_geometry(element: Mapping[str, Any]) -> BaseGeometry | None:
    if element.get("type") == "node" and "lon" in element and "lat" in element:
        return Point(float(element["lon"]), float(element["lat"]))

    raw_geometry = element.get("geometry") or []
    coords = [
        (float(point["lon"]), float(point["lat"]))
        for point in raw_geometry
        if "lon" in point and "lat" in point
    ]
    if len(coords) >= 4 and coords[0] == coords[-1]:
        return Polygon(coords)
    if len(coords) >= 2:
        return LineString(coords)

    center = element.get("center")
    if isinstance(center, Mapping) and "lon" in center and "lat" in center:
        return Point(float(center["lon"]), float(center["lat"]))
    return None


def _element_point(
    element: Mapping[str, Any],
    geometry: BaseGeometry | None,
) -> Point | None:
    if geometry is not None and not geometry.is_empty:
        return geometry.representative_point()

    center = element.get("center")
    if isinstance(center, Mapping) and "lon" in center and "lat" in center:
        return Point(float(center["lon"]), float(center["lat"]))
    if "lon" in element and "lat" in element:
        return Point(float(element["lon"]), float(element["lat"]))
    return None


def _load_parking_cache(cache: Path) -> pd.DataFrame:
    payload = json.loads(cache.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and payload.get("cache_version") == _CACHE_VERSION:
        records = payload.get("records", [])
        parking = pd.DataFrame(records)
    elif isinstance(payload, Mapping) and "elements" in payload:
        parking = _parse_overpass_payload(payload)
    else:
        parking = pd.DataFrame(payload)
    return estimate_parking_capacity(parking, default_capacity=DEFAULT_PARKING_CAPACITY)


def _write_parking_cache(parking: pd.DataFrame, cache: Path, source: str) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {str(key): _json_safe(value) for key, value in record.items()}
        for record in parking.to_dict(orient="records")
    ]
    payload = {
        "cache_version": _CACHE_VERSION,
        "source": source,
        "records": records,
    }
    cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parking_centers(parking: pd.DataFrame) -> pd.DataFrame:
    if parking.empty:
        return pd.DataFrame(columns=["lat", "lon", "estimated_capacity"])

    frame = parking.copy()
    if "estimated_capacity" not in frame.columns:
        frame = estimate_parking_capacity(frame)

    lats: list[float] = []
    lons: list[float] = []
    capacities: list[float] = []
    for _, row in frame.iterrows():
        lat = _coerce_float(row.get("lat"))
        lon = _coerce_float(row.get("lon"))
        if lat is None or lon is None:
            geometry = _row_geometry(row)
            if geometry is not None and not geometry.is_empty:
                point = geometry.representative_point()
                lat = float(point.y)
                lon = float(point.x)
        if lat is None or lon is None:
            continue
        capacity = _coerce_float(row.get("estimated_capacity"))
        lats.append(float(lat))
        lons.append(float(lon))
        capacities.append(float(capacity if capacity is not None else DEFAULT_PARKING_CAPACITY))

    return pd.DataFrame(
        {
            "lat": lats,
            "lon": lons,
            "estimated_capacity": capacities,
        }
    )


def _segment_centers(
    segments: pd.DataFrame,
    lat_col: str | None,
    lon_col: str | None,
) -> pd.DataFrame:
    if "segment_id" not in segments.columns:
        raise ValueError("segments must contain a 'segment_id' column")

    lat_col = lat_col or _first_existing_column(segments, ["lat_center", "lat_mean", "latitude"])
    lon_col = lon_col or _first_existing_column(segments, ["lon_center", "lon_mean", "longitude"])

    rows: list[dict[str, Any]] = []
    for _, row in segments.iterrows():
        lat = _coerce_float(row.get(lat_col)) if lat_col else None
        lon = _coerce_float(row.get(lon_col)) if lon_col else None
        if lat is None or lon is None:
            geometry = _row_geometry(row)
            if geometry is not None and not geometry.is_empty:
                point = geometry.centroid
                lat = float(point.y)
                lon = float(point.x)
        if lat is None or lon is None:
            continue
        rows.append({"segment_id": str(row["segment_id"]), "lat": lat, "lon": lon})

    return pd.DataFrame(rows, columns=["segment_id", "lat", "lon"])


def _historical_volume_by_segment(
    segments: pd.DataFrame,
    historical_volume: pd.DataFrame | pd.Series | Mapping[str, float] | None,
    volume_column: str | None,
) -> pd.DataFrame:
    if historical_volume is None:
        source = segments
    elif isinstance(historical_volume, pd.Series):
        if historical_volume.index.name == "segment_id" or not isinstance(
            historical_volume.index, pd.RangeIndex
        ):
            return (
                historical_volume.rename("historical_volume")
                .reset_index()
                .rename(columns={historical_volume.index.name or "index": "segment_id"})
                .assign(segment_id=lambda frame: frame["segment_id"].astype(str))
            )
        if len(historical_volume) != len(segments):
            raise ValueError("historical_volume Series must be indexed by segment_id or match segments length")
        source = segments[["segment_id"]].copy()
        source["historical_volume"] = historical_volume.to_numpy(dtype=float)
        volume_column = "historical_volume"
    elif isinstance(historical_volume, Mapping):
        return pd.DataFrame(
            {
                "segment_id": [str(key) for key in historical_volume.keys()],
                "historical_volume": [float(value) for value in historical_volume.values()],
            }
        )
    else:
        source = historical_volume

    if "segment_id" not in source.columns:
        raise ValueError("historical_volume DataFrame must contain 'segment_id'")

    column = volume_column or _first_existing_column(source, _VOLUME_COLUMNS)
    if column is None:
        raise ValueError(
            "No historical volume column found. Provide volume_column or one of: "
            + ", ".join(_VOLUME_COLUMNS)
        )

    volume = source[["segment_id", column]].copy()
    volume[column] = pd.to_numeric(volume[column], errors="coerce").fillna(0.0)
    volume["segment_id"] = volume["segment_id"].astype(str)
    return (
        volume.groupby("segment_id", as_index=False, observed=True)[column]
        .sum()
        .rename(columns={column: "historical_volume"})
    )


def _overflow_risk_index(
    historical_volume: np.ndarray,
    distance_m: np.ndarray,
    capacity: np.ndarray,
    default_capacity: float,
    distance_pressure_m: float,
    volume_scale: float | None,
) -> np.ndarray:
    volume = np.clip(np.nan_to_num(historical_volume, nan=0.0), 0.0, None)
    positive = volume[volume > 0]
    if volume_scale is None:
        scale = float(np.percentile(positive, 95)) if len(positive) else 1.0
    else:
        scale = float(volume_scale)
    scale = max(scale, 1.0)

    distance = np.nan_to_num(distance_m, nan=distance_pressure_m * 2.0, posinf=distance_pressure_m * 2.0)
    distance_pressure = np.clip(distance / max(float(distance_pressure_m), 1.0), 0.0, 3.0)
    capacity = np.clip(np.nan_to_num(capacity, nan=0.0), 0.0, None)
    capacity_factor = np.sqrt(np.maximum(capacity, 1.0) / max(float(default_capacity), 1.0))
    capacity_factor = np.maximum(capacity_factor, 0.35)

    raw = (volume / scale) * (1.0 + distance_pressure) / capacity_factor
    return np.clip(100.0 * (1.0 - np.exp(-raw)), 0.0, 100.0)


def _row_tags(row: pd.Series) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    tags_json = row.get("tags_json")
    if isinstance(tags_json, str) and tags_json.strip():
        try:
            loaded = json.loads(tags_json)
            if isinstance(loaded, Mapping):
                tags.update({str(key): value for key, value in loaded.items()})
        except json.JSONDecodeError:
            pass
    for key in _CAPACITY_TAGS + ("amenity", "parking", "name"):
        if key in row and pd.notna(row[key]):
            tags[key] = row[key]
    return tags


def _first_present_tag(tags: Mapping[str, Any], keys: Iterable[str]) -> Any | None:
    for key in keys:
        value = tags.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _parse_capacity(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        capacity = float(value)
        return capacity if capacity > 0 else None

    text = str(value).strip().lower()
    if not text or text in {"yes", "no", "unknown", "many", "limited", "customers"}:
        return None

    numbers = [float(match) for match in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    if "-" in text and len(numbers) >= 2:
        return max(numbers[:2])
    return numbers[0]


def _row_geometry(row: pd.Series) -> BaseGeometry | None:
    geometry = row.get("geometry")
    if isinstance(geometry, BaseGeometry):
        return geometry

    geometry_wkt = row.get("geometry_wkt")
    if isinstance(geometry_wkt, str) and geometry_wkt.strip():
        try:
            return wkt.loads(geometry_wkt)
        except Exception:
            return None
    return None


def _area_m2_epsg32643(geometry: BaseGeometry | None) -> float | None:
    if geometry is None or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    projected = _project_geometry_to_epsg32643(geometry)
    area = float(projected.area)
    return area if math.isfinite(area) and area > 0 else None


def _project_geometry_to_epsg32643(geometry: BaseGeometry) -> BaseGeometry:
    try:
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
        return transform(transformer.transform, geometry)
    except ModuleNotFoundError:
        return transform(lambda x, y, z=None: _project_transform_result(x, y, z), geometry)


def _project_transform_result(x: Any, y: Any, z: Any = None) -> tuple[Any, Any] | tuple[Any, Any, Any]:
    projected_x, projected_y = _project_lonlat_to_epsg32643(x, y)
    if z is None:
        return projected_x, projected_y
    return projected_x, projected_y, z


def _project_lonlat_to_epsg32643(lon: Any, lat: Any) -> tuple[np.ndarray, np.ndarray]:
    """Project WGS84 lon/lat to EPSG:32643 meters.

    Uses pyproj when available. The fallback implements the standard WGS84 UTM
    Zone 43N equations so this module remains importable in lightweight setups.
    """

    try:
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
        x, y = transformer.transform(lon, lat)
        return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    except ModuleNotFoundError:
        return _project_lonlat_to_utm43n(lon, lat)


def _project_lonlat_to_utm43n(lon: Any, lat: Any) -> tuple[np.ndarray, np.ndarray]:
    lon_arr = np.asarray(lon, dtype=float)
    lat_arr = np.asarray(lat, dtype=float)
    lon_rad = np.radians(lon_arr)
    lat_rad = np.radians(lat_arr)
    lon0 = math.radians(EPSG32643_CENTRAL_MERIDIAN_DEG)

    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    e4 = e2 * e2
    e6 = e4 * e2
    ep2 = e2 / (1 - e2)

    sin_lat = np.sin(lat_rad)
    cos_lat = np.cos(lat_rad)
    tan_lat = np.tan(lat_rad)

    n = a / np.sqrt(1 - e2 * sin_lat * sin_lat)
    t = tan_lat * tan_lat
    c = ep2 * cos_lat * cos_lat
    aa = cos_lat * (lon_rad - lon0)

    m = a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat_rad
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * lat_rad)
        + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * lat_rad)
        - (35 * e6 / 3072) * np.sin(6 * lat_rad)
    )

    x = k0 * n * (
        aa
        + (1 - t + c) * aa**3 / 6
        + (5 - 18 * t + t**2 + 72 * c - 58 * ep2) * aa**5 / 120
    ) + 500000.0
    y = k0 * (
        m
        + n
        * tan_lat
        * (
            aa**2 / 2
            + (5 - t + 9 * c + 4 * c**2) * aa**4 / 24
            + (61 - 58 * t + t**2 + 600 * c - 330 * ep2) * aa**6 / 720
        )
    )
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _first_existing_column(frame: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if pd.isna(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
        return None
    return value
