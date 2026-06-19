"use client";

import React, { useMemo, useState } from "react";
import { useMapStore } from "@/store/useMapStore";
import { motion, AnimatePresence } from "framer-motion";
import { X, Activity, ShieldAlert, Crosshair, Brain, Ruler, Navigation, Timer, TrendingUp, MapPin, Gauge, ArrowRight } from "lucide-react";

const VEHICLE_WIDTHS: Record<string, number> = {
  heavy: 2.6,
  light_commercial: 2.3,
  car: 1.9,
  auto: 1.3,
  two_wheeler: 0.8,
  other: 1.9,
};

// Human-readable labels for AI features — no technical jargon
const FEATURE_LABELS: Record<string, string> = {
  segment_hour_mean: "This road usually has violations at this time",
  segment_dow_hour_mean: "Pattern for this day of week & time",
  city_hour_mean: "City-wide violation trend at this hour",
  city_dow_hour_mean: "City trend for this day & time",
  is_peak: "Rush hour — more vehicles on road",
  is_weekday_peak: "Weekday rush hour",
  is_weekend_peak: "Weekend peak hours",
  hour: "Time of day",
  hour_sin: "Time of day (cyclical)",
  hour_cos: "Time of day (cyclical)",
  day_of_week: "Day of the week",
  dow_sin: "Day of week (cyclical)",
  dow_cos: "Day of week (cyclical)",
  is_weekend: "Weekend — different parking patterns",
  month: "Month of year",
  month_sin: "Seasonal pattern",
  month_cos: "Seasonal pattern",
  overflow_risk_index: "No legal parking nearby — overflow likely",
  dist_to_legal_parking_m: "Distance to nearest legal parking",
  legal_parking_capacity: "Nearby legal parking capacity",
  dist_to_metro_m: "Near metro station — high footfall",
  dist_to_commercial_m: "Near commercial/market area",
  event_impact_score: "Nearby event causing extra traffic",
  distance_to_active_event_m: "Distance to active event",
  active_event_count: "Number of nearby events",
  rainfall_mm: "Rainfall amount",
  is_raining: "Rain — drivers park under shelter",
  rain_shelter_bottleneck: "Rain + bridge/underpass = bottleneck",
  is_underpass_or_bridge: "Bridge or underpass structure",
  road_width_m: "Road width",
  segment_total_events: "Historical violation count at this spot",
  segment_event_rate: "How frequently violations happen here",
  segment_rank_pct: "This road's violation rank vs city",
  lag_1h_total: "Violations in the last hour",
  lag_2h_total: "Violations 2 hours ago",
  lag_3h_total: "Violations 3 hours ago",
  lag_24h_total: "Same time yesterday",
  lag_168h_total: "Same time last week",
  road_class: "Type of road",
  segment_id: "Specific road segment",
  police_station: "Jurisdiction area",
  junction_bucket: "Junction type",
  hour_bucket: "Time period of day",
};

function getFeatureLabel(feature: string, impact: number): string {
  const label = FEATURE_LABELS[feature] || feature.replace(/_/g, " ");
  const pct = Math.abs(impact * 100).toFixed(0);
  return impact > 0 ? `${label} (+${pct}%)` : `${label} (-${pct}%)`;
}

function getRiskLabel(eps: number): { text: string; color: string; emoji: string } {
  if (eps >= 80) return { text: "Urgent", color: "text-red-500", emoji: "🔴" };
  if (eps >= 60) return { text: "High", color: "text-orange-500", emoji: "🟠" };
  if (eps >= 40) return { text: "Moderate", color: "text-yellow-500", emoji: "🟡" };
  return { text: "Low", color: "text-zinc-400", emoji: "⚪" };
}

