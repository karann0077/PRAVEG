"use client";

import React, { useEffect, useState } from "react";
import { useMapStore } from "@/store/useMapStore";
import { AlertTriangle, Map, Navigation, CheckCircle, AlertCircle, XCircle, ChevronLeft, ChevronRight, ShieldAlert, Crosshair, Activity } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

function PriorityBadge({ score }: { score: number }) {
  const isCritical = score >= 80;
  const isHigh = score >= 60;
  const isWatch = score >= 40;

  const bg = isCritical ? "bg-rose-500/10 border-rose-500/30 text-rose-400" :
             isHigh ? "bg-orange-500/10 border-orange-500/30 text-orange-400" :
             isWatch ? "bg-amber-500/10 border-amber-500/30 text-amber-400" :
             "bg-zinc-800/50 border-zinc-700/50 text-zinc-400";
             
  const label = isCritical ? "CRITICAL" :
                isHigh ? "HIGH PRIORITY" :
                isWatch ? "WATCHLIST" : "MONITOR";
                
  const glow = isCritical ? "shadow-[0_0_10px_rgba(244,63,94,0.2)]" : "";

  return (
    <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded border ${bg} ${glow}`}>
      {isCritical && <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />}
      <span className="text-[9px] font-bold tracking-widest">{label}</span>
    </div>
  );
}

function ConfidenceBadge({ band }: { band: string }) {
  const isHigh = band === "High";
  const isMed = band === "Medium";
  
  const color = isHigh ? "text-emerald-400" : isMed ? "text-blue-400" : "text-zinc-500";
  const label = isHigh ? "High Acc" : isMed ? "Med Acc" : "Low Acc";

  return (
    <div className={`flex items-center gap-1 ${color}`}>
      <Crosshair className="w-3 h-3" />
      <span className="text-[9px] font-mono font-medium tracking-wide uppercase">{label}</span>
    </div>
  );
}

export default function DispatchQueue() {
  const { flyTo, setSelectedEdge, geoData, selectedEdge } = useMapStore();
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
        animate={{ x: open ? 0 : -420 }}
        transition={{ type: "spring", bounce: 0, damping: 25, stiffness: 200 }}
        className="absolute top-[88px] left-0 w-[420px] bottom-0 z-30 flex flex-col border-r border-white/5 overflow-hidden shadow-[30px_0_60px_-15px_rgba(0,0,0,0.8)]"
        style={{
          background: "linear-gradient(160deg, rgba(11, 15, 26, 0.95) 0%, rgba(6, 9, 16, 0.98) 100%)",
          backdropFilter: "blur(20px)"
        }}
      >
        {/* Header */}
        <div className="relative flex flex-col px-6 py-5 border-b border-white/5 bg-gradient-to-r from-blue-900/10 to-transparent">
          <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-blue-500/20 to-transparent" />
          
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <div className="relative p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
                <ShieldAlert className="w-5 h-5 text-blue-400" />
                <div className="absolute inset-0 bg-blue-400/20 blur-md rounded-lg" />
              </div>
              <div>
                <h2 className="text-white font-heading font-bold text-sm tracking-[0.2em] uppercase">Dispatch Queue</h2>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-zinc-400 text-[11px] font-mono">{queue.length} targets identified</span>
                </div>
              </div>
            </div>
            
            <div className="flex flex-col items-end gap-1.5">
              <div className="flex items-center gap-2 px-2 py-1 rounded bg-rose-500/10 border border-rose-500/20">
                <div className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.8)]" />
                <span className="text-[9px] text-rose-400 font-bold uppercase tracking-widest leading-none mt-px">LIVE SYNC</span>
              </div>
              <span className="text-[9px] text-zinc-600 font-mono tracking-widest uppercase">Updated Just Now</span>
            </div>
          </div>
        </div>

        {/* Cards List */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <div className="w-8 h-8 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
            </div>
          ) : queue.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-zinc-600">
              <div className="p-4 rounded-full bg-white/5 border border-white/5">
                <CheckCircle className="w-8 h-8 text-emerald-500/50" />
              </div>
              <p className="text-xs font-mono uppercase tracking-widest text-zinc-500">All zones clear</p>
            </div>
          ) : (
            <AnimatePresence>
              {queue.map((feature, idx) => {
                const p = feature.properties;
                const priority_score: number = p.eps ?? 0;
                const confidence_band = p.confidence_band || "Low";
                const actionStatus = actionStates[p.segment_id] || "Not sent";
                const isCritical = priority_score >= 80;
                const isSelected = selectedEdge?.properties?.segment_id === p.segment_id;

                return (
                  <motion.div
                    layout
                    key={p.segment_id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ delay: idx * 0.03, duration: 0.3 }}
                    onClick={() => handleClick(feature)}
                    className={`group relative cursor-pointer overflow-hidden rounded-xl transition-all duration-300 border ${
                      isSelected 
                        ? 'bg-[#060D1A] border-cyan-500/50 shadow-[0_0_30px_rgba(34,211,238,0.15)] pl-5' 
                        : 'bg-white/[0.02] border-white/5 hover:bg-white/[0.04] hover:border-white/10 pl-4'
                    }`}
                  >
                    {/* Active State Cyan Edge */}
                    {isSelected && (
                      <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.8)]" />
                    )}
                    {/* Status Background Glow */}
                    {isCritical && (
                      <div className="absolute top-0 right-0 w-32 h-32 bg-rose-500/10 blur-[50px] rounded-full pointer-events-none -translate-y-1/2 translate-x-1/2" />
                    )}

                    {/* Content */}
                    <div className="relative z-10 p-4">
                      <div className="flex items-start justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <div className={`flex items-center justify-center w-6 h-6 rounded bg-black/40 border ${isCritical ? 'border-rose-500/30 text-rose-400' : 'border-white/10 text-zinc-500'} text-[10px] font-mono font-bold`}>
                            {String(idx + 1).padStart(2, "0")}
                          </div>
                          <div className="flex flex-col">
                            <span className="text-white text-sm font-bold leading-tight line-clamp-1 pr-4">
                              {p.road_name || (p.junction_name !== "No Junction" ? p.junction_name : null) || p.police_station || "Unknown Target"}
                            </span>
                          </div>
                        </div>
                        <PriorityBadge score={priority_score} />
                      </div>

                      <div className="flex items-end justify-between">
                        <div className="flex flex-col gap-1.5">
                          <div className="flex items-center gap-2 text-xs">
                            <span className="text-zinc-400 font-medium">{p.police_station} PS</span>
                            <span className="text-zinc-600">|</span>
                            <ConfidenceBadge band={confidence_band} />
                          </div>
                          <div className="flex items-center gap-1.5 mt-0.5 bg-white/5 px-2 py-1 rounded-md border border-white/5 w-max">
                            <Activity className={`w-3.5 h-3.5 ${isCritical ? 'text-rose-400' : 'text-cyan-400'}`} />
                            <span className="text-[9px] text-zinc-400 font-mono tracking-widest uppercase">
                              Est. Load: <span className={`font-bold text-xs ${isCritical ? 'text-rose-400 drop-shadow-[0_0_5px_rgba(244,63,94,0.5)]' : 'text-cyan-400 drop-shadow-[0_0_5px_rgba(34,211,238,0.5)]'}`}>{Math.round(p.predicted_total || 0)}</span> veh
                            </span>
                          </div>
                        </div>

                        {/* Action Status / Score */}
                        <div className="flex flex-col items-end">
                          <div className="text-[10px] uppercase font-mono tracking-widest text-zinc-500 mb-1">Impact Score</div>
                          <div className="text-2xl font-bold font-mono leading-none tracking-tighter text-white">
                            {Math.round(priority_score)}
                          </div>
                        </div>
                      </div>

                      {/* Quick Actions overlay */}
                      <div className="absolute inset-x-0 bottom-0 top-1/2 bg-gradient-to-t from-black/90 via-black/60 to-transparent translate-y-full group-hover:translate-y-0 transition-transform duration-300 flex items-end justify-end p-3 gap-2">
                         {actionStatus !== "Not sent" ? (
                           <div className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-500/20 border border-emerald-500/30 w-full justify-center">
                             <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                             <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">{actionStatus}</span>
                           </div>
                         ) : (
                           <>
                             <button 
                               onClick={(e) => { e.stopPropagation(); setActionStates(prev => ({ ...prev, [p.segment_id]: "Team dispatched" })); }}
                               className="flex-1 py-1.5 bg-blue-500 hover:bg-blue-400 text-white rounded text-[10px] font-bold tracking-widest uppercase transition-colors"
                             >
                               Dispatch
                             </button>
                             <button 
                               onClick={(e) => { e.stopPropagation(); handleFeedback(feature, "Yes"); }}
                               className="px-3 py-1.5 bg-white/10 hover:bg-white/20 text-white rounded text-[10px] font-bold tracking-widest uppercase transition-colors"
                             >
                               Clear
                             </button>
                           </>
                         )}
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          )}
        </div>
      </motion.div>

      {/* Toggle Button */}
      <motion.button
        initial={false}
        animate={{ x: open ? 420 : 0 }}
        transition={{ type: "spring", bounce: 0, damping: 25, stiffness: 200 }}
        onClick={() => setOpen(!open)}
        className="absolute top-[160px] left-0 z-20 h-20 w-7 bg-[#0B0F1A]/90 backdrop-blur-md border-y border-r border-white/10 rounded-r-xl flex items-center justify-center hover:bg-white/10 hover:w-8 transition-all cursor-pointer shadow-[10px_0_20px_-5px_rgba(0,0,0,0.5)] group"
      >
        {open ? (
          <ChevronLeft className="w-4 h-4 text-zinc-400 group-hover:text-white" />
        ) : (
          <ChevronRight className="w-4 h-4 text-zinc-400 group-hover:text-white" />
        )}
      </motion.button>
    </>
  );
}
