"use client";

import React, { useEffect, useState } from "react";
import { useMapStore } from "@/store/useMapStore";
import { AlertTriangle, Map, Navigation, CheckCircle, AlertCircle, XCircle, ChevronLeft, ChevronRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

function PriorityPill({ priority_score, confidence_band }: { priority_score: number, confidence_band: string }) {
  const bg =
    priority_score >= 80 ? "bg-[#ef4444]/20 text-[#ef4444] border-[#ef4444]/30" :
    priority_score >= 60 ? "bg-[#f97316]/20 text-[#f97316] border-[#f97316]/30" :
    priority_score >= 40 ? "bg-[#eab308]/20 text-[#eab308] border-[#eab308]/30" :
    "bg-zinc-800 text-zinc-400 border-zinc-700";
  const label =
    priority_score >= 80 ? "🔴 Critical" :
    priority_score >= 60 ? "🟠 High" :
    priority_score >= 40 ? "🟡 Watch" :
    "⚪ Clear";
    
  const confBg = 
    confidence_band === "High" ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30" :
    confidence_band === "Medium" ? "bg-blue-500/20 text-blue-400 border-blue-500/30" :
    "bg-zinc-800 text-zinc-400 border-zinc-700";

  const confLabel = 
    confidence_band === "High" ? "Likely Accurate" : 
    confidence_band === "Medium" ? "Moderate Acc" : "Low Acc";

  return (
    <div className="flex flex-col gap-1 items-end">
      <div className={`${bg} border text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-[6px] flex items-center shadow-inner`}>
        {label} Priority
      </div>
    </div>
  );
}

export default function DispatchQueue() {
  const { flyTo, setSelectedEdge, geoData } = useMapStore();
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(true);
  // Track action states for features
  const [actionStates, setActionStates] = useState<Record<string, string>>({});

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
    setSelectedEdge(feature);
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
      // Mark as cleared instead of removing instantly to show state
      setActionStates(prev => ({ ...prev, [feature.properties.segment_id]: "Cleared" }));
      setTimeout(() => {
        setQueue((q) => q.filter((f) => f.properties.segment_id !== feature.properties.segment_id));
      }, 2000);
    } catch (e) {
      console.error("Feedback failed", e);
    }
  };

  return (
    <>
      <motion.div 
        initial={false}
        animate={{ x: open ? 0 : -400 }}
        transition={{ type: "spring", bounce: 0, duration: 0.4 }}
        className="absolute top-[88px] left-0 w-[400px] bottom-0 z-30 flex flex-col bg-[#0B0F1A] border-r border-white/5 overflow-hidden shadow-[20px_0_40px_-15px_rgba(0,0,0,0.8)]"
      >
      {/* Header */}
      <div className="flex flex-col px-6 py-5 border-b border-white/5 bg-[#0B0F1A]">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-[#3b82f6]/10 border border-[#3b82f6]/20">
              <AlertTriangle className="w-4 h-4 text-[#3b82f6]" />
            </div>
            <div>
              <p className="text-white font-heading font-bold text-sm tracking-widest uppercase">Dispatch Queue</p>
              <p className="text-zinc-500 text-[11px] font-mono mt-0.5">{queue.length} roads need attention</p>
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
                    const priority_score: number = p.eps ?? 0;
                    const confidence_band = p.confidence_band || "Low";
                    const isCritical = priority_score >= 80;
                    const actionStatus = actionStates[p.segment_id] || "Not sent";

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
                          <button onClick={(e) => { e.stopPropagation(); setActionStates(prev => ({ ...prev, [p.segment_id]: "Team sent" })); }} className="px-2 py-1 bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 rounded text-[10px] font-bold" title="Send Team">
                            Send
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "Yes"); }} className="px-2 py-1 bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 rounded text-[10px] font-bold" title="Mark Cleared">
                            Clear
                          </button>
                        </div>

                        <div className="flex items-center justify-between gap-3 relative z-0">
                          <div className="flex flex-col flex-1 min-w-0">
                            {/* Segment Name & Sequence */}
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-zinc-500 text-[10px] font-mono flex-shrink-0">
                                #{String(idx + 1).padStart(2, "0")}
                              </span>
                              <p className="text-zinc-200 text-[13px] font-bold leading-tight truncate">
                                {p.road_name || (p.junction_name !== "No Junction" ? p.junction_name : null) || p.police_station || "Unknown Road"}
                              </p>
                            </div>
                            
                            {/* Stats Line */}
                            <div className="flex items-center gap-3 pl-6">
                              <span className="text-[11px] text-zinc-400">
                                {p.police_station} Station · <span className="text-zinc-300 font-bold">{Math.round(p.predicted_total || 0)} vehicles expected</span>
                              </span>
                            </div>
                            {/* Action Status */}
                            <div className="flex items-center gap-3 pl-6 mt-1.5">
                              <span className={`text-[9px] font-bold uppercase tracking-wider ${
                                actionStatus === 'Cleared' ? 'text-emerald-400' :
                                actionStatus === 'Team sent' ? 'text-blue-400' :
                                'text-zinc-500'
                              }`}>
                                {actionStatus}
                              </span>
                            </div>
                          </div>
                          
                          <div className="flex items-center gap-3">
                            <PriorityPill priority_score={priority_score} confidence_band={confidence_band} />
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                  </AnimatePresence>
                </div>
              )}
            </div>
      </motion.div>

      {/* Toggle Button */}
      <motion.button
        initial={false}
        animate={{ x: open ? 400 : 0 }}
        transition={{ type: "spring", bounce: 0, duration: 0.4 }}
        onClick={() => setOpen(!open)}
        className="absolute top-[200px] left-0 z-20 h-16 w-6 bg-[#0B0F1A] border-y border-r border-white/10 rounded-r-lg flex items-center justify-center hover:bg-white/5 transition-colors cursor-pointer shadow-lg"
      >
        {open ? (
          <ChevronLeft className="w-4 h-4 text-zinc-500" />
        ) : (
          <ChevronRight className="w-4 h-4 text-zinc-500" />
        )}
      </motion.button>
    </>
  );
}
