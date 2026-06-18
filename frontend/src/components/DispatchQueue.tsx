"use client";

import React, { useEffect, useState, useRef } from "react";
import { useMapStore } from "@/store/useMapStore";
import { AlertTriangle, Crosshair, Map, Navigation, CheckCircle, AlertCircle, XCircle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

function EPSPill({ eps }: { eps: number }) {
  const bg =
    eps >= 90 ? "bg-[#ef4444]/20 text-[#ef4444] border-[#ef4444]/30" :
    eps >= 70 ? "bg-[#f97316]/20 text-[#f97316] border-[#f97316]/30" :
    eps >= 50 ? "bg-[#eab308]/20 text-[#eab308] border-[#eab308]/30" :
    eps >= 30 ? "bg-[#facc15]/20 text-[#facc15] border-[#facc15]/30" :
    "bg-[#22c55e]/20 text-[#22c55e] border-[#22c55e]/30";
  const label =
    eps >= 90 ? "CRITICAL" :
    eps >= 70 ? "HIGH" :
    eps >= 50 ? "MEDIUM" :
    eps >= 30 ? "WATCH" :
    "CLEAR";
  return (
    <div className={`${bg} border text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-[6px] flex items-center`}>
      {label}
    </div>
  );
}

export default function DispatchQueue() {
  const { flyTo, setSelectedEdge, targetHour, geoData } = useMapStore();
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (!geoData) {
      setLoading(true);
      return;
    }
    setLoading(false);
    if (geoData && geoData.features) {
      const features = (geoData.features || [])
        .filter((f: any) => !f.properties.is_ripple)
        .sort((a: any, b: any) => b.properties.eps - a.properties.eps)
        .slice(0, 15);
      setQueue(features);
    }
  }, [geoData]);

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
    <div className="absolute top-[88px] left-0 w-[400px] bottom-0 z-30 flex flex-col bg-[#0B0F1A] border-r border-white/5 overflow-hidden">
      {/* Header */}
      <div className="flex flex-col px-6 py-5 border-b border-white/5 bg-[#0B0F1A]">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-[#3b82f6]/10 border border-[#3b82f6]/20">
              <AlertTriangle className="w-4 h-4 text-[#3b82f6]" />
            </div>
            <div>
              <p className="text-white font-heading font-bold text-sm tracking-widest uppercase">Active Dispatch</p>
              <p className="text-zinc-500 text-[11px] font-mono mt-0.5">{queue.length} critical segments pending</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-[#ef4444] animate-pulse shadow-[0_0_0_0_rgba(239,68,68,0.35)]" style={{ animation: 'pulse-ring 2s cubic-bezier(0.4, 0, 0.6, 1) infinite' }} />
              <span className="text-[10px] text-[#ef4444] font-mono font-bold uppercase tracking-widest">LIVE</span>
            </div>
            <span className="text-[9px] text-zinc-600 font-mono">Updated 2s ago</span>
          </div>
        </div>

        {/* Action Button */}
        <button className="w-full flex items-center justify-center gap-2 bg-[#3b82f6] hover:bg-[#2563eb] text-white py-3 px-4 rounded-[6px] transition-colors font-medium text-[13px]">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-white"></span>
          </span>
          Optimize patrol route
        </button>
      </div>

            {/* Cards */}
            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {loading ? (
                <div className="flex items-center justify-center h-40">
                  <div className="w-6 h-6 border-2 border-[#3b82f6]/60 border-t-transparent rounded-full animate-spin" />
                </div>
              ) : queue.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-40 gap-2 text-zinc-600">
                  <Navigation className="w-8 h-8 opacity-30" />
                  <p className="text-xs font-mono">No active hotspots</p>
                </div>
              ) : (
                <div className="divide-y divide-white/5">
                  <AnimatePresence>
                  {queue.map((feature, idx) => {
                    const p = feature.properties;
                    const eps: number = p.eps ?? 0;
                    const dotColor =
                      eps >= 90 ? "bg-[#ef4444] shadow-[0_0_8px_rgba(239,68,68,0.6)]" :
                      eps >= 70 ? "bg-[#f97316] shadow-[0_0_8px_rgba(249,115,22,0.6)]" :
                      eps >= 50 ? "bg-[#eab308]" :
                      eps >= 30 ? "bg-[#facc15]" :
                      "bg-[#22c55e]";
                    const isCritical = eps >= 70;

                    return (
                      <motion.div
                        layout
                        key={p.segment_id}
                        initial={{ opacity: 0, x: -16 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        transition={{ delay: idx * 0.04 }}
                        whileHover={{ backgroundColor: "rgba(255,255,255,0.02)" }}
                        onClick={() => handleClick(feature)}
                        className={`cursor-pointer px-6 py-4 transition-all group relative overflow-hidden`}
                      >
                        {/* Hover Reveal Actions Background */}
                        <div className="absolute top-0 right-0 bottom-0 w-32 bg-gradient-to-l from-[#0B0F1A] via-[#0B0F1A] to-transparent translate-x-full group-hover:translate-x-0 transition-transform duration-200 ease-out z-10 flex items-center justify-end pr-4 gap-2">
                          <button onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "Yes"); }} className="p-1.5 hover:bg-emerald-500/20 text-zinc-500 hover:text-emerald-400 rounded-full transition-colors" title="Mark Resolved">
                            <CheckCircle className="w-4 h-4" strokeWidth={1.5} />
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "Partial"); }} className="p-1.5 hover:bg-yellow-500/20 text-zinc-500 hover:text-yellow-400 rounded-full transition-colors" title="Needs Investigation">
                            <AlertCircle className="w-4 h-4" strokeWidth={1.5} />
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "No"); }} className="p-1.5 hover:bg-rose-500/20 text-zinc-500 hover:text-rose-400 rounded-full transition-colors" title="Inaccurate">
                            <XCircle className="w-4 h-4" strokeWidth={1.5} />
                          </button>
                        </div>

                        <div className="flex items-center justify-between gap-3 relative z-0">
                          <div className="flex items-center gap-3 min-w-0">
                            {/* Sequence Number */}
                            <span className="text-zinc-700 text-[10px] font-mono flex-shrink-0 w-4">
                              {String(idx + 1).padStart(2, "0")}
                            </span>
                            
                            {/* Severity Dot */}
                            <div className="relative flex items-center justify-center flex-shrink-0">
                              {isCritical && <span className={`absolute inset-0 rounded-full animate-ping opacity-50 ${dotColor}`} />}
                              <span className={`w-2 h-2 rounded-full ${dotColor}`} />
                            </div>

                            {/* Segment Name */}
                            <p className="text-zinc-200 text-[14px] font-medium leading-tight truncate">
                              {p.road_name || (p.junction_name !== "No Junction" ? p.junction_name : null) || p.police_station || "Unknown"}
                            </p>
                          </div>
                          
                          <div className="flex items-center gap-3">
                            <EPSPill eps={eps} />
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                  </AnimatePresence>
                </div>
              )}
            </div>
    </div>
  );
}
