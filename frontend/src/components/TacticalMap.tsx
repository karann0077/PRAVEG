"use client";

import React, { useEffect, useState, useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, ScatterplotLayer, ArcLayer } from "@deck.gl/layers";
import { useMapStore } from "@/store/useMapStore";
import Map from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";

// Map style URLs
const MAP_STYLES = {
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
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

// Google Maps-style traffic coloring: matte semantic colors
function getTrafficColor(eps: number): [number, number, number, number] {
  if (eps >= 90) return [131, 24, 67, 255];     // Deep Burgundy
  if (eps >= 70) return [239, 68, 68, 255];     // Standard Red
  if (eps >= 50) return [234, 179, 8, 255];     // Mustard Yellow
  if (eps >= 30) return [250, 204, 21, 255];    // Light Yellow
  return [16, 185, 129, 255];                   // Matte Emerald Green
}

function getGlowColor(eps: number): [number, number, number, number] {
  if (eps >= 90) return [131, 24, 67, 90];
  if (eps >= 70) return [239, 68, 68, 70];
  if (eps >= 50) return [234, 179, 8, 60];
  if (eps >= 30) return [250, 204, 21, 40];
  return [0, 0, 0, 0]; // No glow for green roads
}

function getLineWidth(eps: number): number {
  if (eps >= 90) return 6;
  if (eps >= 70) return 5;
  if (eps >= 50) return 4;
  if (eps >= 30) return 4;
  return 3;
}

export default function TacticalMap() {
  const { viewState, setViewState, selectedEdge, setSelectedEdge, mapStyle, targetHour, isSimulatingResolution } = useMapStore();
  const [geoData, setGeoData] = useState<any>(null);
  const [poiData, setPoiData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

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

    return [
      // Outer glow halo — wide, transparent, for bloom effect
      new GeoJsonLayer({
      id: "traffic-glow",
      data: geoData,
      pickable: false,
      stroked: true,
      filled: false,
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 0,
      getLineWidth: (d: any) => {
        const eps = d.properties?.eps ?? 0;
        return eps >= 30 ? getLineWidth(eps) * 3 : 0;
      },
      getLineColor: (d: any) => {
        const color = getGlowColor(d.properties?.eps ?? 0);
        if (selectedEdge) {
          if (selectedEdge.segment_id === d.properties.segment_id) {
            return isSimulatingResolution ? [16, 185, 129, 90] : color;
          }
          if (d.properties.is_ripple && d.properties.source_bottleneck === selectedEdge.segment_id) {
             return isSimulatingResolution ? [16, 185, 129, 90] : [239, 68, 68, 90]; // Green vs Red Glow
          }
          return [color[0], color[1], color[2], 0]; // Hide glow if another edge is selected
        } else {
          if (d.properties.is_ripple) return [0,0,0,0];
        }
        return color;
      },
      lineCapRounded: true,
      lineJointRounded: true,
      updateTriggers: { getLineWidth: geoData, getLineColor: geoData },
    }),
    // Core traffic line — crisp, opaque, follows road geometry exactly
    new GeoJsonLayer({
      id: "traffic-core",
      data: geoData,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 120],
      stroked: true,
      filled: false,
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 2,
      getLineWidth: (d: any) => getLineWidth(d.properties?.eps ?? 0),
      getLineColor: (d: any) => {
        const color = getTrafficColor(d.properties?.eps ?? 0);
        if (selectedEdge) {
          if (selectedEdge.segment_id === d.properties.segment_id) {
            return isSimulatingResolution ? [16, 185, 129, 255] : color;
          }
          if (d.properties.is_ripple && d.properties.source_bottleneck === selectedEdge.segment_id) {
             return isSimulatingResolution ? [16, 185, 129, 255] : [239, 68, 68, 255]; // Green vs Red Line
          }
          return [color[0], color[1], color[2], 25]; // Fade to 10% opacity if another edge is selected
        } else {
          if (d.properties.is_ripple) return [0,0,0,0];
        }
        return color;
      },
      lineCapRounded: true,
      lineJointRounded: true,
      onClick: (info: any) => {
        setSelectedEdge(info.object ? { ...info.object.properties, geometry: info.object.geometry } : null);
      },
      updateTriggers: { getLineWidth: geoData, getLineColor: [geoData, selectedEdge, isSimulatingResolution] },
    }),
    new ArcLayer({
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
    ];
  }, [geoData, poiData, selectedEdge, setSelectedEdge]);

  return (
    <div className="absolute inset-0 w-full h-full">
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }: any) => setViewState(vs)}
        controller={{
          dragPan: true,
          dragRotate: true,       // right-click drag = pitch+bearing
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
