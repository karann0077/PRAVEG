"use client";

import React, { useEffect, useState, useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer } from "@deck.gl/layers";
import { useMapStore } from "@/store/useMapStore";
import Map from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";

// Map style URLs
const MAP_STYLES = {
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

// Google Maps-style traffic coloring: green=free, yellow=slow, red=congested
function getTrafficColor(eps: number): [number, number, number, number] {
  if (eps >= 90) return [220, 30, 30, 255];    // Google red
  if (eps >= 70) return [255, 80, 0, 255];      // Dark orange
  if (eps >= 50) return [255, 165, 0, 255];     // Orange
  if (eps >= 30) return [255, 220, 0, 255];     // Yellow
  if (eps >= 10) return [100, 200, 50, 255];    // Light green
  return [40, 167, 69, 255];                    // Green (clear)
}

function getGlowColor(eps: number): [number, number, number, number] {
  if (eps >= 90) return [220, 30, 30, 90];
  if (eps >= 70) return [255, 80, 0, 70];
  if (eps >= 50) return [255, 165, 0, 60];
  if (eps >= 30) return [255, 220, 0, 40];
  return [0, 0, 0, 0]; // No glow for green roads
}

function getLineWidth(eps: number): number {
  if (eps >= 90) return 6;
  if (eps >= 70) return 5;
  if (eps >= 50) return 4;
  if (eps >= 30) return 4;
  if (eps >= 10) return 3;
  return 3;
}

export default function TacticalMap() {
  const { viewState, setViewState, setSelectedEdge, mapStyle } = useMapStore();
  const [geoData, setGeoData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/predictions")
      .then((r) => r.json())
      .then((data) => { setGeoData(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const currentStyle = mapStyle === "satellite" ? MAP_STYLES.satellite : MAP_STYLES.dark;

  const layers = useMemo(() => [
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
      getLineColor: (d: any) => getGlowColor(d.properties?.eps ?? 0),
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
      getLineColor: (d: any) => getTrafficColor(d.properties?.eps ?? 0),
      lineCapRounded: true,
      lineJointRounded: true,
      onClick: (info: any) => {
        setSelectedEdge(info.object ? info.object.properties : null);
      },
      updateTriggers: { getLineWidth: geoData, getLineColor: geoData },
    }),
  ], [geoData, setSelectedEdge]);

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