export default function PhysicsInspector() {
  const { 
    selectedEdge, setSelectedEdge, isSimulatingResolution, setIsSimulatingResolution, 
    geoData, isSimulationActive, setIsSimulationActive,
    resolutionImpact, setResolutionImpact, nearestStation, setNearestStation 
  } = useMapStore();
  const [shapData, setShapData] = useState<any>(null);
  const [dispatchConfirm, setDispatchConfirm] = useState(false);
  const [loadingImpact, setLoadingImpact] = useState(false);

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
      setIsSimulationActive(false);
      setResolutionImpact(null);

      // Fetch AI explanation
      fetch(`/api/explain?segment_id=${selectedEdge.segment_id}`)
        .then(r => r.json())
        .then(d => { if (d.data) setShapData(d.data); })
        .catch(console.error);

      // Fetch nearest station
      fetch(`/api/nearest_station?segment_id=${selectedEdge.segment_id}`)
        .then(r => r.json())
        .then(d => setNearestStation(d))
        .catch(console.error);
    }
  }, [selectedEdge, setIsSimulationActive, setResolutionImpact, setNearestStation]);

  const analysis = useMemo(() => {
    if (!selectedEdge) return null;
    let eps: number = selectedEdge.eps ?? 0;
    const roadWidth: number = selectedEdge.road_width_m ?? 6.0;
    
    let dominantVehicle = "car";
    let maxCount = 0;
    for (const [vClass] of Object.entries(VEHICLE_WIDTHS)) {
      const val = parseFloat(selectedEdge[`count_${vClass}`] ?? 0);
      if (val > maxCount) { maxCount = val; dominantVehicle = vClass; }
    }
    const vehicleWidth = VEHICLE_WIDTHS[dominantVehicle] ?? 1.9;
    
    const roadClassVolumes: Record<string, number> = {
      trunk: 5000, primary: 3000, secondary: 1500, tertiary: 500, residential: 200,
    };
    const rClass = selectedEdge.road_class?.toLowerCase() || 'tertiary';
    const estTrafficVolume = roadClassVolumes[rClass] || 500;

    let totalBlockWidth = vehicleWidth;
    let chokePercent = (totalBlockWidth / roadWidth) * 100;
    let speedReductionPercent = Math.min(95, (chokePercent * 1.2) + (eps * 0.3));
    let economicBleed = (speedReductionPercent / 100) * estTrafficVolume * 50;

    // Use real data from backend if available
    if (isSimulationActive && resolutionImpact) {
      return {
        eps: 0,
        roadWidth,
        totalBlockWidth: 0,
        chokePercent: 0,
        speedReductionPercent: 0,
        economicBleed: 0,
        dominantVehicle,
        clearance: roadWidth,
        speedBefore: resolutionImpact.impact?.before?.speed_kmh ?? 15,
        speedAfter: resolutionImpact.impact?.after?.speed_kmh ?? 35,
        savingsPerHr: resolutionImpact.impact?.improvement?.economic_savings_per_hr ?? 0,
        cascadeSegments: resolutionImpact.impact?.improvement?.cascade_segments_helped ?? 0,
        lanesRestored: resolutionImpact.impact?.improvement?.lanes_restored ?? 0,
      };
    }

    return { 
      eps, roadWidth, totalBlockWidth, chokePercent, speedReductionPercent,
      economicBleed, dominantVehicle,
      clearance: Math.max(0, roadWidth - totalBlockWidth),
      speedBefore: null, speedAfter: null, savingsPerHr: null, cascadeSegments: null, lanesRestored: null,
    };
  }, [selectedEdge, isSimulationActive, resolutionImpact]);

  const handleSimulate = async () => {
    if (isSimulationActive) {
      setIsSimulationActive(false);
      setResolutionImpact(null);
      return;
    }

    setLoadingImpact(true);
    try {
      const res = await fetch(`/api/resolve_impact?segment_id=${selectedEdge.segment_id}`);
      const data = await res.json();
      setResolutionImpact(data);
      setIsSimulationActive(true);
    } catch (e) {
      console.error("Failed to load resolution impact:", e);
      setIsSimulationActive(true); // fallback to simple mode
    } finally {
      setLoadingImpact(false);
    }
  };

  const handleDispatch = () => {
    setIsSimulatingResolution(true);
    setTimeout(() => {
      setIsSimulatingResolution(false);
      setSelectedEdge(null);
    }, 4000);
  };

  const risk = getRiskLabel(analysis?.eps ?? 0);

  return (
    <AnimatePresence>
      {selectedEdge && analysis && (
        <motion.div
          key="road-details"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 20 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          className="absolute top-24 right-4 w-[400px] z-30 flex flex-col rounded-2xl glass-panel overflow-hidden"
        >
          {/* Header — Road Name + Risk Level */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/5 bg-black/20">
            <div>
              <h3 className="text-white text-[15px] font-heading font-bold flex items-center gap-2 mb-1.5">
                <Crosshair className="w-4 h-4 text-[#3b82f6] drop-shadow-[0_0_8px_rgba(59,130,246,0.8)]" />
                {selectedEdge.road_name || selectedEdge.junction_name || "Unknown Road"}
              </h3>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 bg-black/40 px-2.5 py-1 rounded-md border border-white/5">
                  <span className="text-sm">{risk.emoji}</span>
                  <span className={`text-[11px] font-bold ${risk.color}`}>
                    {risk.text}
                  </span>
                  <span className="text-[10px] font-mono text-zinc-500">
                    {Math.round(analysis.eps)}/100
                  </span>
                </div>
                {nearestStation && (
                  <div className="flex items-center gap-1.5 bg-black/40 px-2 py-1 rounded-md border border-white/5">
                    <MapPin className="w-3 h-3 text-blue-400" />
                    <span className="text-[10px] text-zinc-300">{nearestStation.station_name}</span>
                    <span className="text-[10px] text-blue-400 font-bold">~{nearestStation.eta_minutes} min</span>
                  </div>
                )}
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
            {/* Revenue Loss Card */}
            <div className="p-4 rounded-xl border border-white/5 bg-black/40 relative overflow-hidden group shadow-inner">
              <div className="absolute inset-0 bg-gradient-to-r from-rose-600/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="flex items-center justify-between mb-3 relative z-10">
                <p className="text-[10px] text-zinc-400 font-mono uppercase tracking-widest">
                  Revenue Loss Per Hour
                </p>
              </div>
              <div className="relative z-10 mb-4">
                <AnimatePresence mode="popLayout">
                  <motion.span 
                    key={isSimulationActive ? 'resolved' : 'active'}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                    className={`text-[28px] font-black font-mono leading-none tracking-tighter ${isSimulationActive ? 'text-emerald-500' : 'text-[#ef4444]'}`}
                  >
                    ₹{analysis.economicBleed.toLocaleString(undefined, { maximumFractionDigits: 0 })} <span className="text-sm text-zinc-500 font-normal">/ hr</span>
                  </motion.span>
                </AnimatePresence>
              </div>

              {/* Before/After Comparison (shows when simulation active) */}
              <AnimatePresence>
                {isSimulationActive && resolutionImpact && (
                  <motion.div 
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="mb-4 relative z-10 space-y-2"
                  >
                    <div className="flex items-center gap-2 text-xs">
                      <div className="flex-1 bg-red-500/10 border border-red-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-red-400 uppercase tracking-wider mb-1">Before</div>
                        <div className="text-red-400 font-bold">{resolutionImpact.impact?.before?.speed_kmh ?? '?'} km/h</div>
                      </div>
                      <ArrowRight className="w-4 h-4 text-emerald-400 animate-pulse" />
                      <div className="flex-1 bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-emerald-400 uppercase tracking-wider mb-1">After</div>
                        <div className="text-emerald-400 font-bold">{resolutionImpact.impact?.after?.speed_kmh ?? '?'} km/h</div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <div className="flex-1 bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-emerald-400 uppercase tracking-wider mb-0.5">Savings</div>
                        <div className="text-emerald-400 font-bold text-sm">₹{(resolutionImpact.impact?.improvement?.economic_savings_per_hr ?? 0).toLocaleString()}</div>
                      </div>
                      <div className="flex-1 bg-blue-500/10 border border-blue-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-blue-400 uppercase tracking-wider mb-0.5">Nearby roads helped</div>
                        <div className="text-blue-400 font-bold text-sm">{resolutionImpact.impact?.improvement?.cascade_segments_helped ?? 0}</div>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <button 
                onClick={handleSimulate}
                disabled={loadingImpact}
                className={`w-full relative z-10 text-[11px] font-bold py-2.5 rounded-[6px] uppercase tracking-wider transition-colors ${
                  loadingImpact 
                    ? 'bg-zinc-800 text-zinc-500 cursor-wait'
                    : isSimulationActive 
                    ? 'bg-zinc-800 text-zinc-300 hover:bg-zinc-700 border border-white/5' 
                    : 'bg-[#3b82f6]/20 text-[#3b82f6] border border-[#3b82f6]/30 hover:bg-[#3b82f6]/30'
                }`}
              >
                {loadingImpact ? 'Computing...' : isSimulationActive ? 'Reset' : 'What if we clear this?'}
              </button>
            </div>

            {/* 2D Road Cross-Section Diagram */}
            <div className="relative h-32 bg-[#0B0F1A] rounded-xl border border-white/5 shadow-inner overflow-hidden flex flex-col justify-center px-6">
              <p className="absolute top-3 left-4 text-[9px] font-mono text-zinc-500 uppercase tracking-widest">Road Cross-Section</p>
              
              <div className="relative w-full h-12 mt-4 bg-zinc-900 border-y border-zinc-700 flex items-center">
                <div className="absolute inset-0 flex items-center justify-center">
                   <div className="w-full border-t-2 border-dashed border-zinc-600/50" />
                </div>

                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${100 - analysis.chokePercent}%` }}
                  className="h-full bg-[#22c55e]/20 border-y-2 border-[#22c55e]/50 flex items-center justify-center relative"
                >
                  <span className="text-[10px] font-mono font-bold text-[#22c55e]">{analysis.clearance.toFixed(1)}m clear</span>
                </motion.div>

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

            {/* Stat Chips — field-friendly labels */}
            <div className="flex items-center gap-2 text-sm">
              <div className="flex-1 bg-black/40 border border-white/5 rounded-lg p-2.5 flex flex-col">
                <span className="text-[10px] text-zinc-500 font-mono flex items-center gap-1.5 uppercase mb-1">
                  <Ruler className="w-3 h-3" /> Road Width
                </span>
                <span className="text-zinc-200 font-mono font-bold text-xs">{analysis.roadWidth}m</span>
              </div>
              <div className="flex-1 bg-black/40 border border-white/5 rounded-lg p-2.5 flex flex-col relative overflow-hidden">
                <div className={`absolute inset-0 opacity-10 ${analysis.chokePercent > 50 ? 'bg-[#ef4444]' : analysis.chokePercent > 25 ? 'bg-[#f97316]' : 'bg-zinc-500'}`} />
                <span className="text-[10px] text-zinc-500 font-mono flex items-center gap-1.5 uppercase mb-1 relative z-10">
                  <Activity className="w-3 h-3" /> Blocked
                </span>
                <span className={`font-mono font-bold text-xs relative z-10 ${analysis.chokePercent > 50 ? 'text-[#ef4444]' : analysis.chokePercent > 25 ? 'text-[#f97316]' : 'text-zinc-200'}`}>
                  {analysis.chokePercent.toFixed(0)}%
                </span>
              </div>
              <div className="flex-1 bg-black/40 border border-white/5 rounded-lg p-2.5 flex flex-col">
                <span className="text-[10px] text-zinc-500 font-mono flex items-center gap-1.5 uppercase mb-1">
                  <Navigation className="w-3 h-3" /> Passable
                </span>
                <span className="text-[#22c55e] font-mono font-bold text-xs">{analysis.clearance.toFixed(1)}m</span>
              </div>
            </div>

            {/* Why This Alert? — replaces "AI Inference Drivers" */}
            <div>
              <p className="text-[10px] text-zinc-400 font-mono uppercase tracking-widest mb-3 flex items-center gap-2">
                <Brain className="w-3 h-3 text-indigo-400" /> Why This Alert?
              </p>
              <div className="bg-black/40 rounded-xl p-4 border border-white/5 space-y-4 shadow-inner">
                {shapData ? (
                  <>
                    {[...(shapData.top_positive_contributors || []), ...(shapData.top_negative_contributors || [])]
                      .sort((a: any, b: any) => Math.abs(b.impact) - Math.abs(a.impact))
                      .slice(0, 4)
                      .map((c: any, i: number) => {
                        const width = Math.min(100, Math.max(10, Math.abs(c.impact) * 100));
                        const label = getFeatureLabel(c.feature, c.impact);
                        const parts = label.split(/(\([^)]+\))/);
                        return (
                          <div key={i} className="flex flex-col gap-1.5">
                            <div className="flex justify-between text-[10px] font-mono text-zinc-300">
                              <span>{parts[0]?.trim()}</span>
                              <span className={`font-bold ${c.impact > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>{parts[1] || ''}</span>
                            </div>
                            <div className="w-full h-1 bg-zinc-800 rounded-full overflow-hidden">
                              <motion.div 
                                initial={{ width: 0 }}
                                animate={{ width: `${width}%` }}
                                className={`h-full rounded-full shadow-[0_0_8px_currentcolor] ${c.impact > 0 ? 'bg-rose-500' : 'bg-emerald-500'}`}
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
                          <div className="h-full bg-zinc-700 animate-pulse" style={{ width: `${w}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Dispatch Button — "Send Team" instead of "Dispatch tow unit" */}
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
                  <span className="text-xs tracking-wider">Team Dispatched ✓</span>
                </>
              ) : dispatchConfirm ? (
                <>
                  <Timer className="w-4 h-4 animate-pulse" />
                  <span className="text-[13px]">Confirm? (3s)</span>
                </>
              ) : (
                <>
                  <ShieldAlert className="w-4 h-4" />
                  <span className="text-[13px]">Send Team</span>
                </>
              )}
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
