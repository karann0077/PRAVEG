"""OpenStreetMap road fetching and nearest-road matching.

This is a no-key fallback for the PDF's road-network phase. It fetches public
OSM road ways from Overpass, then snaps each violation point to the nearest
road LineString so exported hotspots can render as lines on roads.
"""

from __future__ import annotations

import json
import numbers
from pathlib import Path

import pandas as pd
import requests
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from shapely import wkt

from .config import ROAD_WIDTH_BY_CLASS_M


EXCLUDED_HIGHWAYS = {
    "footway",
    "path",
    "pedestrian",
    "steps",
    "cycleway",
    "bridleway",
    "construction",
    "proposed",
    "raceway",
}


def fetch_osm_roads_for_events(
    events: pd.DataFrame,
    cache_path: str | Path = "artifacts/osm/bengaluru_roads.json",
    margin_deg: float = 0.01,
) -> pd.DataFrame:
    """Fetch or load OSM road ways covering the event bounding box."""

    cache = Path(cache_path)
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        south = float(events["latitude"].min()) - margin_deg
        north = float(events["latitude"].max()) + margin_deg
        west = float(events["longitude"].min()) - margin_deg
        east = float(events["longitude"].max()) + margin_deg
        query = (
            f'[out:json][timeout:120];'
            f'way["highway"]({south},{west},{north},{east});'
            f"out body;>;out skel qt;"
        )
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": "parking-enforcement-engine/0.1"},
            timeout=240,
        )
        response.raise_for_status()
        payload = response.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload), encoding="utf-8")

    nodes = {
        element["id"]: (float(element["lon"]), float(element["lat"]))
        for element in payload.get("elements", [])
        if element.get("type") == "node" and "lat" in element and "lon" in element
    }
    rows = []
    for element in payload.get("elements", []):
        if element.get("type") != "way":
            continue
        tags = element.get("tags", {})
        highway = tags.get("highway")
        if isinstance(highway, list):
            highway = highway[0] if highway else None
        if not highway or highway in EXCLUDED_HIGHWAYS:
            continue
        coords = [nodes[node_id] for node_id in element.get("nodes", []) if node_id in nodes]
        if len(coords) < 2:
            continue
        geometry = LineString(coords)
        road_class = road_class_from_highway(str(highway))
        rows.append(
            {
                "segment_id": f"osm_way_{element['id']}",
                "osm_way_id": int(element["id"]),
                "osm_highway": str(highway),
                "road_class": road_class,
                "road_width_m": ROAD_WIDTH_BY_CLASS_M.get(road_class, 6.0),
                "road_name": tags.get("name", ""),
                "geometry_wkt": geometry.wkt,
            }
        )
    if not rows:
        raise RuntimeError("No OSM road ways were returned for the dataset bounding box.")
    return pd.DataFrame(rows).drop_duplicates("segment_id").reset_index(drop=True)


def match_events_to_osm_roads(events: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    """Snap events to nearest fetched OSM road LineString."""

    matched = events.copy()
    geometries = [wkt.loads(value) for value in roads["geometry_wkt"].astype(str)]
    tree = STRtree(geometries)
    road_records = roads.reset_index(drop=True).to_dict("records")

    segment_ids: list[str] = []
    road_classes: list[str] = []
    road_widths: list[float] = []
    road_names: list[str] = []
    osm_highways: list[str] = []
    nearest_distances: list[float] = []

    for lon, lat in zip(matched["longitude"], matched["latitude"], strict=False):
        point = Point(float(lon), float(lat))
        
        # ── V3: Topology-aware snapping ──────────────────────────────────────────
        # Query all roads within ~200m (0.002 degrees)
        buffer_deg = 0.002
        candidate_indices = tree.query(point.buffer(buffer_deg))
        
        if len(candidate_indices) == 0:
            # Fallback to nearest if none within buffer
            idx = tree.nearest(point)
            if isinstance(idx, numbers.Integral):
                idx = int(idx)
            else:
                idx = geometries.index(idx)
            best_idx = idx
            best_dist = float(point.distance(geometries[best_idx]))
        else:
            best_score = float('inf')
            best_idx = candidate_indices[0]
            best_dist = float('inf')
            
            for idx in candidate_indices:
                geom = geometries[idx]
                record = road_records[idx]
                dist = point.distance(geom)
                
                # Penalize snapping to major highways/trunks unless very close
                # A 0.0005 deg penalty is roughly ~50 meters.
                penalty = 0.0
                hw = str(record.get("osm_highway", ""))
                if hw in ["motorway", "motorway_link", "trunk", "trunk_link"]:
                    penalty = 0.0005
                elif hw in ["primary", "primary_link"]:
                    penalty = 0.0002
                
                score = dist + penalty
                if score < best_score:
                    best_score = score
                    best_idx = idx
                    best_dist = float(dist)

        record = road_records[best_idx]
        segment_ids.append(record["segment_id"])
        road_classes.append(record["road_class"])
        road_widths.append(float(record["road_width_m"]))
        road_names.append(str(record.get("road_name", "")))
        osm_highways.append(str(record.get("osm_highway", "")))
        nearest_distances.append(best_dist)

    matched["segment_id"] = segment_ids
    matched["road_class"] = road_classes
    matched["road_width_m"] = road_widths
    matched["road_name"] = road_names
    matched["osm_highway"] = osm_highways
    matched["nearest_road_distance_deg"] = nearest_distances
    matched["map_matching_mode"] = "osm_overpass_nearest_road"
    return matched


def road_class_from_highway(highway: str) -> str:
    """Map OSM highway tags to the width classes used by scoring."""

    highway = highway.lower()
    if highway in {"motorway", "motorway_link"}:
        return "motorway"
    if highway in {"trunk", "trunk_link"}:
        return "trunk"
    if highway in {"primary", "primary_link"}:
        return "primary"
    if highway in {"secondary", "tertiary", "secondary_link", "tertiary_link", "unclassified"}:
        return "secondary"
    return "residential"
