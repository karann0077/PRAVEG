"use client";

import React, { useEffect, useState, useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, ArcLayer, PathLayer, TextLayer } from "@deck.gl/layers";
import { HeatmapLayer, HexagonLayer } from "@deck.gl/aggregation-layers";
import * as turf from '@turf/turf';
import { useMapStore } from "@/store/useMapStore";
import { motion } from "framer-motion";
import Map, { Marker } from "react-map-gl/maplibre";
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
  const { viewState, setViewState, selectedEdge, setSelectedEdge, mapStyle, targetHour, isSimulatingResolution, geoData, setGeoData, activeLayerMode, showRipples, setSelectedHeatmapZone, heatmapWeightMode, isBuildingRoute, nearestStation, patrolRouteGeometry } = useMapStore();
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

    const fetchData = () => {
      fetch(`/api/predictions?hour=${hourParam}&t=${Date.now()}`)
        .then((r) => r.json())
        .then((data) => { setGeoData(data); setLoading(false); })
        .catch(() => setLoading(false));
    };

    fetchData();

    if (hourParam === "live") {
      const interval = setInterval(fetchData, 60000);
      return () => clearInterval(interval);
    }
  }, [targetHour, setGeoData]);

  const currentStyle = mapStyle === "satellite" ? MAP_STYLES.satellite : mapStyle === "light" ? MAP_STYLES.light : MAP_STYLES.dark;
  const isActionRoads = activeLayerMode === "action_roads";
  const isTrafficBlockage = activeLayerMode === "traffic_blockage";
  const isPatrolRoute = activeLayerMode === "patrol_route";
  const isAllPredictions = activeLayerMode === "all_predictions";

  // --- TURF.JS GEOMETRY CHUNKING (HEATMAP INTERPOLATION) ---
  const heatmapPoints = useMemo(() => {
    if (!isTrafficBlockage || !geoData || !geoData.mapFeatures) return [];
    const points: any[] = [];
    geoData.mapFeatures.forEach((f: any) => {
      const eps = f.properties?.eps ?? 0;
      const econLoss = f.properties?.economic_loss || (eps * 15000); // Derive economic bleed if missing
      const estVehicles = f.properties?.predicted_total || Math.floor(eps / 2);
      const weight = heatmapWeightMode === 'violation_density' ? estVehicles : econLoss;
      
      try {
        let coord = f.geometry.coordinates[0];
        while (Array.isArray(coord) && Array.isArray(coord[0])) coord = coord[0];
        if (Array.isArray(coord)) {
           points.push({
             position: coord,
             eps: eps,
             economic_loss: econLoss,
             vehicles: estVehicles,
             weight: weight,
             segment_id: f.properties?.segment_id
           });
        }
      }
    });
    return points;
  }, [geoData, isTrafficBlockage, heatmapWeightMode]);

  const layers = useMemo(() => {
    let dispatchRouteData = [];
    if (isSimulatingResolution && selectedEdge && selectedEdge.geometry) {
      const coords = selectedEdge.geometry.coordinates;
      let targetCoord = coords[0];
      if (Array.isArray(targetCoord) && Array.isArray(targetCoord[0])) {
        targetCoord = targetCoord[0];
      }
      if (targetCoord) {
        dispatchRouteData.push({
          source: [77.585, 12.975],
          target: targetCoord
        });
      }
    }

    let tspPath: any[] = [];
    if (isBuildingRoute && patrolRouteGeometry) {
      tspPath.push({
        path: patrolRouteGeometry,
        color: [59, 130, 246, 255] // Vibrant Blue
      });
    }

    return [
      isTrafficBlockage && new HeatmapLayer({
        id: 'heatmap-layer',
        data: heatmapPoints,
        getPosition: (d: any) => d.position,
        getWeight: (d: any) => d.weight,
        radiusPixels: 20,
        intensity: 2,
        threshold: 0.05,
        colorRange: [
          [34, 197, 94, 50],
          [6, 182, 212, 100],
          [168, 85, 247, 150],
          [236, 72, 153, 200],
          [239, 68, 68, 255]
        ]
      }),

      isTrafficBlockage && new HexagonLayer({
        id: 'heatmap-picker-layer',
        data: heatmapPoints,
        getPosition: (d: any) => d.position,
        radius: 200,
        opacity: 0,
        pickable: true,
        onClick: (info: any) => {
           if (info.object && info.object.points) {
              const pts = info.object.points;
              const totalLoss = pts.reduce((sum: number, p: any) => sum + p.source.economic_loss, 0);
              const totalVeh = pts.reduce((sum: number, p: any) => sum + p.source.vehicles, 0);
              const uniqueSegments = new Set(pts.map((p: any) => p.source.segment_id)).size;
              
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
           return true;
        }
      }),

      !isTrafficBlockage && new GeoJsonLayer({
        id: "traffic-glow",
        data: geoData?.mapFeatures || [],
        pickable: false,
        stroked: true,
        filled: false,
        lineWidthUnits: "pixels",
        getLineWidth: (d: any) => {
          const eps = d.properties?.eps ?? 0;
          return 2 + (eps / 15) + 6; // Glow is wider
        },
        getLineColor: (d: any) => {
          const eps = d.properties?.eps ?? 0;
          
          if (selectedEdge) {
            if (selectedEdge.properties?.segment_id === d.properties.segment_id) {
              return isSimulatingResolution ? [16, 185, 129, 100] : [34, 211, 238, 100];
            }
            return [30, 30, 30, 0]; 
          }
          
          if (eps >= 75) return [225, 29, 72, 120]; // Deep Red
          if (eps >= 50) return [249, 115, 22, 100]; // Orange
          if (eps >= 25) return [234, 179, 8, 80]; // Yellow
          return [34, 197, 94, 60]; // Green glow
        },
        lineCapRounded: true,
        lineJointRounded: true,
        updateTriggers: { getLineColor: [geoData, selectedEdge, isSimulatingResolution, activeLayerMode], getLineWidth: [geoData] },
      }),

      !isTrafficBlockage && new GeoJsonLayer({
        id: "traffic-core",
        data: geoData?.mapFeatures || [],
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 200],
        stroked: true,
        filled: false,
        lineWidthUnits: "pixels",
        lineWidthMinPixels: 1,
        getLineWidth: (d: any) => {
          const eps = d.properties?.eps ?? 0;
          return 2 + (eps / 15);
        },
        getLineColor: (d: any) => {
          const eps = d.properties?.eps ?? 0;

          if (selectedEdge) {
            if (selectedEdge.properties?.segment_id === d.properties.segment_id) {
              return isSimulatingResolution ? [16, 185, 129, 255] : [255, 255, 255, 255];
            }
            return [100, 100, 100, 50];
          }
          
          if (eps >= 75) return [225, 29, 72, 255]; // Deep Red
          if (eps >= 50) return [249, 115, 22, 255]; // Orange
          if (eps >= 25) return [234, 179, 8, 255]; // Yellow
          return [34, 197, 94, 255]; // Green
        },
        lineCapRounded: true,
        lineJointRounded: true,
        onClick: (info: any) => {
          setSelectedEdge(info.object ? info.object : null);
          return true;
        },
        updateTriggers: { getLineColor: [geoData, selectedEdge, isSimulatingResolution, activeLayerMode], getLineWidth: [geoData] },
      }),

      showRipples && new GeoJsonLayer({
        id: "traffic-ripples",
        data: geoData?.rippleFeatures || [],
        pickable: false,
        stroked: true,
        filled: false,
        lineWidthUnits: "pixels",
        getLineWidth: 2,
        getLineColor: (d: any) => {
          if (selectedEdge && d.properties?.source_bottleneck === selectedEdge.properties?.segment_id) {
             return isSimulatingResolution ? [16, 185, 129, 150] : [255, 100, 140, 150];
          }
          return [255, 42, 95, 80]; // Faint red ripple
        },
        lineCapRounded: true,
        lineJointRounded: true,
        updateTriggers: { getLineColor: [geoData, selectedEdge, isSimulatingResolution] },
      }),
    
    // TSP Patrol Route - Outer Glow (wide, soft)
    (isPatrolRoute || isBuildingRoute) && new PathLayer({
      id: 'tsp-patrol-route-glow',
      data: tspPath,
      getPath: (d: any) => d.path,
      getColor: [99, 180, 255, 90], // Wide electric blue glow
      getWidth: 18,
      widthUnits: "pixels",
      widthMinPixels: 12,
      lineCapRounded: true,
      lineJointRounded: true,
    }),

    // TSP Patrol Route - Middle Bright
    (isPatrolRoute || isBuildingRoute) && new PathLayer({
      id: 'tsp-patrol-route-mid',
      data: tspPath,
      getPath: (d: any) => d.path,
      getColor: [147, 210, 255, 180], // Bright blue mid
      getWidth: 8,
      widthUnits: "pixels",
      widthMinPixels: 6,
      lineCapRounded: true,
      lineJointRounded: true,
    }),

    // TSP Patrol Route - Inner Core with animated dash
    (isPatrolRoute || isBuildingRoute) && new PathLayer({
      id: 'tsp-patrol-route-core',
      data: tspPath,
      getPath: (d: any) => d.path,
      getColor: [255, 255, 255, 255], // White core
      getWidth: 3,
      widthUnits: "pixels",
      widthMinPixels: 2,
      lineCapRounded: true,
      lineJointRounded: true,
      dashJustified: true,
      dashGapPickable: true,
      getDashArray: [12, 6],
      dashOffset: dashOffset,
      extensions: [new (require('@deck.gl/extensions').PathStyleExtension)({ dash: true })],
      updateTriggers: { dashOffset: dashOffset }
    }),



    !isTrafficBlockage && new ArcLayer({
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
  }, [geoData, poiData, selectedEdge, setSelectedEdge, activeLayerMode, dashOffset, isSimulatingResolution, heatmapPoints, isActionRoads, isTrafficBlockage, isPatrolRoute, isAllPredictions, isBuildingRoute, nearestStation, patrolRouteGeometry]);

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 1.2, ease: "easeOut" }}
      className="absolute inset-0 w-full h-full"
    >
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
        style={{ position: "absolute", inset: "0" }}
      >
        <Map
          mapStyle={currentStyle as any}
          reuseMaps
          attributionControl={false}
        >
          {isBuildingRoute && patrolRouteGeometry && patrolRouteGeometry.length > 0 && (
            <>
              {/* SOURCE MARKER (Police Station) */}
              <Marker longitude={patrolRouteGeometry[0][0]} latitude={patrolRouteGeometry[0][1]} anchor="bottom">
                <div className="flex flex-col items-center">
                  <div className="relative flex items-center justify-center w-8 h-8 bg-rose-500 rounded-full shadow-[0_0_15px_rgba(244,63,94,0.6)] border-[3px] border-white">
                    <div className="w-2.5 h-2.5 bg-white rounded-full" />
                  </div>
                  <div className="w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[8px] border-t-rose-500 -mt-0.5" />
                  {nearestStation?.station_name && (
                    <div className="absolute top-10 whitespace-nowrap px-2.5 py-1 bg-[#0B0F1A]/90 backdrop-blur-md text-white text-[10px] font-bold tracking-widest uppercase rounded border border-white/10 shadow-xl">
                      {nearestStation.station_name} PS
                    </div>
                  )}
                </div>
              </Marker>
              
              {/* DESTINATION MARKER (Target Zone) */}
              <Marker longitude={patrolRouteGeometry[patrolRouteGeometry.length - 1][0]} latitude={patrolRouteGeometry[patrolRouteGeometry.length - 1][1]} anchor="bottom">
                <div className="flex flex-col items-center">
                  <div className="relative flex items-center justify-center w-8 h-8 bg-blue-500 rounded-full shadow-[0_0_15px_rgba(59,130,246,0.6)] border-[3px] border-white">
                    <div className="w-2.5 h-2.5 bg-white rounded-full" />
                  </div>
                  <div className="w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[8px] border-t-blue-500 -mt-0.5" />
                  <div className="absolute top-10 whitespace-nowrap px-2.5 py-1 bg-[#0B0F1A]/90 backdrop-blur-md text-white text-[10px] font-bold tracking-widest uppercase rounded border border-white/10 shadow-xl">
                    TARGET ZONE
                  </div>
                </div>
              </Marker>
            </>
          )}
        </Map>
      </DeckGL>

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#0B0F1A]/80 backdrop-blur-sm z-50">
          <div className="flex flex-col items-center gap-4">
            <div className="w-10 h-10 border-4 border-[#3b82f6] border-t-transparent rounded-full animate-spin" />
            <span className="text-zinc-400 font-mono text-xs tracking-widest uppercase">
              Loading Spatial Intelligence...
            </span>
          </div>
        </div>
      )}
    </motion.div>
  );
}
