"use client";

import React, { useEffect, useState, useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, ArcLayer, PathLayer } from "@deck.gl/layers";
import { HeatmapLayer, HexagonLayer } from "@deck.gl/aggregation-layers";
import * as turf from '@turf/turf';
import { useMapStore } from "@/store/useMapStore";
import Map from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";

// Map style URLs
const MAP_STYLES = {
  light: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json", // Google Maps style equivalent
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  satellite: {
    version: 8 as const,
    sources: {
      satellite: {
        type: "raster" as const,
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        attribution: "© ESRI World Imagery",
        maxzoom: 19,
      },
      "satellite-labels": {
        type: "raster" as const,
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
      },
    },
    layers: [
      { id: "satellite-bg", type: "raster" as const, source: "satellite" },
      { id: "satellite-labels", type: "raster" as const, source: "satellite-labels" },
    ],
  },
};

export default function TacticalMap() {
  const { viewState, setViewState, selectedEdge, setSelectedEdge, mapStyle, targetHour, isSimulatingResolution, geoData, setGeoData, activeLayerMode, setSelectedHeatmapZone } = useMapStore();
  const [poiData, setPoiData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [dashOffset, setDashOffset] = useState(0);

  // Animate the TSP Patrol Route dashes
  useEffect(() => {
    let animationId: number;
    const animate = () => {
      setDashOffset(prev => (prev - 0.05) % 100);
      animationId = requestAnimationFrame(animate);
    };
    animate();
    return () => cancelAnimationFrame(animationId);
  }, []);

  useEffect(() => {
    fetch("/data/pois.geojson").then(r => r.json()).then(setPoiData).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    const hourParam = targetHour || "live";

    fetch(`/api/predictions?hour=${hourParam}`)
      .then((r) => r.json())
      .then((data) => { setGeoData(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [targetHour]);

  const currentStyle = mapStyle === "satellite" ? MAP_STYLES.satellite : mapStyle === "light" ? MAP_STYLES.light : MAP_STYLES.dark;

  const isTactical = activeLayerMode === "tactical";
  const isHeatmap = activeLayerMode === "heatmap";

  // --- TURF.JS GEOMETRY CHUNKING (HEATMAP INTERPOLATION) ---
  const heatmapPoints = useMemo(() => {
    if (!isHeatmap || !geoData || !geoData.features) return [];
    const points: any[] = [];
    geoData.features.forEach((f: any) => {
      const eps = f.properties?.eps ?? 0;
      if (eps < 50) return; // Only map warning/critical roads for the blast radius
      
      const econLoss = f.properties?.economic_loss || (eps * 15000); // Derive economic bleed if missing
      const estVehicles = f.properties?.count_car || Math.floor(eps / 2);
      
      try {
        // Some GeoJSON might have multi geometries, try standard lineString first
        const line = turf.lineString(f.geometry.coordinates);
        // Split into dense 10-meter chunks to perfectly trace the road topology
        const chunks = turf.lineChunk(line, 0.01, { units: 'kilometers' });
        chunks.features.forEach((chunk: any) => {
           const coord = chunk.geometry.coordinates[0];
           points.push({
             position: coord,
             eps: eps,
             economic_loss: econLoss,
             vehicles: estVehicles,
             segment_id: f.properties?.segment_id
           });
        });
      } catch (err) {
        // Safe fallback for irregular MultiLineStrings
        let coord = f.geometry.coordinates[0];
        while (Array.isArray(coord) && Array.isArray(coord[0])) coord = coord[0];
        if (Array.isArray(coord)) {
           points.push({
             position: coord,
             eps: eps,
             economic_loss: econLoss,
             vehicles: estVehicles,
             segment_id: f.properties?.segment_id
           });
        }
      }
    });
    return points;
  }, [geoData, isHeatmap]);

  const layers = useMemo(() => {
    let dispatchRouteData = [];
    if (isSimulatingResolution && selectedEdge && selectedEdge.geometry) {
      const coords = selectedEdge.geometry.coordinates;
      let targetCoord = coords[0];
      if (Array.isArray(targetCoord) && Array.isArray(targetCoord[0])) {
        targetCoord = targetCoord[0]; // Handle MultiLineString
      }
      if (targetCoord) {
        dispatchRouteData.push({
          source: [77.585, 12.975], // Mock Cubbon Park Traffic Police Station
          target: targetCoord
        });
      }
    }

    // Build mock TSP Route out of top 5 hotspots
    let tspPath: any[] = [];
    if (geoData && geoData.features) {
      const hotspots = geoData.features
        .filter((f: any) => f.properties.eps > 80)
        .slice(0, 5)
        .map((f: any) => f.geometry.coordinates[0]);
      if (hotspots.length > 0) {
        tspPath.push({
          path: [[77.585, 12.975], ...hotspots.map((c: any) => Array.isArray(c[0]) ? c[0] : c)], // Mock Police Station + Hotspots
          color: [255, 255, 255, 255]
        });
      }
    }

    return [
      // Heatmap Mode (Economic Bleed Weighting)
      isHeatmap && new HeatmapLayer({
        id: 'heatmap-layer',
        data: heatmapPoints,
        getPosition: (d: any) => d.position,
        getWeight: (d: any) => d.economic_loss,
        radiusPixels: 50,
        intensity: 1,
        threshold: 0.1,
        colorRange: [
          [15, 23, 42, 0],       // slate-900 (transparent)
          [34, 211, 238, 150],   // Cyan
          [14, 165, 233, 200],   // Sky Blue
          [236, 72, 153, 255],   // Pink
          [225, 29, 72, 255]     // Neon Red
        ]
      }),

      // The Invisible Mesh Hack (Clickable Heatmap Zone Commander)
      isHeatmap && new HexagonLayer({
        id: 'heatmap-picker-layer',
        data: heatmapPoints,
        getPosition: (d: any) => d.position,
        radius: 200, // Hex bin size acting as the interactive bounding volume
        opacity: 0, // INVISIBLE but INTERACTIVE
        pickable: true,
        onClick: (info: any) => {
           if (info.object && info.object.points) {
              const pts = info.object.points;
              // Aggregate financial and squad data for the entire Zone
              const totalLoss = pts.reduce((sum: number, p: any) => sum + p.source.economic_loss, 0);
              const totalVeh = pts.reduce((sum: number, p: any) => sum + p.source.vehicles, 0);
              const uniqueSegments = new Set(pts.map((p: any) => p.source.segment_id)).size;
              
              // Calculate a Staging Area safely offset from the epicenter
              const hexCenter = info.coordinate;
              const stagingArea = [hexCenter[0] + 0.005, hexCenter[1] + 0.005];

              setSelectedHeatmapZone({
                totalSegments: uniqueSegments,
                totalVehicles: totalVeh,
                totalEconomicLoss: totalLoss,
                stagingArea: stagingArea
              });
           } else {
              setSelectedHeatmapZone(null);
           }
        }
      }),

      // Original Tactical Traffic Lines via DeckGL
      isTactical && new GeoJsonLayer({
        id: "traffic-core",
        data: geoData,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 120],
        stroked: true,
        filled: false,
        lineWidthUnits: "pixels",
        lineWidthMinPixels: 2,
        getLineWidth: 4,
        getLineColor: (d: any) => {
          const eps = d.properties?.eps ?? 0;
          if (selectedEdge) {
            if (selectedEdge.segment_id === d.properties.segment_id) {
              return isSimulatingResolution ? [50, 255, 50, 255] : [255, 255, 255, 255];
            }
            if (d.properties.is_ripple && d.properties.source_bottleneck === selectedEdge.segment_id) {
               return isSimulatingResolution ? [50, 255, 50, 255] : [255, 50, 50, 255];
            }
            return [100, 100, 100, 50]; // Fade
          }
          if (d.properties?.is_ripple) return [0,0,0,0];
          
          if (eps >= 80) return [255, 50, 50, 255]; // Red
          if (eps >= 50) return [255, 200, 50, 255]; // Yellow
          return [50, 255, 50, 255]; // Green
        },
        lineCapRounded: true,
        lineJointRounded: true,
        onClick: (info: any) => {
          setSelectedEdge(info.object ? { ...info.object.properties, geometry: info.object.geometry } : null);
        },
        updateTriggers: { getLineColor: [geoData, selectedEdge, isSimulatingResolution] },
      }),
    
    // TSP Patrol Route
    isTactical && new PathLayer({
      id: 'tsp-patrol-route',
      data: tspPath,
      getPath: (d: any) => d.path,
      getColor: (d: any) => d.color,
      getWidth: 4,
      widthUnits: "pixels",
      dashJustified: true,
      dashGapPickable: true,
      getDashArray: [4, 4],
      dashOffset: dashOffset,
      extensions: [new (require('@deck.gl/extensions').PathStyleExtension)({ dash: true })],
      updateTriggers: { dashOffset: dashOffset }
    }),

    isTactical && new ArcLayer({
      id: "dispatch-arc",
      data: dispatchRouteData,
      getSourcePosition: (d: any) => d.source,
      getTargetPosition: (d: any) => d.target,
      getSourceColor: [59, 130, 246, 255], // Police Blue
      getTargetColor: [16, 185, 129, 255], // Emerald Green
      getWidth: 6,
      tilt: 45,
      getHeight: 0.5,
      visible: isSimulatingResolution,
    }),
    ].filter(Boolean);
  }, [geoData, poiData, selectedEdge, setSelectedEdge, activeLayerMode, dashOffset, isSimulatingResolution, heatmapPoints, isTactical, isHeatmap]);

  return (
    <div className="absolute inset-0 w-full h-full">
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }: any) => setViewState(vs)}
        controller={{
          dragPan: true,
          dragRotate: true,
          scrollZoom: true,
          doubleClickZoom: true,
          touchZoom: true,
          touchRotate: true,
          keyboard: true,
        }}
        layers={layers}
        getCursor={({ isDragging, isHovering }: any) =>
          isDragging ? "grabbing" : isHovering ? "pointer" : "grab"
        }
        style={{ position: "absolute", inset: 0 }}
      >
        <Map
          mapStyle={currentStyle as any}
          reuseMaps
          attributionControl={false}
        />
      </DeckGL>

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/80 z-50">
          <div className="flex flex-col items-center gap-4">
            <div className="w-10 h-10 border-4 border-rose-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-slate-300 font-mono text-xs tracking-widest uppercase">
              Loading Spatial Intelligence...
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
