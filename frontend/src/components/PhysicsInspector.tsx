"use client";

import React, { useMemo, useState, useEffect } from "react";
import { useMapStore } from "@/store/useMapStore";
import { motion, AnimatePresence } from "framer-motion";
import { X, ShieldAlert, Crosshair, Brain, MapPin, ArrowRight, Route, AlertCircle, Timer, ChevronLeft, ChevronRight } from "lucide-react";

const VEHICLE_WIDTHS: Record<string, number> = {
  heavy: 2.6,
  light_commercial: 2.3,
  car: 1.9,
  auto: 1.3,
  two_wheeler: 0.8,
  other: 1.9,
};

const FEATURE_LABELS: Record<string, string> = {
  segment_hour_mean: "This road often has illegal parking at this hour.",
  segment_dow_hour_mean: "This road often has illegal parking at this hour.",
  city_hour_mean: "City-wide parking violations are high at this hour.",
  city_dow_hour_mean: "City-wide parking violations are high at this hour.",
  is_peak: "It is currently a busy traffic period.",
  is_weekday_peak: "It is currently a busy weekday traffic period.",
  is_weekend_peak: "It is currently a busy weekend traffic period.",
  hour: "Time of day patterns show high risk.",
  hour_sin: "Time of day patterns show high risk.",
  hour_cos: "Time of day patterns show high risk.",
  day_of_week: "Day of the week patterns show high risk.",
  dow_sin: "Day of the week patterns show high risk.",
  dow_cos: "Day of the week patterns show high risk.",
  is_weekend: "Weekend parking patterns show high risk.",
  month: "Seasonal patterns show high risk.",
  month_sin: "Seasonal patterns show high risk.",
  month_cos: "Seasonal patterns show high risk.",
  overflow_risk_index: "There is no legal parking nearby, making illegal parking likely.",
  dist_to_legal_parking_m: "Legal parking is far away from this area.",
  legal_parking_capacity: "Nearby legal parking capacity is very low.",
  dist_to_metro_m: "High footfall from a nearby metro station.",
  dist_to_commercial_m: "High activity from nearby commercial areas.",
  event_impact_score: "A nearby event is causing extra traffic.",
  distance_to_active_event_m: "A nearby event is causing extra traffic.",
  active_event_count: "Nearby events are causing extra traffic.",
  rainfall_mm: "Rainfall usually increases parking under shelters.",
  is_raining: "Drivers tend to park under shelters when it rains.",
  rain_shelter_bottleneck: "Parked vehicles under a bridge or underpass are causing a bottleneck.",
  is_underpass_or_bridge: "This structure creates a natural parking shelter.",
  road_width_m: "The road is narrow, so parked vehicles quickly block movement.",
  segment_total_events: "This specific road has a strong history of parking violations.",
  segment_event_rate: "Violations happen frequently at this location.",
  segment_rank_pct: "This road ranks very high in the city for violations.",
  lag_1h_total: "Violations occurred here within the last hour.",
  lag_2h_total: "Violations occurred here recently.",
  lag_3h_total: "Violations occurred here recently.",
  lag_24h_total: "Violations happened here at this exact time yesterday.",
  lag_168h_total: "Violations happened here at this exact time last week.",
  road_class: "This road type often experiences blockages.",
  segment_id: "This specific segment is prone to issues.",
  police_station: "This jurisdiction area has active patterns.",
  junction_bucket: "Nearby junction traffic is already affected.",
  hour_bucket: "This time period usually sees high violation rates.",
  poi_gravity_score: "A high concentration of points of interest (markets, schools) attracts parking.",
  road_network_degree: "This is a complex intersection with high connectivity.",
  is_holiday: "Public holiday patterns increase parking risk here.",
  is_festival: "Festival period traffic increases parking risk here.",
  is_school_pickup: "School pickup hour rush is causing congestion.",
  is_lunch_market: "Lunch or market rush hour is causing congestion.",
  is_nightlife: "Nightlife and entertainment activities are causing congestion.",
  is_first_week_of_month: "First week of the month patterns show higher activity.",
  rolling_7d_mean: "This road had consistent violations over the past 7 days.",
  rolling_28d_mean: "This road has a persistent violation trend this month.",
  neighbor_ring_1_violation_sum: "Clearing this road may reduce spillover to nearby roads.",
  station_enforcement_volume: "The local station often enforces violations in this area.",
  segment_historical_severity_mean: "Violations here are historically severe.",
};

