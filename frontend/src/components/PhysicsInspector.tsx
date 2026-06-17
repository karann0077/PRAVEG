"use client";

import React, { useMemo } from "react";
import { useMapStore } from "@/store/useMapStore";
import { motion, AnimatePresence } from "framer-motion";
import { X, Activity, Ruler, AlertTriangle, TrendingDown, Car } from "lucide-react";

const VEHICLE_WIDTHS: Record<string, number> = {
  heavy: 2.6,
  light_commercial: 2.3,
  car: 1.9,
  auto: 1.3,
  two_wheeler: 0.8,
  other: 1.9,
};

const ROAD_LABELS: Record<string, string> = {
  motorway: "Motorway / Expressway",
  trunk: "Trunk Road",
  primary: "Primary Arterial",
  secondary: "Secondary Collector",
  tertiary: "Local Distributor",
  residential: "Residential Lane",
  unknown: "Unknown",
};

export default function PhysicsInspector() {
  const { selectedEdge, setSelectedEdge } = useMapStore();

  const analysis = useMemo(() => {
    if (!selectedEdge) return null;
    const eps: number = selectedEdge.eps ?? 0;
    const roadWidth: number = selectedEdge.road_width_m ?? 6.0;
    const roadClass: string = selectedEdge.road_class ?? "unknown";

    // Determine dominant vehicle from predicted totals
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
    const capacityRatio = vehicleWidth / roadWidth;
    const interruption = (capacityRatio ** 2) * (eps >= 90 ? 2.5 : eps >= 60 ? 1.0 : 0.5);
    const clearance = Math.max(0, roadWidth - vehicleWidth);
    const chokePercent = Math.min(100, (vehicleWidth / roadWidth) * 100);
    const isEmergency = clearance < 3.0;

    return { eps, roadWidth, roadClass, vehicleWidth, dominantVehicle, clearance, chokePercent, interruption, isEmergency };
  }, [selectedEdge]);

  return (
    <AnimatePresence>
      {selectedEdge && analysis && (
        <motion.div
          key="physics-inspector"
          initial={{ opacity: 0, y: 60, scale: 0.92 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 60, scale: 0.92 }}
          transition={{ type: "spring", stiffness: 260, damping: 24 }}
          className="absolute bottom-28 right-5 w-[420px] z-30 rounded-2xl overflow-hidden border border-slate-700/60 shadow-2xl"
          style={{
            background: "rgba(8,15,30,0.92)",
            backdropFilter: "blur(28px)",
            boxShadow:
              analysis.eps >= 90
                ? "0 0 40px rgba(225,29,72,0.25), 0 25px 50px rgba(0,0,0,0.6)"
                : "0 25px 50px rgba(0,0,0,0.6)",
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800 bg-slate-900/50">
            <h3 className="text-white text-sm font-bold flex items-center gap-2">
              <div className="p-1 bg-cyan-500/15 rounded-md">
                <Activity className="w-3.5 h-3.5 text-cyan-400" />
              </div>
              Bottleneck Physics Inspector
            </h3>
            <button
              onClick={() => setSelectedEdge(null)}
              className="p-1.5 rounded-full hover:bg-slate-700/80 text-slate-500 hover:text-white transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="p-5 space-y-5">
            {/* ID + EPS */}
            <div className="flex justify-between items-center">
              <div>
                <p className="text-slate-500 text-[10px] font-mono uppercase tracking-widest mb-1">
                  Segment ID
                </p>
                <p className="text-slate-300 text-xs font-mono truncate max-w-[200px]">
                  {selectedEdge.segment_id}
                </p>
              </div>
              <div className="text-right">
                <p className="text-slate-500 text-[10px] font-mono uppercase tracking-widest mb-1">
                  EPS Score
                </p>
                <p
                  className={`text-3xl font-black font-mono ${
                    analysis.eps >= 90
                      ? "text-rose-500 drop-shadow-[0_0_10px_rgba(244,63,94,0.8)]"
                      : analysis.eps >= 60
                      ? "text-orange-400"
                      : "text-yellow-400"
                  }`}
                >
                  {analysis.eps.toFixed(1)}
                </p>
              </div>
            </div>

            {/* Road Info Row */}
            <div className="grid grid-cols-3 gap-3 text-xs">
              <div className="bg-slate-800/60 rounded-xl p-3 border border-slate-700/40">
                <Ruler className="w-3.5 h-3.5 text-cyan-400 mb-1.5" />
                <p className="text-slate-500 text-[9px] uppercase tracking-wider">Road Width</p>
                <p className="text-white font-bold font-mono mt-0.5">{analysis.roadWidth}m</p>
              </div>
              <div className="bg-slate-800/60 rounded-xl p-3 border border-slate-700/40">
                <Car className="w-3.5 h-3.5 text-purple-400 mb-1.5" />
                <p className="text-slate-500 text-[9px] uppercase tracking-wider">Vehicle</p>
                <p className="text-white font-bold font-mono mt-0.5 capitalize">
                  {analysis.dominantVehicle.replace("_", " ")}
                </p>
              </div>
              <div
                className={`rounded-xl p-3 border ${
                  analysis.isEmergency
                    ? "bg-rose-900/30 border-rose-500/40"
                    : "bg-slate-800/60 border-slate-700/40"
                }`}
              >
                <TrendingDown
                  className={`w-3.5 h-3.5 mb-1.5 ${analysis.isEmergency ? "text-rose-400" : "text-emerald-400"}`}
                />
                <p className="text-slate-500 text-[9px] uppercase tracking-wider">Clearance</p>
                <p
                  className={`font-bold font-mono mt-0.5 ${
                    analysis.isEmergency ? "text-rose-400" : "text-emerald-400"
                  }`}
                >
                  {analysis.clearance.toFixed(1)}m
                </p>
              </div>
            </div>

            {/* 2D Road Cross-Section Visualizer */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <p className="text-slate-400 text-[10px] font-mono uppercase tracking-widest">
                  Road Cross-Section View
                </p>
                <p className="text-slate-500 text-[10px] font-mono">
                  Total: {analysis.roadWidth}m
                </p>
              </div>

              {/* The physical cross-section */}
              <div className="relative h-14 rounded-xl overflow-hidden border border-slate-600/40 bg-slate-800/30 flex">
                {/* Road surface texture */}
                <div className="absolute inset-0 opacity-10 bg-[repeating-linear-gradient(90deg,transparent,transparent_20px,rgba(255,255,255,0.05)_20px,rgba(255,255,255,0.05)_22px)]" />

                {/* Parked vehicle block */}
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${analysis.chokePercent}%` }}
                  transition={{ duration: 1.2, ease: [0.25, 0.46, 0.45, 0.94] }}
                  className={`h-full flex items-center justify-center relative border-r-2 ${
                    analysis.eps >= 90
                      ? "bg-rose-500/70 border-rose-400"
                      : "bg-orange-500/60 border-orange-400"
                  }`}
                  style={{
                    backgroundImage:
                      "repeating-linear-gradient(45deg, transparent, transparent 8px, rgba(0,0,0,0.15) 8px, rgba(0,0,0,0.15) 16px)",
                  }}
                >
                  <div className="flex flex-col items-center z-10">
                    <span className="text-white text-[10px] font-black font-mono drop-shadow-md">
                      {analysis.vehicleWidth}m
                    </span>
                    <span className="text-white/70 text-[8px] uppercase tracking-wider capitalize">
                      {analysis.dominantVehicle.replace("_", " ")}
                    </span>
                  </div>
                </motion.div>

                {/* Remaining clearance block */}
                <div className="flex-1 h-full flex items-center justify-center">
                  <div className="text-center">
                    <p
                      className={`text-sm font-bold font-mono ${
                        analysis.isEmergency ? "text-rose-400" : "text-emerald-400"
                      }`}
                    >
                      {analysis.clearance.toFixed(1)}m
                    </p>
                    <p className="text-slate-600 text-[9px]">remaining</p>
                  </div>
                </div>
              </div>

              {/* Scale labels */}
              <div className="flex justify-between text-[9px] font-mono text-slate-600 mt-1 px-1">
                <span>◄ Blocked: {analysis.chokePercent.toFixed(0)}%</span>
                <span>Free-flow ►</span>
              </div>
            </div>

            {/* Physics Formula Box */}
            <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-3.5">
              <p className="text-[10px] text-cyan-400 font-mono uppercase tracking-widest mb-2">
                Mathematical Execution
              </p>
              <p className="text-slate-300 text-xs leading-relaxed font-mono">
                I = ({analysis.vehicleWidth}m / {analysis.roadWidth}m)² × γ<br />
                I = {(analysis.vehicleWidth / analysis.roadWidth).toFixed(3)}² × {analysis.eps >= 90 ? "2.5" : "1.0"}{" "}
                = <span className={`font-bold ${analysis.eps >= 90 ? "text-rose-400" : "text-orange-400"}`}>
                  {analysis.interruption.toFixed(3)}
                </span>
              </p>
              {analysis.isEmergency && (
                <div className="mt-2.5 flex items-center gap-2 bg-rose-500/15 border border-rose-500/30 rounded-lg px-2.5 py-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0 animate-pulse" />
                  <p className="text-rose-400 text-[10px] font-bold uppercase tracking-wider">
                    Emergency Gridlock — &lt;3m clearance
                  </p>
                </div>
              )}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
