"""Optional OSMnx road-graph map matching.

The production architecture prefers exact road edges. This module enables that
when OSMnx and its geospatial dependencies are installed. The default training
path falls back to grid segments so the engine remains runnable with only the
provided CSV.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def match_events_to_osmnx_edges(
    events: pd.DataFrame,
    place: str = "Bengaluru, Karnataka, India",
    graphml_path: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Snap event coordinates to OSMnx drive-network edges.

    Returns a copy of the events with ``segment_id`` set to edge IDs and an edge
    metadata table. Importing OSMnx is deliberately inside the function so the
    rest of the engine works without the optional geospatial stack.
    """

    try:
        import osmnx as ox
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OSMnx is not installed. Install optional geospatial dependencies "
            "or use the default grid fallback."
        ) from exc

    if graphml_path and Path(graphml_path).exists():
        graph = ox.load_graphml(graphml_path)
    else:
        graph = ox.graph_from_place(place, network_type="drive", simplify=True)
        if graphml_path:
            Path(graphml_path).parent.mkdir(parents=True, exist_ok=True)
            ox.save_graphml(graph, graphml_path)

    matched = events.copy()
    nearest = ox.distance.nearest_edges(
        graph,
        X=matched["longitude"].astype(float).to_numpy(),
        Y=matched["latitude"].astype(float).to_numpy(),
    )
    matched["osm_u"] = [edge[0] for edge in nearest]
    matched["osm_v"] = [edge[1] for edge in nearest]
    matched["osm_key"] = [edge[2] for edge in nearest]
    matched["segment_id"] = (
        "osm_"
        + matched["osm_u"].astype(str)
        + "_"
        + matched["osm_v"].astype(str)
        + "_"
        + matched["osm_key"].astype(str)
    )
    matched["map_matching_mode"] = "osmnx_nearest_edge"

    edge_rows = []
    for u, v, key, data in graph.edges(keys=True, data=True):
        edge_id = f"osm_{u}_{v}_{key}"
        highway = data.get("highway", "unknown")
        if isinstance(highway, list):
            highway = highway[0] if highway else "unknown"
        geometry = data.get("geometry")
        edge_rows.append(
            {
                "segment_id": edge_id,
                "osm_u": u,
                "osm_v": v,
                "osm_key": key,
                "osm_highway": str(highway),
                "osm_length_m": float(data.get("length", 0.0) or 0.0),
                "geometry_wkt": geometry.wkt if geometry is not None else None,
            }
        )
    return matched, pd.DataFrame(edge_rows)
