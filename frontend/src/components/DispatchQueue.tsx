"use client";

import React, { useEffect, useState, useRef } from "react";
import { useMapStore } from "@/store/useMapStore";
import { AlertTriangle, MapPin, Crosshair, ChevronLeft, ChevronRight, Radio } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

function EPSPill({ eps }: { eps: number }) {
  const bg =
    eps >= 90 ? "bg-[#831843]" :
    eps >= 70 ? "bg-[#ef4444]" :
    eps >= 50 ? "bg-[#eab308]" :
    eps >= 30 ? "bg-[#facc15]" :
    "bg-[#10b981]";
  const label =
    eps >= 90 ? "CRITICAL" :
    eps >= 70 ? "HIGH" :
    eps >= 50 ? "MEDIUM" :
    eps >= 30 ? "WATCH" :
    "CLEAR";
  return (
    <div className={`${bg} text-white text-[9px] font-black font-mono px-2 py-0.5 rounded-full flex items-center gap-1`}>
      <span className="w-1.5 h-1.5 rounded-full bg-white/80 animate-pulse" />
      {label}
    </div>
  );
}

export default function DispatchQueue() {
  const { flyTo, setSelectedEdge, targetHour } = useMapStore();
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    setLoading(true);
    const hourParam = targetHour || "live";

    fetch(`/api/predictions?hour=${hourParam}`)
      .then((r) => r.json())
      .then((data) => {
        if (data && data.features) {
          const loaded = data.features.filter((f: any) => !f.properties.is_ripple).map((f: any) => ({
            id: f.properties.segment_id,
            roadName: f.properties.road_name || "Unknown Road",
            roadClass: f.properties.road_class,
            width: f.properties.road_width_m,
            eps: f.properties.eps,
            priorityBand: f.properties.priority_band,
            action: f.properties.recommended_action,
            geometry: f.geometry,
            ...f.properties, // Capture all properties for physics inspector
          }));
          // setSegments(loaded);
          const features = (data.features || [])
            .filter((f: any) => !f.properties.is_ripple)
            .sort((a: any, b: any) => b.properties.eps - a.properties.eps)
            .slice(0, 15);
          setQueue(features);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [targetHour]);

  const handleClick = (feature: any) => {
    const coords = feature.geometry?.coordinates || [];
    const mid = coords[Math.floor(coords.length / 2)] || coords[0];
    if (mid) flyTo(mid[0], mid[1], 17);
    setSelectedEdge(feature.properties);
  };

  const handleFeedback = async (feature: any, accuracy: string) => {
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          edge_id: feature.properties.segment_id,
          predicted_eps: feature.properties.eps,
          actual_accuracy: accuracy,
        })
      });
      // Remove from queue locally
      setQueue((q) => q.filter((f) => f.properties.segment_id !== feature.properties.segment_id));
    } catch (e) {
      console.error("Feedback failed", e);
    }
  };

  return (
    <div className="absolute top-24 left-4 w-96 bottom-8 z-30 flex flex-col rounded-2xl border border-slate-700 shadow-2xl overflow-hidden bg-slate-800/80 backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-col px-5 py-4 border-b border-slate-700/80 bg-slate-900/50">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-rose-500/20 border border-rose-500/40">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
            </div>
            <div>
              <p className="text-white font-bold text-xs uppercase tracking-widest">Active Dispatch</p>
              <p className="text-slate-400 text-[10px] font-mono">{queue.length} critical segments</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 bg-rose-500 rounded-full animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.8)]" />
            <span className="text-[10px] text-rose-400 font-mono font-bold">LIVE</span>
          </div>
        </div>

        <button 
          onClick={() => console.log("Optimizing TSP Route...")}
          className="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs uppercase tracking-widest shadow-[0_4px_14px_rgba(79,70,229,0.4)] transition-all flex items-center justify-center gap-2"
        >
          <Radio className="w-4 h-4" />
          Optimize Patrol Route
        </button>
      </div>

            {/* Cards */}
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {loading ? (
                <div className="flex items-center justify-center h-40">
                  <div className="w-6 h-6 border-2 border-rose-500/60 border-t-transparent rounded-full animate-spin" />
                </div>
              ) : queue.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-40 gap-2 text-slate-600">
                  <Radio className="w-8 h-8 opacity-30" />
                  <p className="text-xs font-mono">No active hotspots</p>
                </div>
              ) : (
                <div className="divide-y divide-slate-800/50">
                  {queue.map((feature, idx) => {
                    const p = feature.properties;
                    const eps: number = p.eps ?? 0;
                    const lineColor =
                      eps >= 90 ? "border-l-[#831843]" :
                      eps >= 70 ? "border-l-[#ef4444]" :
                      eps >= 50 ? "border-l-[#eab308]" :
                      eps >= 30 ? "border-l-[#facc15]" :
                      "border-l-[#10b981]";

                    return (
                      <motion.div
                        key={p.segment_id}
                        initial={{ opacity: 0, x: -16 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: idx * 0.04 }}
                        whileHover={{ backgroundColor: "rgba(255,255,255,0.04)" }}
                        onClick={() => handleClick(feature)}
                        className={`cursor-pointer px-4 py-3 border-l-[3px] ${lineColor} transition-all`}
                      >
                        <div className="flex items-start justify-between gap-2 mb-1.5">
                          <div className="flex items-start gap-1.5 min-w-0">
                            <span className="text-slate-600 text-[10px] font-mono mt-0.5 flex-shrink-0">
                              {String(idx + 1).padStart(2, "0")}
                            </span>
                            <p className="text-slate-200 text-xs font-semibold leading-tight line-clamp-2">
                              {p.road_name || (p.junction_name !== "No Junction" ? p.junction_name : null) || p.police_station || "Unknown"}
                            </p>
                          </div>
                          <EPSPill eps={eps} />
                        </div>

                        <div className="pl-6 mt-2 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-[9px] text-slate-500 font-mono uppercase">Mark Resolved:</span>
                            <button onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "Yes"); }} className="p-1 hover:bg-emerald-500/20 text-slate-500 hover:text-emerald-400 rounded transition-colors" title="Accurate">
                              👍
                            </button>
                            <button onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "Partial"); }} className="p-1 hover:bg-yellow-500/20 text-slate-500 hover:text-yellow-400 rounded transition-colors" title="Partial">
                              🤔
                            </button>
                            <button onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "No"); }} className="p-1 hover:bg-rose-500/20 text-slate-500 hover:text-rose-400 rounded transition-colors" title="Inaccurate">
                              👎
                            </button>
                          </div>
                          <div className="flex items-center gap-1 text-slate-600 hover:text-cyan-400 transition-colors">
                            <Crosshair className="w-3 h-3" />
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-5 py-3 border-t border-slate-700/80 bg-slate-900/50">
              <p className="text-slate-500 text-[10px] font-mono text-center">
                LightGBM · MapmyIndia · 298K events
              </p>
            </div>
    </div>
  );
}
