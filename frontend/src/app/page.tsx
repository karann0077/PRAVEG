"use client";

import React, { useEffect, useState } from "react";
import TacticalMap from "@/components/TacticalMap";
import DispatchQueue from "@/components/DispatchQueue";
import PhysicsInspector from "@/components/PhysicsInspector";
import TimeScrubber from "@/components/TimeScrubber";
import { useMapStore } from "@/store/useMapStore";
import { ShieldAlert, Wifi, Brain, Database, Layers, Map as MapIcon, RotateCcw } from "lucide-react";

function MapControls() {
  const { mapStyle, setMapStyle, viewState, setViewState } = useMapStore();

  const toggle3D = () => {
    setViewState({ ...viewState, pitch: viewState.pitch > 0 ? 0 : 45, bearing: viewState.pitch > 0 ? 0 : viewState.bearing });
  };

  const resetNorth = () => {
    setViewState({ ...viewState, pitch: 0, bearing: 0 });
  };

  return (
    <div className="absolute bottom-36 right-4 z-30 flex flex-col gap-2">
      {/* Satellite / Dark toggle */}
      <button
        onClick={() => setMapStyle(mapStyle === "dark" ? "satellite" : "dark")}
        className="group w-10 h-10 flex items-center justify-center rounded-xl border border-slate-700/60 hover:border-slate-500 transition-all"
        style={{ background: "rgba(8,15,30,0.92)", backdropFilter: "blur(16px)" }}
        title={mapStyle === "dark" ? "Switch to Satellite" : "Switch to Dark Map"}
      >
        {mapStyle === "dark" ? (
          <Layers className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
        ) : (
          <MapIcon className="w-4 h-4 text-cyan-400 group-hover:text-white transition-colors" />
        )}
      </button>

      {/* 3D tilt toggle */}
      <button
        onClick={toggle3D}
        className={`group w-10 h-10 flex items-center justify-center rounded-xl border transition-all font-mono text-xs font-bold ${
          viewState.pitch > 0
            ? "border-cyan-500/60 text-cyan-400"
            : "border-slate-700/60 text-slate-400 hover:border-slate-500 hover:text-white"
        }`}
        style={{ background: "rgba(8,15,30,0.92)", backdropFilter: "blur(16px)" }}
        title="Toggle 3D Tilt"
      >
        {viewState.pitch > 0 ? "2D" : "3D"}
      </button>

      {/* Reset north */}
      <button
        onClick={resetNorth}
        className="group w-10 h-10 flex items-center justify-center rounded-xl border border-slate-700/60 hover:border-slate-500 transition-all"
        style={{ background: "rgba(8,15,30,0.92)", backdropFilter: "blur(16px)" }}
        title="Reset to North"
      >
        <RotateCcw className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
      </button>
    </div>
  );
}

function TrafficLegend() {
  return (
    <div
      className="absolute bottom-36 right-16 z-30 rounded-xl border border-slate-700/40 px-3.5 py-3 text-[10px] font-mono"
      style={{ background: "rgba(8,15,30,0.90)", backdropFilter: "blur(20px)" }}
    >
      <p className="text-slate-500 uppercase tracking-widest mb-2 text-[9px]">Traffic Impact</p>
      <div className="space-y-1.5">
        {[
          { color: "bg-red-600 shadow-[0_0_8px_rgba(220,38,38,0.8)]", label: "Critical (≥90)" },
          { color: "bg-orange-500", label: "High (≥70)" },
          { color: "bg-orange-400", label: "Medium (≥50)" },
          { color: "bg-yellow-400", label: "Watchlist (≥30)" },
          { color: "bg-green-500", label: "Clear (<30)" },
        ].map(({ color, label }) => (
          <div key={label} className="flex items-center gap-2">
            <div className={`w-7 h-2 rounded-full ${color}`} />
            <span className="text-slate-400">{label}</span>
          </div>
        ))}
      </div>
      <p className="text-slate-700 text-[8px] mt-2 border-t border-slate-800 pt-1.5">
        Right-drag → Tilt map
      </p>
    </div>
  );
}

export default function Home() {
  const [time, setTime] = useState("");

  useEffect(() => {
    const update = () =>
      setTime(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <main className="relative w-full h-screen overflow-hidden bg-[#060d1a] font-sans select-none">
      {/* Full-screen map — the app */}
      <TacticalMap />

      {/* TOP NAV BAR */}
      <div
        className="absolute top-0 left-0 w-full h-16 z-20 flex items-center justify-between px-5 pointer-events-none"
        style={{
          background: "linear-gradient(to bottom, rgba(6,13,26,0.97) 0%, rgba(6,13,26,0.5) 80%, transparent 100%)",
        }}
      >
        <div className="flex items-center gap-3 pointer-events-auto">
          <div
            className="p-2 rounded-xl border border-rose-500/40"
            style={{ background: "rgba(225,29,72,0.15)", boxShadow: "0 0 14px rgba(225,29,72,0.25)" }}
          >
            <ShieldAlert className="w-4 h-4 text-rose-500" />
          </div>
          <div>
            <h1 className="text-white text-sm font-black tracking-widest uppercase leading-tight">
              Bengaluru AI Traffic Command
            </h1>
            <p className="text-slate-500 text-[9px] font-mono uppercase tracking-widest">
              Spatiotemporal Enforcement Engine · OSM Road-Matched
            </p>
          </div>
        </div>

        <div className="hidden md:flex items-center gap-5 pointer-events-auto">
          <div className="flex items-center gap-1.5">
            <Brain className="w-3 h-3 text-purple-400" />
            <span className="text-purple-400 text-[10px] font-mono">LightGBM Active</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Wifi className="w-3 h-3 text-cyan-400" />
            <span className="text-cyan-400 text-[10px] font-mono">MapmyIndia API</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Database className="w-3 h-3 text-emerald-400" />
            <span className="text-emerald-400 text-[10px] font-mono">298K Events · 3127 Segments</span>
          </div>
          <div
            className="px-2.5 py-1 rounded-lg border border-slate-800 text-slate-400 text-[10px] font-mono tabular-nums"
            style={{ background: "rgba(15,23,42,0.85)" }}
          >
            {time}
          </div>
        </div>
      </div>

      {/* LEFT: Slide-in Drawer */}
      <DispatchQueue />

      {/* BOTTOM RIGHT: Physics Inspector */}
      <PhysicsInspector />

      {/* BOTTOM CENTER: Time Scrubber */}
      <TimeScrubber />

      {/* RIGHT: Map controls + Legend */}
      <MapControls />
      <TrafficLegend />

      {/* Scanline overlay */}
      <div
        className="absolute inset-0 pointer-events-none z-50 opacity-[0.025]"
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,1) 2px, rgba(255,255,255,1) 3px)",
        }}
      />
    </main>
  );
}
