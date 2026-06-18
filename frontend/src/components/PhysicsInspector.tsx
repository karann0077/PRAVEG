"use client";

import React, { useMemo, useState } from "react";
import { useMapStore } from "@/store/useMapStore";
import { motion, AnimatePresence } from "framer-motion";
import { X, Activity, Truck, AlertTriangle, ShieldAlert, Crosshair } from "lucide-react";

const VEHICLE_WIDTHS: Record<string, number> = {
  heavy: 2.6,
  light_commercial: 2.3,
  car: 1.9,
  auto: 1.3,
  two_wheeler: 0.8,
  other: 1.9,
};

export default function PhysicsInspector() {
  const { selectedEdge, setSelectedEdge, isSimulatingResolution, setIsSimulatingResolution, geoData } = useMapStore();
  const [shapData, setShapData] = useState<any>(null);

  React.useEffect(() => {
    if (selectedEdge) {
      setShapData(null);
      fetch(`/api/explain?segment_id=${selectedEdge.segment_id}`)
        .then(r => r.json())
        .then(d => {
          if (d.data) setShapData(d.data);
        })
        .catch(console.error);
    }
  }, [selectedEdge]);

  const mapFeatureToLabel = (f: string, impact: number) => {
    if (f === "event_impact_score") return `🔴 High Event Proximity (+${(Math.abs(impact) * 100).toFixed(0)}% Risk)`;
    if (f === "overflow_risk_index") return `🔴 Commercial Hub Overflow (+${(Math.abs(impact) * 100).toFixed(0)}% Risk)`;
    if (f === "rain_shelter_bottleneck") return `🔴 Rain Shelter Bottleneck (+${(Math.abs(impact) * 100).toFixed(0)}% Risk)`;
    if (f === "dist_to_commercial_m") return `🔴 Near Commercial Zone (+${(Math.abs(impact) * 100).toFixed(0)}% Risk)`;
    if (f === "dist_to_metro_m") return `🔴 Near Transit Hub (+${(Math.abs(impact) * 100).toFixed(0)}% Risk)`;
    if (f === "is_raining") return impact < 0 ? `🟢 Clear Weather (-${(Math.abs(impact) * 100).toFixed(0)}% Risk)` : `🔴 Rain Hazard (+${(Math.abs(impact) * 100).toFixed(0)}% Risk)`;
    return impact > 0 ? `🔴 ${f} (+${(Math.abs(impact) * 100).toFixed(0)}% Risk)` : `🟢 ${f} (-${(Math.abs(impact) * 100).toFixed(0)}% Risk)`;
  };

  const analysis = useMemo(() => {
    if (!selectedEdge) return null;
    const eps: number = selectedEdge.eps ?? 0;
    const roadWidth: number = selectedEdge.road_width_m ?? 6.0;
    
    let dominantVehicle = "car";
    let maxCount = 0;
    for (const [vClass] of Object.entries(VEHICLE_WIDTHS)) {
      const colKey = `count_${vClass}`;
      const val = parseFloat(selectedEdge[colKey] ?? 0);
      if (val > maxCount) {
        maxCount = val;
        dominantVehicle = vClass;
      }
    }
    const vehicleWidth = VEHICLE_WIDTHS[dominantVehicle] ?? 1.9;
    const totalBlockWidth = vehicleWidth;
    const chokePercent = (totalBlockWidth / roadWidth) * 100;

    // Traffic Speed Impact Mathematical Formula
    // Speed Reduction % = min(95%, (Choke% * 1.2) + (EPS * 0.3))
    const rawSpeedReduction = (chokePercent * 1.2) + (eps * 0.3);
    const speedReductionPercent = Math.min(95, rawSpeedReduction);

    return { 
      eps, 
      roadWidth, 
      totalBlockWidth, 
      chokePercent, 
      speedReductionPercent, 
      dominantVehicle: selectedEdge.count_heavy > 0 ? "heavy" : selectedEdge.count_car > 0 ? "car" : "scooter",
      clearance: Math.max(0, roadWidth - totalBlockWidth)
    };
  }, [selectedEdge]);

  const handleDispatch = () => {
    setIsSimulatingResolution(true);
    
    // SMART ROUTING FEATURE: Collect red lines to avoid
    let avoidPolygons: any[] = [];
    if (geoData && geoData.features) {
      avoidPolygons = geoData.features
        .filter((f: any) => f.properties.eps > 70)
        .map((f: any) => f.geometry);
    }
    
    console.log("SMART ROUTING REQUEST: Dispatching tow truck...");
    console.log(`Passing ${avoidPolygons.length} 'Red Lines' (EPS > 70) to Routing API as 'avoid_polygons'`);
    console.log(JSON.stringify({
      start: [77.585, 12.975], // Police Station
      end: selectedEdge.geometry?.coordinates[0],
      avoid_polygons: avoidPolygons
    }));

    // Simulate resolution time
    setTimeout(() => {
      setIsSimulatingResolution(false);
      setSelectedEdge(null);
    }, 4000);
  };

  return (
    <AnimatePresence>
      {selectedEdge && analysis && (
        <motion.div
          key="bottleneck-inspector"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[480px] rounded-2xl border border-white/20 shadow-2xl overflow-hidden"
          style={{
            background: "rgba(255,255,255,0.95)",
            backdropFilter: "blur(12px)",
            boxShadow: analysis.eps >= 90 ? "0 30px 60px rgba(131,24,67,0.4)" : "0 30px 60px rgba(0,0,0,0.3)"
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50/80">
            <h3 className="text-slate-800 text-sm font-bold flex items-center gap-2 uppercase tracking-wider">
              <Crosshair className="w-4 h-4 text-rose-600" />
              Tactical Inspector
            </h3>
            <button
              onClick={() => setSelectedEdge(null)}
              className="p-1.5 rounded-full hover:bg-slate-200 text-slate-500 hover:text-slate-800 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-6">
            {/* Top Metrics */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <p className="text-slate-500 text-[10px] font-mono uppercase tracking-widest mb-1">
                  Enforcement Target
                </p>
                <p className="text-slate-900 text-lg font-bold capitalize flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-rose-500" />
                  {analysis.dominantVehicle.replace("_", " ")}
                </p>
              </div>

              {/* EPS Circular Gauge */}
              <div className="relative w-16 h-16 flex items-center justify-center">
                <svg className="absolute inset-0 w-full h-full -rotate-90">
                  <circle cx="32" cy="32" r="28" fill="none" stroke="#e2e8f0" strokeWidth="6" />
                  <circle
                    cx="32"
                    cy="32"
                    r="28"
                    fill="none"
                    stroke={analysis.eps >= 90 ? "#831843" : analysis.eps >= 70 ? "#ef4444" : "#eab308"}
                    strokeWidth="6"
                    strokeDasharray={`${(analysis.eps / 100) * 175} 175`}
                    strokeLinecap="round"
                    className="transition-all duration-1000"
                  />
                </svg>
                <div className="flex flex-col items-center">
                  <span className="text-slate-900 font-bold font-mono text-lg leading-none">{Math.round(analysis.eps)}</span>
                  <span className="text-slate-500 text-[8px] font-mono uppercase">EPS</span>
                </div>
              </div>
            </div>

            {/* Isometric 3D Visualization */}
            <div className="relative h-48 bg-slate-100 rounded-xl overflow-hidden mb-6 flex items-center justify-center border border-slate-200 perspective-1000 shadow-inner">
              <div
                className="relative w-[200px] h-[300px] preserve-3d"
                style={{ transform: "rotateX(60deg) rotateZ(-45deg)" }}
              >
                {/* Road Base */}
                <div className="absolute inset-0 bg-slate-300 border-2 border-slate-400 rounded-sm shadow-md" />
                
                {/* Center Line */}
                <div className="absolute inset-y-0 left-1/2 w-1 -translate-x-1/2 bg-[repeating-linear-gradient(0deg,transparent,transparent_10px,rgba(255,255,255,0.8)_10px,rgba(255,255,255,0.8)_20px)]" />

                {/* The Obstruction (Illegally Parked Vehicle) */}
                <motion.div
                  initial={{ z: 50, opacity: 0 }}
                  animate={{ z: 0, opacity: 1 }}
                  className="absolute bottom-1/2 left-2 bg-rose-600 rounded shadow-2xl flex items-center justify-center"
                  style={{
                    width: `${analysis.chokePercent}%`, // Dynamic width relative to road
                    height: '40px',
                    transform: "translateZ(10px)",
                    boxShadow: "-10px 10px 20px rgba(0,0,0,0.5)"
                  }}
                >
                  <div className="text-white text-[10px] font-bold rotate-90">{analysis.dominantVehicle.replace("_", " ")}</div>
                </motion.div>

                {/* Simulated Queue of Cars trapped behind */}
                <div className="absolute bottom-4 left-2 w-[40%] flex flex-col gap-2">
                  {[...Array(4)].map((_, i) => (
                    <motion.div
                      key={i}
                      initial={{ y: 50, opacity: 0 }}
                      animate={{ y: 0, opacity: 1 }}
                      transition={{ delay: i * 0.2, repeat: Infinity, duration: 2 }}
                      className="w-full h-8 bg-slate-500 rounded-sm shadow-lg"
                      style={{ transform: "translateZ(5px)" }}
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* Action Metrics */}
            <div className="flex items-center justify-between mb-4 text-sm">
              <div className="text-slate-600">
                <span className="font-mono bg-slate-200 px-1.5 py-0.5 rounded mr-1">W</span> {analysis.roadWidth}m Road
              </div>
              <div className="text-slate-600">
                <span className="font-mono bg-rose-100 text-rose-700 px-1.5 py-0.5 rounded mr-1">C</span> {analysis.chokePercent.toFixed(0)}% Choke
              </div>
              <div className="text-slate-600">
                <span className="font-mono bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded mr-1">R</span> {analysis.clearance.toFixed(1)}m Left
              </div>
            </div>

            {/* Explainable AI (SHAP) Metrics */}
            <div className="mb-4">
              <p className="text-[10px] text-slate-500 font-mono uppercase tracking-widest mb-2">
                AI Inference Drivers (SHAP)
              </p>
              <div className="bg-slate-100 rounded-lg p-3 space-y-2 border border-slate-200">
                {shapData ? (
                  <>
                    {shapData.top_positive_contributors?.map((c: any, i: number) => (
                      <div key={i} className="text-xs font-mono text-slate-700">
                        {mapFeatureToLabel(c.feature, c.impact)}
                      </div>
                    ))}
                    {shapData.top_negative_contributors?.map((c: any, i: number) => (
                      <div key={i} className="text-xs font-mono text-slate-700">
                        {mapFeatureToLabel(c.feature, c.impact)}
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="text-xs text-slate-400 font-mono animate-pulse">Calculating SHAP values from LRU Cache...</div>
                )}
              </div>
            </div>

            {/* Speed Reduction Metric */}
            <div className="mb-6 p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 backdrop-blur-md relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-r from-rose-600/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <p className="text-[10px] text-rose-600 font-mono uppercase tracking-widest mb-1 relative z-10">
                Traffic Speed Impact
              </p>
              <div className="flex items-end gap-2 relative z-10">
                <span className="text-3xl font-black text-rose-700 font-mono leading-none tracking-tighter">
                  -{analysis.speedReductionPercent.toFixed(1)}%
                </span>
              </div>
              <div className="mt-2 text-[9px] text-slate-500 font-mono leading-tight relative z-10 border-t border-rose-500/20 pt-2">
                <span className="text-slate-700 font-bold">Mathematical Model:</span> <br/>
                <code className="text-rose-600/90 font-bold">Speed_Reduction = min(95%, (Choke% × 1.2) + (EPS × 0.3))</code>
              </div>
            </div>

            {/* Dispatch Button */}
            <button
              onClick={handleDispatch}
              disabled={isSimulatingResolution}
              className={`w-full py-4 rounded-xl flex items-center justify-center gap-2 font-bold uppercase tracking-widest text-sm transition-all ${
                isSimulatingResolution 
                  ? "bg-emerald-600 text-white shadow-[0_0_20px_rgba(16,185,129,0.5)] cursor-not-allowed" 
                  : "bg-rose-600 hover:bg-rose-700 text-white shadow-xl hover:shadow-rose-500/30"
              }`}
            >
              {isSimulatingResolution ? (
                <>
                  <ShieldAlert className="w-5 h-5" />
                  Tow Unit En Route... Resolving Queue
                </>
              ) : (
                <>
                  <ShieldAlert className="w-5 h-5" />
                  Dispatch {analysis.dominantVehicle === "heavy" ? "Heavy-Duty" : ""} Tow Unit
                </>
              )}
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