export default function PhysicsInspector() {
  const { 
    selectedEdge, setSelectedEdge, isSimulatingResolution, setIsSimulatingResolution, 
    isSimulationActive, setIsSimulationActive, isBuildingRoute, setIsBuildingRoute,
    resolutionImpact, setResolutionImpact, nearestStation, setNearestStation,
    patrolRouteGeometry, setPatrolRouteGeometry
  } = useMapStore();
  const [shapData, setShapData] = useState<any>(null);
  const [impactData, setImpactData] = useState<any>(null);
  const [dispatchConfirm, setDispatchConfirm] = useState(false);
  const [loadingImpact, setLoadingImpact] = useState(false);
  const [actionState, setActionState] = useState<"Not sent" | "Team Sent" | "Cleared">("Not sent");
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (dispatchConfirm) {
      timer = setTimeout(() => setDispatchConfirm(false), 3000);
    }
    return () => clearTimeout(timer);
  }, [dispatchConfirm]);

  useEffect(() => {
    if (selectedEdge) {
      setShapData(null);
      setImpactData(null);
      setIsSimulationActive(false);
      setIsBuildingRoute(false);
      setResolutionImpact(null);
      setActionState("Not sent");

      const p = selectedEdge.properties || selectedEdge;

      fetch(`/api/explain?segment_id=${p.segment_id}`)
        .then(r => r.json())
        .then(d => { if (d.data) setShapData(d.data); })
        .catch(console.error);
        
      fetch(`/api/resolve_impact?segment_id=${p.segment_id}`)
        .then(r => r.json())
        .then(setImpactData)
        .catch(console.error);

      fetch(`/api/nearest_station?segment_id=${p.segment_id}`)
        .then(r => r.json())
        .then(d => setNearestStation(d))
        .catch(console.error);
    }
  }, [selectedEdge, setIsSimulationActive, setResolutionImpact, setNearestStation, setPatrolRouteGeometry, setIsBuildingRoute]);

  useEffect(() => {
    if (isBuildingRoute && nearestStation?.station_location && selectedEdge) {
      const startLon = nearestStation.station_location.lon;
      const startLat = nearestStation.station_location.lat;
      const coords = selectedEdge.geometry?.coordinates;
      let targetCoord = coords && coords[0];
      if (Array.isArray(targetCoord) && Array.isArray(targetCoord[0])) {
         targetCoord = targetCoord[0];
      }
      if (targetCoord) {
         fetch(`https://router.project-osrm.org/route/v1/driving/${startLon},${startLat};${targetCoord[0]},${targetCoord[1]}?geometries=geojson`)
           .then(r => r.json())
           .then(data => {
             if (data.routes && data.routes[0]) {
               setPatrolRouteGeometry(data.routes[0].geometry.coordinates);
             }
           })
           .catch(err => {
             console.error("OSRM Route error:", err);
           });
      }
    } else {
      setPatrolRouteGeometry(null);
    }
  }, [isBuildingRoute, nearestStation, selectedEdge, setPatrolRouteGeometry]);

  const details = useMemo(() => {
    if (!selectedEdge) return null;
    const p = selectedEdge.properties || selectedEdge;

    // 1. Priority Level & Score
    const score = parseFloat(p.eps || 0);
    const priorityLevel = 
      score >= 80 ? 'Critical' :
      score >= 60 ? 'High' :
      score >= 40 ? 'Watch' : 'Clear';
    
    const priorityColor = 
      score >= 80 ? 'text-[#ef4444]' :
      score >= 60 ? 'text-[#f97316]' :
      score >= 40 ? 'text-[#eab308]' : 'text-zinc-400';

    const priorityBg = 
      score >= 80 ? 'bg-[#ef4444]/20 border-[#ef4444]/30' :
      score >= 60 ? 'bg-[#f97316]/20 border-[#f97316]/30' :
      score >= 40 ? 'bg-[#eab308]/20 border-[#eab308]/30' : 'bg-zinc-800 border-zinc-700';
    
    // 2. Road Blockage Summary
    const estimatedVehicles = Math.round(parseFloat(p.predicted_total || 0));
    const roadWidthM = parseFloat(p.road_width_m || 6.0);
    
    let dominantVehicle = "car";
    let maxCount = 0;
    for (const [vClass] of Object.entries(VEHICLE_WIDTHS)) {
      const val = parseFloat(p[`count_${vClass}`] ?? 0);
      if (val > maxCount) { maxCount = val; dominantVehicle = vClass; }
    }
    const vehicleWidth = VEHICLE_WIDTHS[dominantVehicle] ?? 1.9;
    
    const chokePercent = Math.min(100, (vehicleWidth / roadWidthM) * 100);
    const clearWidthM = Math.max(0, roadWidthM - vehicleWidth);

    // 3. Traffic Status
    const multiplier = parseFloat(p.live_congestion_multiplier || 1.0);
    const trafficStatus = 
      multiplier > 1.2 ? 'Heavy traffic now' :
      multiplier > 1.05 ? 'Slow traffic now' : 'Free flow traffic';

    // 4. Action
    const action = p.recommended_action || "Monitor";
    const recommendedAction = 
      action.includes("Immediate") ? "Send team now" :
      action.includes("Preventative") ? "Preventive patrol" : "Monitor only";

    // 5. Why this alert (Wait for SHAP data)
    let whyThisAlert: string[] = [];
    if (shapData) {
      const all = [...(shapData.top_positive_contributors || []), ...(shapData.top_negative_contributors || [])]
        .filter((c: any) => c.impact > 0.05) // only meaningful contributors
        .sort((a: any, b: any) => Math.abs(b.impact) - Math.abs(a.impact))
        .slice(0, 3);
      whyThisAlert = all.map((c: any) => FEATURE_LABELS[c.feature] || "Historical patterns indicate high risk of violation here.");
      if (whyThisAlert.length === 0) {
        whyThisAlert = ["This road is ranked due to repeated illegal parking patterns at this time."];
      }
    }

    // 6. Impact Simulation
    let beforeSpeedKmph: string | number = "Live speed unavailable";
    let afterSpeedKmph: string | number = "?";
    let nearbyRoadsHelped = 0;
    let estimatedDelaySaved = "Impact estimate unavailable";
    
    if (isSimulationActive && resolutionImpact) {
       beforeSpeedKmph = resolutionImpact.impact?.before?.speed_kmh ?? "Live speed unavailable";
       afterSpeedKmph = resolutionImpact.impact?.after?.speed_kmh ?? "?";
       nearbyRoadsHelped = resolutionImpact.impact?.improvement?.cascade_segments_helped ?? 0;
       estimatedDelaySaved = "₹" + (resolutionImpact.impact?.improvement?.economic_savings_per_hr ?? 0).toLocaleString();
    } else {
       // if not active, we still don't want ? appearing
       estimatedDelaySaved = "Impact estimate unavailable";
    }

    return {
      roadName: p.road_name || (p.junction_name !== "No Junction" ? p.junction_name : null) || "Unknown Road",
      stationName: p.police_station || "Unknown",
      priorityLevel,
      priorityColor,
      priorityBg,
      priorityScore: score,
      estimatedVehicles,
      roadWidthM,
      blockedPercent: chokePercent,
      clearWidthM,
      etaText: nearestStation ? `~${nearestStation.eta_minutes} min ETA` : "Route not calculated",
      trafficStatus,
      recommendedAction,
      whyThisAlert,
      beforeSpeedKmph,
      afterSpeedKmph,
      nearbyRoadsHelped,
      estimatedDelaySaved,
      economicLossInr: p.economic_loss_inr ? `₹${p.economic_loss_inr.toLocaleString()}/hr` : 'Calculating...',
      mainReason: "Illegal parking is likely reducing usable road width during a busy traffic period.",
    };
  }, [selectedEdge, shapData, nearestStation, isSimulationActive, resolutionImpact]);

  const handleSimulate = async () => {
    if (isSimulationActive) {
      setIsSimulationActive(false);
      setResolutionImpact(null);
      return;
    }

    setLoadingImpact(true);
    try {
      const p = selectedEdge.properties || selectedEdge;
      const res = await fetch(`/api/resolve_impact?segment_id=${p.segment_id}`);
      const data = await res.json();
      setResolutionImpact(data);
      setIsSimulationActive(true);
    } catch (e) {
      console.error("Failed to load resolution impact:", e);
      setIsSimulationActive(true); // fallback
    } finally {
      setLoadingImpact(false);
    }
  };

  const handleDispatch = () => {
    if (actionState === "Not sent") {
      setActionState("Team Sent");
    } else if (actionState === "Team Sent") {
      setActionState("Cleared");
      setTimeout(() => setSelectedEdge(null), 2000);
    }
  };

  return (
    <AnimatePresence>
      {selectedEdge && details && (
        <>
          {/* Toggle Button */}
          <motion.button
            key="inspector-toggle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, x: isCollapsed ? 0 : -436 }}
            exit={{ opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="absolute top-[200px] right-0 z-20 h-16 w-6 bg-[#0B0F1A] border-y border-l border-white/10 rounded-l-lg flex items-center justify-center hover:bg-white/5 transition-colors cursor-pointer shadow-[rgba(0,0,0,0.8)_-10px_0_20px]"
          >
            {isCollapsed ? (
              <ChevronLeft className="w-4 h-4 text-zinc-500" />
            ) : (
              <ChevronRight className="w-4 h-4 text-zinc-500" />
            )}
          </motion.button>

          <motion.div
            key="road-details"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: isCollapsed ? 450 : 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="absolute top-24 right-4 w-[420px] z-30 flex flex-col rounded-xl glass-panel overflow-hidden border border-white/10 bg-[#0B0F1A]/95 shadow-2xl"
          >
          {/* Header */}
          <div className="flex items-start justify-between px-5 py-5 border-b border-white/5 bg-black/40">
            <div className="flex-1 min-w-0 pr-4">
              <div className="flex items-center gap-2 mb-2">
                <div className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase border ${details.priorityBg} ${details.priorityColor}`}>
                  {details.priorityLevel} Priority
                </div>
                <div className="text-[11px] text-zinc-400 font-mono tracking-wide">{nearestStation ? nearestStation.station_name : `${details.stationName} Station`}</div>
              </div>
              <h3 className="text-white text-lg font-bold truncate leading-tight flex items-center gap-2">
                <Crosshair className="w-5 h-5 text-blue-500" />
                {details.roadName}
              </h3>
            </div>
            <button
              onClick={() => setSelectedEdge(null)}
              className="p-1.5 rounded-full hover:bg-zinc-800 text-zinc-400 hover:text-white transition-colors flex-shrink-0"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="p-5 overflow-y-auto custom-scrollbar max-h-[75vh] flex flex-col gap-5">
            
            {/* Recommended Action */}
            <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className="w-4 h-4 text-blue-400" />
                <span className="text-xs font-bold text-blue-400 uppercase tracking-wider">Action Required</span>
              </div>
              <p className="text-white font-medium text-[15px]">{details.recommendedAction}</p>
              <p className="text-zinc-400 text-sm mt-1">{details.mainReason}</p>
            </div>

            {/* Blockage Summary & Traffic */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-black/40 border border-white/5 rounded-lg p-3">
                <p className="text-[10px] text-zinc-500 uppercase tracking-widest mb-1">Expected Vehicles</p>
                <p className="text-zinc-200 font-bold text-lg">{details.estimatedVehicles}</p>
              </div>
              <div className="bg-black/40 border border-white/5 rounded-lg p-3">
                <p className="text-[10px] text-zinc-500 uppercase tracking-widest mb-1">Road Blockage</p>
                <p className="text-rose-400 font-bold text-lg">{details.blockedPercent.toFixed(0)}% blocked</p>
              </div>
              <div className="bg-black/40 border border-white/5 rounded-lg p-3">
                <p className="text-[10px] text-zinc-500 uppercase tracking-widest mb-1">Economic Loss</p>
                <p className="text-rose-400 font-bold text-lg">{details.economicLossInr}</p>
              </div>
              <div className="bg-black/40 border border-white/5 rounded-lg p-3 col-span-2">
                <p className="text-[10px] text-zinc-500 uppercase tracking-widest mb-2 flex items-center justify-between">
                  Traffic Flow Recovery
                  {impactData?.impact?.improvement?.speed_recovery_pct > 0 && (
                    <span className="text-emerald-400 font-bold bg-emerald-500/10 px-1.5 py-0.5 rounded">
                      +{impactData.impact.improvement.speed_recovery_pct}% Speed
                    </span>
                  )}
                </p>
                {impactData ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-rose-400">Congested: {impactData.impact.before.speed_kmh} km/h</span>
                      <span className="text-zinc-500">→</span>
                      <span className="text-emerald-400">Cleared: {impactData.impact.after.speed_kmh} km/h</span>
                    </div>
                    {/* Visual Progress Bar */}
                    <div className="relative w-full h-1.5 bg-rose-500/20 rounded-full overflow-hidden">
                      <div 
                        className="absolute left-0 top-0 bottom-0 bg-emerald-500 rounded-full transition-all duration-1000 ease-out"
                        style={{ width: `${Math.min(100, (impactData.impact.before.speed_kmh / impactData.impact.after.speed_kmh) * 100)}%` }}
                      />
                      {/* Ghost bar showing recovery potential */}
                      <div 
                        className="absolute top-0 bottom-0 bg-emerald-400/30 rounded-full transition-all duration-1000 ease-out border-r border-emerald-400 animate-pulse"
                        style={{ 
                          left: `${Math.min(100, (impactData.impact.before.speed_kmh / impactData.impact.after.speed_kmh) * 100)}%`,
                          width: `${Math.min(100, ((impactData.impact.after.speed_kmh - impactData.impact.before.speed_kmh) / impactData.impact.after.speed_kmh) * 100)}%` 
                        }}
                      />
                    </div>
                    {impactData.impact.improvement.cascade_segments_helped > 0 && (
                      <p className="text-[9px] text-zinc-400 mt-0.5 leading-tight">
                        * Clearing this unblocks <span className="text-white font-bold">{impactData.impact.improvement.cascade_segments_helped}</span> downstream segments. <span className="text-emerald-400 font-bold">+{impactData.impact.improvement.speed_recovery_kmh} km/h</span> flow restored.
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 animate-pulse">
                    <div className="h-3 bg-zinc-800/50 rounded w-full" />
                    <div className="h-1.5 bg-zinc-800/50 rounded-full w-full mt-1" />
                  </div>
                )}
              </div>
            </div>

            {/* Why This Alert? */}
            <div>
              <p className="text-[10px] text-zinc-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                <Brain className="w-3 h-3 text-indigo-400" /> Why This Alert?
              </p>
              <div className="bg-black/40 rounded-lg p-4 border border-white/5">
                {shapData ? (
                  <ul className="space-y-2.5">
                    {details.whyThisAlert.map((reason, i) => (
                      <li key={i} className="flex items-start gap-2 text-[13px] text-zinc-300">
                        <span className="text-indigo-500 mt-0.5">•</span> {reason}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="flex flex-col gap-3">
                    <div className="w-3/4 h-3 bg-zinc-800/50 rounded animate-pulse" />
                    <div className="w-5/6 h-3 bg-zinc-800/50 rounded animate-pulse" />
                    <div className="w-2/3 h-3 bg-zinc-800/50 rounded animate-pulse" />
                  </div>
                )}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex flex-col gap-2 mt-2">
              <button
                onClick={() => {
                  if (!dispatchConfirm && actionState === "Not sent") {
                    setDispatchConfirm(true);
                  } else {
                    setDispatchConfirm(false);
                    handleDispatch();
                  }
                }}
                className={`w-full py-3.5 rounded-lg flex items-center justify-center gap-2 font-bold transition-all text-sm ${
                  actionState === "Cleared"
                    ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                    : actionState === "Team Sent"
                    ? "bg-blue-500 text-white shadow-[0_0_15px_rgba(59,130,246,0.3)]"
                    : dispatchConfirm
                    ? "bg-rose-500 text-white shadow-[0_0_15px_rgba(239,68,68,0.4)]"
                    : "bg-orange-500 hover:bg-orange-600 text-white shadow-[0_0_15px_rgba(249,115,22,0.3)]"
                }`}
              >
                {actionState === "Cleared" ? (
                  <>✓ Marked Cleared</>
                ) : actionState === "Team Sent" ? (
                  <>Mark Cleared</>
                ) : dispatchConfirm ? (
                  <>
                    <Timer className="w-4 h-4 animate-pulse" /> Confirm Send Team?
                  </>
                ) : (
                  <>
                    <ShieldAlert className="w-4 h-4" /> Send Team Now
                  </>
                )}
              </button>
              
              <div className="flex gap-2">
                <button 
                  onClick={() => setIsBuildingRoute(!isBuildingRoute)}
                  className={`flex-1 py-2.5 hover:bg-zinc-700 rounded-lg text-[13px] font-medium transition-colors flex items-center justify-center gap-2 ${
                    isBuildingRoute ? "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.2)]" : "bg-zinc-800 text-zinc-300"
                  }`}
                >
                  <Route className="w-4 h-4" /> {isBuildingRoute ? "Hide Route" : "Build Patrol Route"}
                </button>
              </div>
              <p className="text-center text-[10px] text-zinc-500 font-mono mt-1">{details.etaText}</p>
            </div>

            {/* Collapsed Impact Simulation */}
            <div className="mt-2 border-t border-white/5 pt-4">
              <button 
                onClick={handleSimulate}
                disabled={loadingImpact}
                className="w-full text-left flex items-center justify-between group"
              >
                <span className="text-[11px] font-bold text-zinc-400 group-hover:text-zinc-200 uppercase tracking-wider transition-colors">
                  {loadingImpact ? 'Computing...' : isSimulationActive ? 'Hide Simulation' : 'What if we clear this?'}
                </span>
                <span className="text-zinc-500 group-hover:text-zinc-300">
                  {isSimulationActive ? '−' : '+'}
                </span>
              </button>

              <AnimatePresence>
                {isSimulationActive && resolutionImpact && (
                  <motion.div 
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="mt-4 space-y-3"
                  >
                    <div className="flex items-center gap-2 text-xs">
                      <div className="flex-1 bg-red-500/10 border border-red-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-red-400 uppercase tracking-wider mb-1">Live Speed</div>
                        <div className="text-red-400 font-bold">{details.beforeSpeedKmph}</div>
                      </div>
                      <ArrowRight className="w-4 h-4 text-emerald-400 animate-pulse" />
                      <div className="flex-1 bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-emerald-400 uppercase tracking-wider mb-1">Est. Cleared</div>
                        <div className="text-emerald-400 font-bold">{details.afterSpeedKmph} km/h</div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <div className="flex-1 bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-emerald-400 uppercase tracking-wider mb-0.5">Est. Delay Impact</div>
                        <div className="text-emerald-400 font-bold text-sm">{details.estimatedDelaySaved}</div>
                      </div>
                      <div className="flex-1 bg-blue-500/10 border border-blue-500/20 rounded-lg p-2 text-center">
                        <div className="text-[9px] text-blue-400 uppercase tracking-wider mb-0.5">Spillover Helped</div>
                        <div className="text-blue-400 font-bold text-sm">{details.nearbyRoadsHelped} roads</div>
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
            
          </div>
        </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
