"use client";

import React, { useMemo, useState } from "react";
import { useMapStore } from "@/store/useMapStore";
import { motion, AnimatePresence } from "framer-motion";
import { X, Activity, Truck, AlertTriangle, ShieldAlert, Crosshair, Brain, Ruler, Navigation, Timer } from "lucide-react";

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
  const [dispatchConfirm, setDispatchConfirm] = useState(false);

  React.useEffect(() => {
    let timer: NodeJS.Timeout;
    if (dispatchConfirm) {
      timer = setTimeout(() => setDispatchConfirm(false), 3000);
    }
    return () => clearTimeout(timer);
  }, [dispatchConfirm]);

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
          className="absolute top-24 right-4 w-[400px] z-30 flex flex-col rounded-2xl glass-panel overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/5 bg-black/20">
            <div>
              <h3 className="text-white text-[16px] font-heading font-bold flex items-center gap-2 uppercase tracking-widest mb-1.5">
                <Crosshair className="w-4 h-4 text-[#3b82f6] drop-shadow-[0_0_8px_rgba(59,130,246,0.8)]" />
                {selectedEdge.road_name || selectedEdge.junction_name || "Unknown Link"}
              </h3>
              
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 bg-black/40 px-2 py-1 rounded-md border border-white/5">
                  <div className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
                  <span className="text-[10px] font-mono text-zinc-300">EPS {analysis.eps.toFixed(1)}</span>
                  <span className="text-[9px] font-mono text-zinc-500">± 2.5</span>
                </div>
              </div>
            </div>
            <button
              onClick={() => setSelectedEdge(null)}
              className="p-1.5 rounded-full hover:bg-zinc-800 text-zinc-400 hover:text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-5 overflow-y-auto custom-scrollbar max-h-[70vh] space-y-5">
            {/* Economic Impact Card */}
            <div className="p-4 rounded-xl border border-white/5 bg-black/40 relative overflow-hidden group shadow-inner">
              <div className="absolute inset-0 bg-gradient-to-r from-rose-600/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="flex items-center justify-between mb-4 relative z-10">
                <p className="text-[10px] text-zinc-400 font-mono uppercase tracking-widest">
                  Estimated Economic Loss
                </p>
              </div>
              <div className="relative z-10 mb-4">
                <AnimatePresence mode="popLayout">
                  <motion.span 
                    key={isSimulationActive ? 'green' : 'red'}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className={`text-[28px] font-black font-mono leading-none tracking-tighter ${isSimulationActive ? 'text-emerald-500' : 'text-[#ef4444]'}`}
                  >
                    ₹{analysis.economicBleed.toLocaleString(undefined, { maximumFractionDigits: 0 })} <span className="text-sm text-zinc-500 font-normal">/ hr</span>
                  </motion.span>
                </AnimatePresence>
              </div>

              {/* 7-day mini sparkline mock */}
              <div className="flex items-end gap-1 h-8 mb-5 relative z-10 opacity-70">
                {[30, 45, 20, 60, 80, 50, 90].map((h, i) => (
                  <motion.div 
                    key={i}
                    initial={{ height: 0 }}
                    animate={{ height: `${h}%` }}
                    transition={{ delay: i * 0.05 }}
                    className={`flex-1 rounded-t-sm ${i === 6 ? (isSimulationActive ? 'bg-emerald-500' : 'bg-rose-500') : 'bg-zinc-700'}`}
                  />
                ))}
              </div>

              <button 
                onClick={() => setIsSimulationActive(!isSimulationActive)}
                className={`w-full relative z-10 text-[11px] font-bold py-2.5 rounded-[6px] uppercase tracking-wider transition-colors ${isSimulationActive ? 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-white/5' : 'bg-[#3b82f6]/20 text-[#3b82f6] border border-[#3b82f6]/30 hover:bg-[#3b82f6]/30'}`}
              >
                {isSimulationActive ? 'Reset Scenario' : 'Simulate Enforcement'}
              </button>
            </div>

            {/* 2D Road Cross-Section Diagram */}
            <div className="relative h-32 bg-[#0B0F1A] rounded-xl border border-white/5 shadow-inner overflow-hidden flex flex-col justify-center px-6">
              <p className="absolute top-3 left-4 text-[9px] font-mono text-zinc-500 uppercase tracking-widest">Road Cross-Section</p>
              
              <div className="relative w-full h-12 mt-4 bg-zinc-900 border-y border-zinc-700 flex items-center">
                {/* Center Dash */}
                <div className="absolute inset-0 flex items-center justify-center">
                   <div className="w-full border-t-2 border-dashed border-zinc-600/50" />
                </div>

                {/* Clear Segment */}
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${100 - analysis.chokePercent}%` }}
                  className="h-full bg-[#22c55e]/20 border-y-2 border-[#22c55e]/50 flex items-center justify-center relative"
                >
                  <span className="text-[10px] font-mono font-bold text-[#22c55e]">{analysis.clearance.toFixed(1)}m</span>
                </motion.div>

                {/* Blocked Segment */}
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${analysis.chokePercent}%` }}
                  className="h-full bg-[#ef4444]/30 border-y-2 border-[#ef4444]/60 flex items-center justify-center relative"
                >
                  <span className="text-[10px] font-mono font-bold text-[#ef4444] whitespace-nowrap overflow-hidden px-1">
                    {analysis.dominantVehicle.replace("_", " ")}
                  </span>
                </motion.div>
              </div>
            </div>

            {/* Labeled Stat Chips */}
            <div className="flex items-center gap-2 text-sm">
              <div className="flex-1 bg-black/40 border border-white/5 rounded-lg p-2.5 flex flex-col">
                <span className="text-[10px] text-zinc-500 font-mono flex items-center gap-1.5 uppercase mb-1">
                  <Ruler className="w-3 h-3" /> Width
                </span>
                <span className="text-zinc-200 font-mono font-bold text-xs">{analysis.roadWidth}m</span>
              </div>
              <div className="flex-1 bg-black/40 border border-white/5 rounded-lg p-2.5 flex flex-col relative overflow-hidden">
                <div className={`absolute inset-0 opacity-10 ${analysis.chokePercent > 50 ? 'bg-[#ef4444]' : analysis.chokePercent > 25 ? 'bg-[#f97316]' : 'bg-zinc-500'}`} />
                <span className="text-[10px] text-zinc-500 font-mono flex items-center gap-1.5 uppercase mb-1 relative z-10">
                  <Activity className="w-3 h-3" /> Choke
                </span>
                <span className={`font-mono font-bold text-xs relative z-10 ${analysis.chokePercent > 50 ? 'text-[#ef4444]' : analysis.chokePercent > 25 ? 'text-[#f97316]' : 'text-zinc-200'}`}>
                  {analysis.chokePercent.toFixed(0)}%
                </span>
              </div>
              <div className="flex-1 bg-black/40 border border-white/5 rounded-lg p-2.5 flex flex-col">
                <span className="text-[10px] text-zinc-500 font-mono flex items-center gap-1.5 uppercase mb-1">
                  <Navigation className="w-3 h-3" /> Lane left
                </span>
                <span className="text-[#22c55e] font-mono font-bold text-xs">{analysis.clearance.toFixed(1)}m</span>
              </div>
            </div>

            {/* Explainable AI (SHAP) Metrics */}
            <div>
              <p className="text-[10px] text-zinc-400 font-mono uppercase tracking-widest mb-3 flex items-center gap-2">
                <Brain className="w-3 h-3 text-indigo-400" /> AI Inference Drivers
              </p>
              <div className="bg-black/40 rounded-xl p-4 border border-white/5 space-y-4 shadow-inner">
                {shapData ? (
                  <>
                    {[...(shapData.top_positive_contributors || []), ...(shapData.top_negative_contributors || [])]
                      .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
                      .slice(0, 4)
                      .map((c: any, i: number) => {
                        const width = Math.min(100, Math.max(10, Math.abs(c.impact) * 100));
                        return (
                          <div key={i} className="flex flex-col gap-1.5">
                            <div className="flex justify-between text-[10px] font-mono text-zinc-300">
                              <span>{mapFeatureToLabel(c.feature, c.impact).split(' (')[0]}</span>
                              <span className="font-bold">{mapFeatureToLabel(c.feature, c.impact).split('(')[1]?.replace(')', '')}</span>
                            </div>
                            <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden">
                              <motion.div 
                                initial={{ width: 0 }}
                                animate={{ width: `${width}%` }}
                                className={`h-full rounded-full shadow-[0_0_8px_currentcolor] ${getShapColor(c.impact)}`}
                              />
                            </div>
                          </div>
                        );
                    })}
                  </>
                ) : (
                  <div className="flex flex-col gap-3">
                    {[60, 80, 40].map((w, i) => (
                      <div key={i} className="flex flex-col gap-1.5">
                        <div className="w-1/3 h-2 bg-zinc-800/50 rounded animate-pulse" />
                        <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden">
                          <div className={`h-full bg-zinc-700 animate-pulse`} style={{ width: `${w}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Dispatch Button */}
            <button
              onClick={() => {
                if (!dispatchConfirm) {
                  setDispatchConfirm(true);
                } else {
                  setDispatchConfirm(false);
                  handleDispatch();
                }
              }}
              disabled={isSimulatingResolution}
              className={`w-full py-4 mt-2 rounded-[6px] flex items-center justify-center gap-2 font-bold transition-all ${
                isSimulatingResolution 
                  ? "bg-zinc-800 text-zinc-500 cursor-not-allowed border border-white/5" 
                  : dispatchConfirm
                  ? "bg-[#ef4444] text-white shadow-[0_0_20px_rgba(239,68,68,0.4)]"
                  : "bg-[#f97316] hover:bg-[#ea580c] text-white shadow-[0_0_20px_rgba(249,115,22,0.3)]"
              }`}
            >
              {isSimulatingResolution ? (
                <>
                  <ShieldAlert className="w-4 h-4" />
                  <span className="text-xs tracking-wider">Unit En Route</span>
                </>
              ) : dispatchConfirm ? (
                <>
                  <Timer className="w-4 h-4 animate-pulse" />
                  <span className="text-[13px]">Confirm dispatch? (3s)</span>
                </>
              ) : (
                <>
                  <ShieldAlert className="w-4 h-4" />
                  <span className="text-[13px]">Dispatch tow unit</span>
                </>
              )}
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
