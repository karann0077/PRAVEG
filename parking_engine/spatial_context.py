"""Spatial context features for Bengaluru parking segments.

This module is intentionally standalone so V2 feature integration can import it
without changing the current training pipeline. It fetches/cache OSM points and
polygons for station and commercial context, projects coordinates to EPSG:32643,
and computes nearest-neighbor distances in meters.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


LOGGER = logging.getLogger(__name__)

DEFAULT_POI_CACHE_PATH = Path("artifacts/osm/bengaluru_spatial_context_pois.geojson")
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_PLACE_QUERY = "Bengaluru, Karnataka, India"

# Approximate Bengaluru urban bounding box: south, west, north, east.
DEFAULT_BENGALURU_BBOX = (12.73, 77.35, 13.20, 77.85)

POI_COLUMNS = [
    "poi_id",
    "poi_type",
    "name",
    "lat",
    "lon",
    "osm_type",
    "osm_id",
    "source",
    "tags",
]

SPATIAL_CONTEXT_COLUMNS = [
    "segment_id", 
    "dist_to_metro_m", 
    "dist_to_commercial_m",
    "dist_to_bus_stop_m",
    "dist_to_school_m",
    "dist_to_hospital_m",
    "dist_to_market_m",
    "dist_to_restaurant_m",
    "dist_to_worship_m",
    "dist_to_office_m",
    "dist_to_mall_m",
    "dist_to_airport_m",
    "dist_to_railway_station_m",
    "dist_to_hotel_m",
    "dist_to_nightlife_m",
    "dist_to_park_m",
    "dist_to_stadium_m",
    "dist_to_university_m",
    "poi_count_200m",
    "poi_count_500m",
    "poi_gravity_score",
]

# V3: POI gravity weights - higher weight = more parking impact
POI_GRAVITY_WEIGHTS = {
    "metro": 3.0,
    "railway_station": 3.0,
    "airport": 4.0,
    "commercial": 2.5,
    "mall": 3.5,
    "market": 2.5,
    "school": 2.0,
    "university": 2.5,
    "hospital": 2.0,
    "restaurant": 1.5,
    "bus_stop": 1.2,
    "worship": 1.5,
    "office": 2.5,
    "hotel": 2.0,
    "nightlife": 2.5,
    "park": 1.5,
    "stadium": 3.0,
}


def fetch_bengaluru_context_pois(
    cache_path: str | Path = DEFAULT_POI_CACHE_PATH,
    *,
    force_refresh: bool = False,
    allow_network: bool = True,
    prefer_osmnx: bool = True,
    place_query: str = DEFAULT_PLACE_QUERY,
    bbox: tuple[float, float, float, float] = DEFAULT_BENGALURU_BBOX,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    timeout_seconds: int = 180,
) -> pd.DataFrame:
    """Load cached Bengaluru context POIs or fetch them from OSM.

    Returned rows use ``poi_type == "metro"`` for OSM ``railway=station`` and
    ``poi_type == "commercial"`` for OSM ``landuse=commercial|retail``. If
    network access or optional geospatial dependencies are unavailable, the
    function falls back to any readable cache and otherwise returns an empty
    DataFrame with the expected columns.
    """

    cache = Path(cache_path)
    cached = load_cached_context_pois(cache)
    if not force_refresh and not cached.empty:
        cached.attrs["cache_path"] = str(cache)
        cached.attrs["source"] = "cache"
        return cached

    fetch_error: Exception | None = None
    if allow_network:
        fetchers = []
        if prefer_osmnx:
            fetchers.append(
                lambda: _fetch_context_pois_with_osmnx(place_query=place_query)
            )
        fetchers.append(
            lambda: _fetch_context_pois_with_overpass(
                bbox=bbox,
                overpass_url=overpass_url,
                timeout_seconds=timeout_seconds,
            )
        )

        for fetcher in fetchers:
            try:
                pois = normalize_poi_dataframe(fetcher())
            except Exception as exc:  # pragma: no cover - depends on network/providers.
                fetch_error = exc
                LOGGER.warning("Bengaluru POI fetch failed: %s", exc)
                continue
            if not pois.empty:
                write_context_poi_cache(pois, cache)
                pois.attrs["cache_path"] = str(cache)
                pois.attrs["source"] = "network"
                return pois

    if not cached.empty:
        cached.attrs["cache_path"] = str(cache)
        cached.attrs["source"] = "cache_fallback"
        if fetch_error is not None:
            cached.attrs["fetch_error"] = str(fetch_error)
        return cached

    empty = _empty_poi_frame()
    if fetch_error is not None:
        empty.attrs["fetch_error"] = str(fetch_error)
    elif not allow_network:
        empty.attrs["fetch_error"] = "network disabled and no readable cache found"
    return empty


def load_cached_context_pois(cache_path: str | Path = DEFAULT_POI_CACHE_PATH) -> pd.DataFrame:
    """Read cached context POIs from GeoJSON/JSON, returning an empty frame on failure."""

    cache = Path(cache_path)
    if not cache.exists():
        return _empty_poi_frame()

    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except Exception as exc:
        LOGGER.warning("Could not read POI cache %s: %s", cache, exc)
        return _empty_poi_frame()

    try:
        if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
            rows = [_poi_row_from_geojson_feature(feature) for feature in payload.get("features", [])]
            return normalize_poi_dataframe([row for row in rows if row])
        if isinstance(payload, dict) and isinstance(payload.get("pois"), list):
            return normalize_poi_dataframe(payload["pois"])
        if isinstance(payload, list):
            return normalize_poi_dataframe(payload)
    except Exception as exc:
        LOGGER.warning("Could not parse POI cache %s: %s", cache, exc)
    return _empty_poi_frame()


def write_context_poi_cache(
    pois: pd.DataFrame,
    cache_path: str | Path = DEFAULT_POI_CACHE_PATH,
) -> None:
    """Persist POIs as GeoJSON so the cache remains inspectable and portable."""

    frame = normalize_poi_dataframe(pois)
    cache = Path(cache_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    features = []
    for row in frame.to_dict("records"):
        properties = {
            key: _json_safe(value)
            for key, value in row.items()
            if key not in {"lat", "lon"} and not _is_missing(value)
        }
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row["lon"]), float(row["lat"])],
                },
            }
        )
    payload = {"type": "FeatureCollection", "features": features}
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_spatial_context_features(
    segment_metadata: pd.DataFrame,
    *,
    pois: pd.DataFrame | None = None,
    cache_path: str | Path = DEFAULT_POI_CACHE_PATH,
    force_refresh: bool = False,
    allow_network: bool = True,
    missing_distance_m: float = np.nan,
) -> pd.DataFrame:
    """Return segment-level proximity features keyed by ``segment_id``.

    ``segment_metadata`` must contain ``segment_id``, ``lat_center``, and
    ``lon_center``. Missing/invalid segment coordinates and unavailable POI
    types receive ``missing_distance_m``.
    """

    segments = _normalize_segment_metadata(segment_metadata)
    context_pois = (
        normalize_poi_dataframe(pois)
        if pois is not None
        else fetch_bengaluru_context_pois(
            cache_path=cache_path,
            force_refresh=force_refresh,
            allow_network=allow_network,
        )
    )

    result = segments[["segment_id"]].copy()
    poi_types = [
        "metro", "commercial", "bus_stop", "school", 
        "hospital", "market", "restaurant", "worship", "office",
        "mall", "airport", "railway_station", "hotel", "nightlife", "park", "stadium", "university"
    ]
    for ptype in poi_types:
        result[f"dist_to_{ptype}_m"] = nearest_poi_distances_m(
            segments,
            context_pois,
            poi_type=ptype,
            missing_distance_m=missing_distance_m,
        ).to_numpy()

    # V3: Density counts within 200m and 500m
    counts_200, counts_500, gravity_score = _compute_poi_density_and_gravity(segments, context_pois)
    result["poi_count_200m"] = counts_200
    result["poi_count_500m"] = counts_500
    result["poi_gravity_score"] = gravity_score

    return result[SPATIAL_CONTEXT_COLUMNS]


def nearest_poi_distances_m(
    segment_metadata: pd.DataFrame,
    pois: pd.DataFrame,
    *,
    poi_type: str,
    missing_distance_m: float = np.nan,
) -> pd.Series:
    """Compute distance from each segment center to the nearest POI of ``poi_type``."""

    segments = _normalize_segment_metadata(segment_metadata)
    context_pois = normalize_poi_dataframe(pois)
    distances = pd.Series(missing_distance_m, index=segments.index, dtype="float64")

    valid_segments = segments[["lat_center", "lon_center"]].notna().all(axis=1)
    targets = context_pois.loc[context_pois["poi_type"].eq(poi_type)].copy()
    targets = targets.dropna(subset=["lat", "lon"])
    if not valid_segments.any() or targets.empty:
        distances.index = segments["segment_id"]
        return distances

    segment_x, segment_y = project_lonlat_to_epsg32643(
        segments.loc[valid_segments, "lon_center"].to_numpy(dtype=float),
        segments.loc[valid_segments, "lat_center"].to_numpy(dtype=float),
    )
    poi_x, poi_y = project_lonlat_to_epsg32643(
        targets["lon"].to_numpy(dtype=float),
        targets["lat"].to_numpy(dtype=float),
    )
    query_points = np.column_stack([segment_x, segment_y])
    target_points = np.column_stack([poi_x, poi_y])
    distances.loc[valid_segments] = _nearest_distances_with_ckdtree(
        query_points,
        target_points,
    )
    distances.index = segments["segment_id"]
    return distances


def _compute_poi_density_and_gravity(segments: pd.DataFrame, context_pois: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """V3: Compute counts of POIs within radii and gravity score."""
    n_segments = len(segments)
    counts_200 = pd.Series(0.0, index=segments.index, dtype="float64")
    counts_500 = pd.Series(0.0, index=segments.index, dtype="float64")
    gravity_score = pd.Series(0.0, index=segments.index, dtype="float64")

    valid_segments = segments[["lat_center", "lon_center"]].notna().all(axis=1)
    if not valid_segments.any() or context_pois.empty:
        return counts_200, counts_500, gravity_score

    segment_x, segment_y = project_lonlat_to_epsg32643(
        segments.loc[valid_segments, "lon_center"].to_numpy(dtype=float),
        segments.loc[valid_segments, "lat_center"].to_numpy(dtype=float),
    )
    query_points = np.column_stack([segment_x, segment_y])

    # For counts, we consider all POIs
    valid_pois = context_pois.dropna(subset=["lat", "lon"])
    if valid_pois.empty:
        return counts_200, counts_500, gravity_score
        
    poi_x, poi_y = project_lonlat_to_epsg32643(
        valid_pois["lon"].to_numpy(dtype=float),
        valid_pois["lat"].to_numpy(dtype=float),
    )
    target_points = np.column_stack([poi_x, poi_y])

    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(target_points)
        # counts within 200m and 500m
        idx_200 = tree.query_ball_point(query_points, r=200.0)
        idx_500 = tree.query_ball_point(query_points, r=500.0)
        
        c200 = np.array([len(indices) for indices in idx_200], dtype="float64")
        c500 = np.array([len(indices) for indices in idx_500], dtype="float64")
        counts_200.loc[valid_segments] = c200
        counts_500.loc[valid_segments] = c500
        
        # Calculate gravity score: sum of weight / max(10, distance)^1.5
        # We'll just approximate it using the 500m neighbors for efficiency
        poi_types = valid_pois["poi_type"].to_numpy()
        gravity = np.zeros(len(query_points), dtype="float64")
        
        for i, indices in enumerate(idx_500):
            if not indices:
                continue
            targets = target_points[indices]
            ptypes = poi_types[indices]
            dist = np.sqrt(np.sum((targets - query_points[i])**2, axis=1))
            dist = np.maximum(dist, 10.0)  # avoid div by zero, assume min 10m
            weights = np.array([POI_GRAVITY_WEIGHTS.get(pt, 1.0) for pt in ptypes])
            gravity[i] = np.sum(weights / (dist ** 1.5)) * 1000  # scale factor
            
        gravity_score.loc[valid_segments] = gravity
        
    except Exception as e:
        LOGGER.warning("cKDTree unavailable or failed, skipping POI density features: %s", e)
        
    counts_200.index = segments["segment_id"]
    counts_500.index = segments["segment_id"]
    gravity_score.index = segments["segment_id"]
    return counts_200, counts_500, gravity_score


def project_lonlat_to_epsg32643(
    lon: float | Iterable[float] | np.ndarray | pd.Series,
    lat: float | Iterable[float] | np.ndarray | pd.Series,
) -> tuple[np.ndarray, np.ndarray]:
    """Project WGS84 longitude/latitude coordinates to EPSG:32643 meters.

    Uses ``pyproj`` when installed and falls back to an internal WGS84 UTM zone
    43N forward projection. The fallback keeps this module usable in lightweight
    environments while preserving meter-scale nearest-neighbor behavior around
    Bengaluru.
    """

    lon_arr = np.asarray(lon, dtype="float64")
    lat_arr = np.asarray(lat, dtype="float64")
    lon_arr, lat_arr = np.broadcast_arrays(lon_arr, lat_arr)

    try:
        from pyproj import Transformer  # type: ignore

        transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
        x, y = transformer.transform(lon_arr, lat_arr)
        return np.asarray(x, dtype="float64"), np.asarray(y, dtype="float64")
    except Exception:
        return _project_lonlat_to_utm43n(lon_arr, lat_arr)


def normalize_poi_dataframe(pois: pd.DataFrame | Iterable[dict[str, Any]] | None) -> pd.DataFrame:
    """Normalize external POI rows to the schema used by this module."""

    if pois is None:
        return _empty_poi_frame()
    frame = pois.copy() if isinstance(pois, pd.DataFrame) else pd.DataFrame(list(pois))
    if frame.empty:
        return _empty_poi_frame()

    rename_map = {
        "latitude": "lat",
        "longitude": "lon",
        "type": "poi_type",
        "id": "poi_id",
    }
    frame = frame.rename(columns={k: v for k, v in rename_map.items() if k in frame.columns})
    for col in POI_COLUMNS:
        if col not in frame.columns:
            frame[col] = {} if col == "tags" else ""

    frame["poi_type"] = frame["poi_type"].map(_normalize_poi_type)
    frame["lat"] = pd.to_numeric(frame["lat"], errors="coerce")
    frame["lon"] = pd.to_numeric(frame["lon"], errors="coerce")
    frame = frame.dropna(subset=["lat", "lon", "poi_type"])
    
    valid_types = [
        "metro", "commercial", "bus_stop", "school", 
        "hospital", "market", "restaurant", "worship", "office",
        "mall", "airport", "railway_station", "hotel", "nightlife", "park", "stadium", "university"
    ]
    frame = frame.loc[frame["poi_type"].isin(valid_types)].copy()
    if frame.empty:
        return _empty_poi_frame()

    frame["poi_id"] = frame.apply(_stable_poi_id, axis=1)
    frame["name"] = frame["name"].fillna("").astype(str)
    frame["osm_type"] = frame["osm_type"].fillna("").astype(str)
    frame["osm_id"] = frame["osm_id"].fillna("").astype(str)
    frame["source"] = frame["source"].fillna("").astype(str)
    frame["tags"] = frame["tags"].apply(lambda value: value if isinstance(value, dict) else {})
    frame = frame[POI_COLUMNS]
    frame = frame.drop_duplicates("poi_id").sort_values(["poi_type", "poi_id"])
    return frame.reset_index(drop=True)


def _fetch_context_pois_with_osmnx(place_query: str) -> pd.DataFrame:
    ox = _import_osmnx()
    tags = {"railway": "station", "landuse": ["commercial", "retail"]}
    if hasattr(ox, "features_from_place"):
        gdf = ox.features_from_place(place_query, tags=tags)
    elif hasattr(ox, "geometries_from_place"):
        gdf = ox.geometries_from_place(place_query, tags=tags)
    else:
        raise RuntimeError("Installed osmnx does not expose feature/geometries fetch APIs")
    return _pois_from_osmnx_geodataframe(gdf)


def _fetch_context_pois_with_overpass(
    *,
    bbox: tuple[float, float, float, float],
    overpass_url: str,
    timeout_seconds: int,
) -> pd.DataFrame:
    try:
        import requests
    except Exception as exc:
        raise RuntimeError("requests is required for Overpass POI fetches") from exc

    south, west, north, east = bbox
    selector = f"({south},{west},{north},{east})"
    query = f"""
    [out:json][timeout:{int(timeout_seconds)}];
    (
      node["railway"="station"]{selector};
      way["railway"="station"]{selector};
      relation["railway"="station"]{selector};
      node["landuse"~"^(commercial|retail)$"]{selector};
      way["landuse"~"^(commercial|retail)$"]{selector};
      relation["landuse"~"^(commercial|retail)$"]{selector};
      node["highway"="bus_stop"]{selector};
      node["amenity"~"^(school|college|university)$"]{selector};
      way["amenity"~"^(school|college|university)$"]{selector};
      node["amenity"~"^(hospital|clinic)$"]{selector};
      way["amenity"~"^(hospital|clinic)$"]{selector};
      node["amenity"~"^(marketplace|restaurant|cafe|fast_food|food_court)$"]{selector};
      way["amenity"~"^(marketplace|restaurant|cafe|fast_food|food_court)$"]{selector};
      node["amenity"="place_of_worship"]{selector};
      way["amenity"="place_of_worship"]{selector};
      node["office"]{selector};
      way["office"]{selector};
      relation["office"]{selector};
      node["shop"="mall"]{selector};
      way["shop"="mall"]{selector};
      relation["shop"="mall"]{selector};
      node["aeroway"="aerodrome"]{selector};
      way["aeroway"="aerodrome"]{selector};
      relation["aeroway"="aerodrome"]{selector};
      node["tourism"="hotel"]{selector};
      way["tourism"="hotel"]{selector};
      relation["tourism"="hotel"]{selector};
      node["amenity"~"^(nightclub|bar|pub)$"]{selector};
      way["amenity"~"^(nightclub|bar|pub)$"]{selector};
      relation["amenity"~"^(nightclub|bar|pub)$"]{selector};
      node["leisure"="park"]{selector};
      way["leisure"="park"]{selector};
      relation["leisure"="park"]{selector};
      node["leisure"="stadium"]{selector};
      way["leisure"="stadium"]{selector};
      relation["leisure"="stadium"]{selector};
    );
    out tags center;
    """
    response = requests.post(
        overpass_url,
        data={"data": query},
        headers={"User-Agent": "parking-enforcement-engine/0.1 spatial-context"},
        timeout=timeout_seconds + 30,
    )
    response.raise_for_status()
    payload = response.json()

    rows = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        poi_type = _poi_type_from_osm_tags(tags)
        if poi_type is None:
            continue
        lat, lon = _element_center(element)
        if lat is None or lon is None:
            continue
        osm_type = str(element.get("type", ""))
        osm_id = str(element.get("id", ""))
        rows.append(
            {
                "poi_id": f"osm:{osm_type}:{osm_id}",
                "poi_type": poi_type,
                "name": str(tags.get("name", "")),
                "lat": lat,
                "lon": lon,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "source": "overpass",
                "tags": tags,
            }
        )
    return normalize_poi_dataframe(rows)


def _pois_from_osmnx_geodataframe(gdf: Any) -> pd.DataFrame:
    if gdf is None or len(gdf) == 0:
        return _empty_poi_frame()

    frame = gdf.copy()
    if getattr(frame, "crs", None) is not None and str(frame.crs).upper() not in {
        "EPSG:4326",
        "WGS84",
    }:
        frame = frame.to_crs(epsg=4326)

    rows = []
    for raw_index, row in frame.iterrows():
        tags = {
            key: _json_safe(value)
            for key, value in row.items()
            if key != "geometry" and not _is_missing(value)
        }
        poi_type = _poi_type_from_osm_tags(tags)
        if poi_type is None:
            continue
        geometry = row.get("geometry")
        if geometry is None or getattr(geometry, "is_empty", True):
            continue
        point = geometry if geometry.geom_type == "Point" else geometry.centroid
        osm_type, osm_id = _osm_index_parts(raw_index)
        rows.append(
            {
                "poi_id": f"osm:{osm_type}:{osm_id}",
                "poi_type": poi_type,
                "name": str(tags.get("name", "")),
                "lat": float(point.y),
                "lon": float(point.x),
                "osm_type": osm_type,
                "osm_id": osm_id,
                "source": "osmnx",
                "tags": tags,
            }
        )
    return normalize_poi_dataframe(rows)


def _nearest_distances_with_ckdtree(
    query_points: np.ndarray,
    target_points: np.ndarray,
) -> np.ndarray:
    try:
        from scipy.spatial import cKDTree
    except Exception:
        LOGGER.warning("scipy.spatial.cKDTree unavailable; using slower NumPy distance fallback")
        return _nearest_distances_numpy(query_points, target_points)

    tree = cKDTree(target_points)
    distances, _ = tree.query(query_points, k=1)
    return np.asarray(distances, dtype="float64")


def _nearest_distances_numpy(query_points: np.ndarray, target_points: np.ndarray) -> np.ndarray:
    distances = np.empty(len(query_points), dtype="float64")
    chunk_size = 4096
    for start in range(0, len(query_points), chunk_size):
        chunk = query_points[start : start + chunk_size]
        delta = chunk[:, None, :] - target_points[None, :, :]
        distances[start : start + chunk_size] = np.sqrt(np.sum(delta * delta, axis=2)).min(axis=1)
    return distances


def _project_lonlat_to_utm43n(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized WGS84 UTM zone 43N forward projection."""

    a = 6378137.0
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)
    k0 = 0.9996
    false_easting = 500000.0
    lon0 = math.radians(75.0)

    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    sin_lat = np.sin(lat_rad)
    cos_lat = np.cos(lat_rad)
    tan_lat = np.tan(lat_rad)

    n = a / np.sqrt(1.0 - e2 * sin_lat * sin_lat)
    t = tan_lat * tan_lat
    c = ep2 * cos_lat * cos_lat
    aa = cos_lat * (lon_rad - lon0)

    e4 = e2 * e2
    e6 = e4 * e2
    meridional_arc = a * (
        (1.0 - e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0) * lat_rad
        - (3.0 * e2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0)
        * np.sin(2.0 * lat_rad)
        + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0) * np.sin(4.0 * lat_rad)
        - (35.0 * e6 / 3072.0) * np.sin(6.0 * lat_rad)
    )

    x = false_easting + k0 * n * (
        aa
        + (1.0 - t + c) * aa**3 / 6.0
        + (5.0 - 18.0 * t + t**2 + 72.0 * c - 58.0 * ep2) * aa**5 / 120.0
    )
    y = k0 * (
        meridional_arc
        + n
        * tan_lat
        * (
            aa**2 / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c**2) * aa**4 / 24.0
            + (61.0 - 58.0 * t + t**2 + 600.0 * c - 330.0 * ep2)
            * aa**6
            / 720.0
        )
    )
    return x.astype("float64"), y.astype("float64")


