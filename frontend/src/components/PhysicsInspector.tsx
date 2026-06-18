"use client";

import React, { useMemo, useState } from "react";
import { useMapStore } from "@/store/useMapStore";
import { motion, AnimatePresence } from "framer-motion";
import { X, Activity, Truck, AlertTriangle, ShieldAlert, Crosshair, Brain } from "lucide-react";

const VEHICLE_WIDTHS: Record<string, number> = {
  heavy: 2.6,
  light_commercial: 2.3,
  car: 1.9,
  auto: 1.3,
  two_wheeler: 0.8,
  other: 1.9,
};

export default function PhysicsInspector() {
  const { selectedEdge, setSelectedEdge, isSimulatingResolution, setIsSimulatingResolution, geoData, isSimulationActive, setIsSimulationActive } = useMapStore();
  const [shapData, setShapData] = useState<any>(null);

  React.useEffect(() => {
    if (selectedEdge) {
      setShapData(null);
      setIsSimulationActive(false); // Reset simulation state when switching edges
      fetch(`/api/explain?segment_id=${selectedEdge.segment_id}`)
        .then(r => r.json())
        .then(d => {
          if (d.data) setShapData(d.data);
        })
        .catch(console.error);
    }
  }, [selectedEdge, setIsSimulationActive]);

  const mapFeatureToLabel = (f: string, impact: number) => {
    const risk = (Math.abs(impact) * 100).toFixed(0);
    if (f === "event_impact_score") return `High Event Proximity (+${risk}% Risk)`;
    if (f === "overflow_risk_index") return `Commercial Hub Overflow (+${risk}% Risk)`;
    if (f === "rain_shelter_bottleneck") return `Rain Shelter Bottleneck (+${risk}% Risk)`;
    if (f === "dist_to_commercial_m") return `Near Commercial Zone (+${risk}% Risk)`;
    if (f === "dist_to_metro_m") return `Near Transit Hub (+${risk}% Risk)`;
    if (f === "is_raining") return impact < 0 ? `Clear Weather (-${risk}% Risk)` : `Rain Hazard (+${risk}% Risk)`;
    return impact > 0 ? `${f} (+${risk}% Risk)` : `${f} (-${risk}% Risk)`;
  };

  const getShapColor = (impact: number) => impact > 0 ? "bg-rose-500" : "bg-emerald-500";

  const analysis = useMemo(() => {
    if (!selectedEdge) return null;
    let eps: number = selectedEdge.eps ?? 0;
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
    
    const roadClassVolumes: Record<string, number> = {
      trunk: 5000,
      primary: 3000,
      secondary: 1500,
      tertiary: 500,
      residential: 200,
    };
    const rClass = selectedEdge.road_class?.toLowerCase() || 'tertiary';
    const estTrafficVolume = roadClassVolumes[rClass] || 500;

    // THE SIMULATION LOGIC
    let totalBlockWidth = vehicleWidth;
    let chokePercent = (totalBlockWidth / roadWidth) * 100;
    let speedReductionPercent = Math.min(95, (chokePercent * 1.2) + (eps * 0.3));
    // Factor in estimated traffic volume by road class for economic bleed.
    // Example: (speedReductionPercent / 100) * estTrafficVolume * 50 (₹50 cost per delayed vehicle)
    let economicBleed = (speedReductionPercent / 100) * estTrafficVolume * 50; 

    if (isSimulationActive) {
      totalBlockWidth = 0;
      chokePercent = 0;
      speedReductionPercent = 0;
      economicBleed = 0;
      eps = 0;
    }

    return { 
      eps, 
      roadWidth, 
      totalBlockWidth, 
      chokePercent, 
      speedReductionPercent,
      economicBleed,
      dominantVehicle,
      clearance: Math.max(0, roadWidth - totalBlockWidth)
    };
  }, [selectedEdge, isSimulationActive]);

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
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 20 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          className="absolute top-24 right-4 w-[400px] z-30 flex flex-col rounded-2xl border border-slate-700 shadow-2xl overflow-hidden bg-slate-800/80 backdrop-blur-md"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/80 bg-slate-900/50">
            <div>
              <h3 className="text-white text-xs font-bold flex items-center gap-2 uppercase tracking-widest mb-1">
                <Crosshair className="w-4 h-4 text-indigo-500" />
                {selectedEdge.road_name || selectedEdge.junction_name || "Unknown Link"}
              </h3>
              <p className="text-slate-400 text-[10px] font-mono">EPS {analysis.eps.toFixed(1)} ± 2.5</p>
            </div>
            <button
              onClick={() => setSelectedEdge(null)}
              className="p-1.5 rounded-full hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-5 overflow-y-auto custom-scrollbar max-h-[70vh]">
            {/* Economic Impact Card */}
            <div className="mb-5 p-4 rounded-xl border border-slate-700 bg-slate-900/40 relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-r from-rose-600/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="flex items-center justify-between mb-2 relative z-10">
                <p className="text-[10px] text-slate-400 font-mono uppercase tracking-widest">
                  Estimated Economic Loss
                </p>
                <button 
                  onClick={() => setIsSimulationActive(!isSimulationActive)}
                  className={`text-[9px] font-bold px-2 py-1 rounded-full uppercase tracking-wider transition-colors ${isSimulationActive ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}
                >
                  {isSimulationActive ? 'Reset' : 'Simulate Enforcement'}
                </button>
              </div>
              <div className="relative z-10">
                <AnimatePresence mode="popLayout">
                  <motion.span 
                    key={isSimulationActive ? 'green' : 'red'}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className={`text-3xl font-black font-mono leading-none tracking-tighter ${isSimulationActive ? 'text-emerald-500' : 'text-rose-500'}`}
                  >
                    ₹{analysis.economicBleed.toLocaleString()} <span className="text-base text-slate-500 font-normal">/ hr</span>
                  </motion.span>
                </AnimatePresence>
              </div>
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

            {/* Isometric 3D Visualization */}
            <div className="relative h-40 bg-slate-900/60 rounded-xl overflow-hidden mb-5 flex items-center justify-center border border-slate-700 perspective-1000">
              <div
                className="relative w-[180px] h-[250px] preserve-3d"
                style={{ transform: "rotateX(60deg) rotateZ(-45deg)" }}
              >
                {/* Road Base */}
                <div className="absolute inset-0 bg-slate-800 border-2 border-slate-600 rounded-sm" />
                
                {/* Center Line */}
                <div className="absolute inset-y-0 left-1/2 w-1 -translate-x-1/2 bg-[repeating-linear-gradient(0deg,transparent,transparent_10px,rgba(255,255,255,0.3)_10px,rgba(255,255,255,0.3)_20px)]" />

                {/* The Obstruction (Illegally Parked Vehicle) */}
                <motion.div
                  initial={{ z: 50, opacity: 0 }}
                  animate={{ z: 0, opacity: 1, width: `${analysis.chokePercent}%` }}
                  className="absolute bottom-1/2 left-2 bg-rose-600 rounded flex items-center justify-center shadow-[0_0_15px_rgba(225,29,72,0.5)]"
                  style={{ height: '30px', transform: "translateZ(10px)" }}
                >
                  <div className="text-white text-[9px] font-bold rotate-90 opacity-80">{analysis.dominantVehicle.replace("_", " ")}</div>
                </motion.div>

                {/* Simulated Queue of Cars trapped behind */}
                {!isSimulationActive && (
                  <div className="absolute bottom-4 left-2 w-[40%] flex flex-col gap-2">
                    {[...Array(3)].map((_, i) => (
                      <motion.div
                        key={i}
                        initial={{ y: 50, opacity: 0 }}
                        animate={{ y: 0, opacity: 1 }}
                        transition={{ delay: i * 0.2, repeat: Infinity, duration: 2 }}
                        className="w-full h-6 bg-amber-500/80 rounded-sm shadow-lg"
                        style={{ transform: "translateZ(5px)" }}
                      />
                    ))}
                  </div>
                )}
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
            <div className="mb-5">
              <p className="text-[10px] text-slate-400 font-mono uppercase tracking-widest mb-3 flex items-center gap-2">
                <Brain className="w-3 h-3 text-indigo-400" /> AI Inference Drivers
              </p>
              <div className="bg-slate-900/40 rounded-xl p-4 border border-slate-700/60 space-y-3">
                {shapData ? (
                  <>
                    {[...(shapData.top_positive_contributors || []), ...(shapData.top_negative_contributors || [])]
                      .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
                      .slice(0, 4)
                      .map((c: any, i: number) => {
                        const width = Math.min(100, Math.max(10, Math.abs(c.impact) * 100));
                        return (
                          <div key={i} className="flex flex-col gap-1">
                            <div className="flex justify-between text-[10px] font-mono text-slate-300">
                              <span>{mapFeatureToLabel(c.feature, c.impact).split(' (')[0]}</span>
                              <span className="font-bold">{mapFeatureToLabel(c.feature, c.impact).split('(')[1]?.replace(')', '')}</span>
                            </div>
                            <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                              <motion.div 
                                initial={{ width: 0 }}
                                animate={{ width: `${width}%` }}
                                className={`h-full rounded-full ${getShapColor(c.impact)}`}
                              />
                            </div>
                          </div>
                        );
                    })}
                  </>
                ) : (
                  <div className="text-xs text-slate-500 font-mono animate-pulse">Calculating SHAP values from LRU Cache...</div>
                )}
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
