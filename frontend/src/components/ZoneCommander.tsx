"use client";

import React from "react";
import { useMapStore } from "@/store/useMapStore";
import { AlertTriangle, Car, IndianRupee, MapPin, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export default function ZoneCommander() {
  const { selectedHeatmapZone, setSelectedHeatmapZone } = useMapStore();

  return (
    <AnimatePresence>
      {selectedHeatmapZone && (
        <motion.div
          initial={{ x: 400, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 400, opacity: 0 }}
          className="absolute top-24 right-6 w-96 bg-slate-900/90 backdrop-blur-xl border border-rose-500/30 rounded-xl shadow-[0_0_40px_rgba(225,29,72,0.2)] overflow-hidden z-50 flex flex-col"
        >
          <div className="p-4 border-b border-rose-500/20 bg-rose-500/10 flex justify-between items-start">
            <div>
              <div className="flex items-center gap-2 text-rose-500 mb-1">
                <AlertTriangle className="w-5 h-5" />
                <h2 className="text-sm font-bold tracking-widest uppercase">Zone Commander</h2>
              </div>
              <p className="text-slate-300 text-xs">Critical Heatmap Blob Selected</p>
            </div>
            <button onClick={() => setSelectedHeatmapZone(null)} className="text-slate-400 hover:text-white transition-colors">
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="p-6 space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-800/50 p-4 rounded-lg border border-slate-700/50">
                <div className="text-slate-400 text-[10px] uppercase tracking-widest mb-1 flex items-center gap-2">
                  <AlertTriangle className="w-3 h-3 text-rose-400" />
                  Choked Roads
                </div>
                <div className="text-2xl font-bold text-white">{selectedHeatmapZone.totalSegments}</div>
              </div>
              
              <div className="bg-slate-800/50 p-4 rounded-lg border border-slate-700/50">
                <div className="text-slate-400 text-[10px] uppercase tracking-widest mb-1 flex items-center gap-2">
                  <Car className="w-3 h-3 text-yellow-400" />
                  Est. Vehicles
                </div>
                <div className="text-2xl font-bold text-white">{selectedHeatmapZone.totalVehicles}</div>
              </div>
            </div>

            <div className="bg-slate-800/50 p-4 rounded-lg border border-rose-500/30 shadow-[inset_0_0_20px_rgba(225,29,72,0.1)]">
              <div className="text-rose-400 text-[10px] uppercase tracking-widest mb-1 flex items-center gap-2">
                <IndianRupee className="w-3 h-3" />
                Total Economic Bleed
              </div>
              <div className="text-3xl font-black text-rose-500 flex items-baseline gap-1">
                ₹{((selectedHeatmapZone.totalEconomicLoss || 0) / 100000).toFixed(1)}L <span className="text-sm font-medium text-rose-400/70">/ hr</span>
              </div>
            </div>

            {selectedHeatmapZone.stagingArea && (
              <div className="bg-emerald-500/10 p-4 rounded-lg border border-emerald-500/30">
                <div className="text-emerald-400 text-[10px] uppercase tracking-widest mb-2 flex items-center gap-2">
                  <MapPin className="w-3 h-3" />
                  Recommended Staging Area
                </div>
                <div className="text-sm text-emerald-100 font-mono">
                  {selectedHeatmapZone.stagingArea[1].toFixed(4)}, {selectedHeatmapZone.stagingArea[0].toFixed(4)}
                </div>
                <p className="text-emerald-400/70 text-xs mt-1">Deploy squad outside the blast radius to avoid getting stuck.</p>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