def _normalize_segment_metadata(segment_metadata: pd.DataFrame) -> pd.DataFrame:
    required = {"segment_id", "lat_center", "lon_center"}
    missing = sorted(required.difference(segment_metadata.columns))
    if missing:
        raise ValueError(f"segment_metadata is missing required columns: {missing}")

    frame = segment_metadata[["segment_id", "lat_center", "lon_center"]].copy()
    frame["segment_id"] = frame["segment_id"].astype(str)
    frame["lat_center"] = pd.to_numeric(frame["lat_center"], errors="coerce")
    frame["lon_center"] = pd.to_numeric(frame["lon_center"], errors="coerce")
    return frame.reset_index(drop=True)


def _empty_poi_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=POI_COLUMNS)


def _import_osmnx() -> Any:
    try:
        import osmnx as ox  # type: ignore
    except Exception as exc:
        raise RuntimeError("osmnx is not installed") from exc
    return ox


def _poi_row_from_geojson_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") != "Point" or len(coordinates) < 2:
        return None
    properties = dict(feature.get("properties") or {})
    properties["lon"] = coordinates[0]
    properties["lat"] = coordinates[1]
    return properties


def _poi_type_from_osm_tags(tags: dict[str, Any]) -> str | None:
    if str(tags.get("aeroway", "")).lower() == "aerodrome":
        return "airport"
    if str(tags.get("shop", "")).lower() == "mall":
        return "mall"
    if str(tags.get("tourism", "")).lower() == "hotel":
        return "hotel"
    if str(tags.get("leisure", "")).lower() == "park":
        return "park"
    if str(tags.get("leisure", "")).lower() == "stadium":
        return "stadium"
    if str(tags.get("railway", "")).lower() == "station":
        if str(tags.get("station", "")).lower() == "subway" or str(tags.get("subway", "")).lower() == "yes":
            return "metro"
        return "railway_station"
    if str(tags.get("landuse", "")).lower() in {"commercial", "retail"}:
        return "commercial"
    if str(tags.get("highway", "")).lower() == "bus_stop":
        return "bus_stop"
    amenity = str(tags.get("amenity", "")).lower()
    if amenity in {"nightclub", "bar", "pub"}:
        return "nightlife"
    if amenity in {"university", "college"}:
        return "university"
    if amenity in {"school"}:
        return "school"
    if amenity in {"hospital", "clinic"}:
        return "hospital"
    if amenity in {"restaurant", "cafe", "fast_food", "food_court"}:
        return "restaurant"
    if amenity == "marketplace":
        return "market"
    if amenity == "place_of_worship":
        return "worship"
    if "office" in tags:
        return "office"
    return None


