"""Spatial intersection engine for ripple (traffic spillover) generation.

FIX LOG (2026-06-18):
  BUG-5  FIXED: generate_ripples() used segment_id string parsing (osm_U_V)
         to find upstream segments.  Actual segment IDs are osm_way_XXXXX
         (OSM way numbers, not node pairs), so the upstream_map was always
         empty and ripple files were always 0 features.

         New approach: spatial Shapely buffer + intersection on geometry_wkt
         which is now available in the predictions DataFrame (fixed
         scoring.py writes geometry_wkt into GeoJSON properties).

  FIX-NEW: Ripple decay is now distance-based (not a flat 0.8 multiplier).
           A segment 5 m away gets eps * 0.95; one 30 m away gets eps * 0.75.
           This creates a realistic spatial gradient on the map.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
from shapely import wkt
from shapely.geometry import LineString


# Buffer radius for ripple propagation (meters → approximate degrees)
RIPPLE_RADIUS_M: float = 40.0
_M_TO_DEG: float = 1.0 / 111_000.0


def _load_geometry(wkt_str: str):
    """Safely load a Shapely geometry from WKT string.  Returns None on failure."""
    if not wkt_str or not isinstance(wkt_str, str):
        return None
    try:
        return wkt.loads(wkt_str)
    except Exception:
        return None


def _geojson_coords(shapely_geom) -> list | None:
    """Convert a Shapely LineString to GeoJSON coordinate list."""
    if shapely_geom is None:
        return None
    if shapely_geom.geom_type == "LineString":
        return [[float(x), float(y)] for x, y in shapely_geom.coords]
    if shapely_geom.geom_type == "MultiLineString":
        # Flatten to first sub-line for DeckGL compatibility
        return [[float(x), float(y)] for x, y in list(shapely_geom.geoms[0].coords)]
    return None


def _haversine_centroid_m(geom_a, geom_b) -> float:
    """Approximate distance in metres between two geometry centroids."""
    try:
        ca = geom_a.centroid
        cb = geom_b.centroid
        lat1, lon1 = math.radians(ca.y), math.radians(ca.x)
        lat2, lon2 = math.radians(cb.y), math.radians(cb.x)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * 6_371_008.8 * math.asin(math.sqrt(a))
    except Exception:
        return RIPPLE_RADIUS_M


def _distance_decay(dist_m: float) -> float:
    """FIX-NEW: distance-based EPS decay instead of flat 0.8 multiplier.

    Returns a multiplier in [0.65, 0.97] based on proximity:
      - 0 m  → 0.97  (nearly touching)
      - 15 m → 0.87
      - 30 m → 0.77
      - 40 m → 0.70
    """
    return max(0.65, 0.97 - (dist_m / RIPPLE_RADIUS_M) * 0.32)


def get_intersecting_segments(
    target_wkt: str,
    predictions_df: pd.DataFrame,
    distance_m: float = RIPPLE_RADIUS_M,
) -> list[tuple[str, float]]:
    """Find segments within distance_m of the target segment geometry.

    Returns a list of (segment_id, distance_m) tuples.
    Uses Shapely buffer + intersection — no segment_id string parsing.
    """
    target_geom = _load_geometry(target_wkt)
    if target_geom is None:
        return []

    buffer_deg = distance_m * _M_TO_DEG
    buffered = target_geom.buffer(buffer_deg)

    results = []
    for _, row in predictions_df.iterrows():
        geom = _load_geometry(str(row.get("geometry_wkt", "")))
        if geom is None:
            continue
        if buffered.intersects(geom):
            dist_m = _haversine_centroid_m(target_geom, geom)
            results.append((str(row["segment_id"]), dist_m))

    return results


def generate_ripples(predictions_df: pd.DataFrame, road_graph=None) -> list:
    """Generate ripple GeoJSON features for all segments with eps >= 70.

    FIX BUG-5: Uses geometry_wkt spatial intersection instead of segment_id
    string parsing.  geometry_wkt is now present in predictions_df because
    scoring.write_geojson() was fixed to include it in properties.
    """
    ripples = []
    bottlenecks = predictions_df[predictions_df["eps"] >= 70]

    if bottlenecks.empty:
        return ripples

    # Prepare geometries for STRtree
    geoms = []
    row_data = []
    
    for _, row in predictions_df.iterrows():
        geom = _load_geometry(str(row.get("geometry_wkt", "")))
        if geom is not None:
            geoms.append(geom)
            row_data.append(row)

    if not geoms:
        return ripples

    from shapely.strtree import STRtree
    tree = STRtree(geoms)

    for _, row in bottlenecks.iterrows():
        segment_id = str(row["segment_id"])
        eps = float(row["eps"])
        target_geom = _load_geometry(str(row.get("geometry_wkt", "")))

        if target_geom is None:
            continue  # Cannot do spatial ripple without geometry

        buffer_deg = RIPPLE_RADIUS_M * _M_TO_DEG
        buffered = target_geom.buffer(buffer_deg)

        # Query the tree for intersecting geometries
        intersecting_idx = tree.query(buffered, predicate="intersects")

        for idx in intersecting_idx:
            nbr_geom = geoms[idx]
            nbr_row = row_data[idx]
            nbr_id = str(nbr_row["segment_id"])

            if nbr_id == segment_id:
                continue

            dist_m = _haversine_centroid_m(target_geom, nbr_geom)
            coords = _geojson_coords(nbr_geom)
            if coords is None:
                continue

            # FIX-NEW: distance-based decay
            decay = _distance_decay(dist_m)
            eps_spillover = round(eps * decay, 2)

            ripples.append({
                "type": "Feature",
                "properties": {
                    "source_bottleneck": segment_id,
                    "segment_id": nbr_id,
                    "eps_spillover": eps_spillover,
                    "eps": eps_spillover,          # alias for DeckGL colour accessor
                    "is_ripple": True,
                    "distance_from_bottleneck_m": round(dist_m, 1),
                    "decay_factor": round(decay, 3),
                    "road_class": str(nbr_row.get("road_class", "unknown")),
                    "police_station": str(nbr_row.get("police_station", "Unknown")),
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            })

    return ripples


def write_ripples_geojson(ripples: list, out_path: Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"type": "FeatureCollection", "features": ripples}
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