def _normalize_poi_type(value: Any) -> str | None:
    text = str(value).strip().lower()
    if text in {"airport", "aeroway=aerodrome"}:
        return "airport"
    if text in {"mall", "shop=mall"}:
        return "mall"
    if text in {"hotel", "tourism=hotel"}:
        return "hotel"
    if text in {"park", "leisure=park"}:
        return "park"
    if text in {"stadium", "leisure=stadium"}:
        return "stadium"
    if text in {"nightlife", "nightclub", "bar", "pub"}:
        return "nightlife"
    if text in {"university", "college"}:
        return "university"
    if text in {"railway_station", "station"}:
        return "railway_station"
    if text in {"metro", "subway"}:
        return "metro"
    if text in {"commercial", "retail", "landuse_commercial", "landuse_retail"}:
        return "commercial"
    if text in {"bus_stop", "highway_bus_stop"}:
        return "bus_stop"
    if text in {"school"}:
        return "school"
    if text in {"hospital", "clinic"}:
        return "hospital"
    if text in {"restaurant", "cafe", "fast_food", "food_court"}:
        return "restaurant"
    if text in {"market", "marketplace"}:
        return "market"
    if text in {"worship", "place_of_worship"}:
        return "worship"
    if text in {"office"}:
        return "office"
    return None


def _element_center(element: dict[str, Any]) -> tuple[float | None, float | None]:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None, None


def _stable_poi_id(row: pd.Series) -> str:
    poi_id = str(row.get("poi_id", "")).strip()
    if poi_id:
        return poi_id
    osm_type = str(row.get("osm_type", "")).strip()
    osm_id = str(row.get("osm_id", "")).strip()
    if osm_type and osm_id:
        return f"osm:{osm_type}:{osm_id}"
    return (
        f"{row.get('poi_type')}:{float(row.get('lat')):.7f}:"
        f"{float(row.get('lon')):.7f}:{str(row.get('name', ''))[:60]}"
    )


def _osm_index_parts(index: Any) -> tuple[str, str]:
    if isinstance(index, tuple) and len(index) >= 2:
        return str(index[0]), str(index[1])
    return "feature", str(index)


def _json_safe(value: Any) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items() if not _is_missing(v)}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value if not _is_missing(v)]
    return str(value)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False
