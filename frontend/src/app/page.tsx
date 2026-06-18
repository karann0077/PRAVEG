"use client";

import React, { useEffect, useState } from "react";
import TacticalMap from "@/components/TacticalMap";
import DispatchQueue from "@/components/DispatchQueue";
import PhysicsInspector from "@/components/PhysicsInspector";
import TimeMachine from "@/components/TimeMachine";
import ZoneCommander from "@/components/ZoneCommander";
import { useMapStore } from "@/store/useMapStore";
import { ShieldAlert, Layers, Map as MapIcon, RotateCcw, Activity, AlignLeft, Hexagon } from "lucide-react";

function BottomPillToggles() {
  const { activeLayerMode, setActiveLayerMode } = useMapStore();
  
  const buttons = [
    { id: "tactical", label: "Tactical Lines", icon: <AlignLeft className="w-4 h-4" /> },
    { id: "heatmap", label: "Heatmap", icon: <Activity className="w-4 h-4" /> }
  ] as const;

  return (
    <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-40 flex items-center p-1 rounded-full bg-slate-800/80 backdrop-blur-md border border-slate-700 shadow-2xl">
      {buttons.map((btn) => (
        <button
          key={btn.id}
          onClick={() => setActiveLayerMode(btn.id)}
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-xs font-bold uppercase tracking-widest transition-all ${
            activeLayerMode === btn.id
              ? "bg-indigo-500 text-white shadow-[0_0_15px_rgba(99,102,241,0.5)]"
              : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
          }`}
        >
          {btn.icon}
          {btn.label}
        </button>
      ))}
    </div>
  );
}

function MapControls() {
  const { mapStyle, setMapStyle, viewState, setViewState } = useMapStore();

  const toggle3D = () => {
    setViewState({ ...viewState, pitch: viewState.pitch > 0 ? 0 : 45, bearing: viewState.pitch > 0 ? 0 : viewState.bearing });
  };

  const resetNorth = () => {
    setViewState({ ...viewState, pitch: 0, bearing: 0 });
  };

  return (
    <div className="absolute bottom-32 right-4 z-20 flex flex-col gap-2">
      <button
        onClick={() => setMapStyle(mapStyle === "dark" ? "satellite" : "dark")}
        className="group w-10 h-10 flex items-center justify-center rounded-xl border border-slate-700/60 bg-slate-800/80 backdrop-blur-md hover:border-slate-500 transition-all"
        title={mapStyle === "dark" ? "Switch to Satellite" : "Switch to Dark Map"}
      >
        {mapStyle === "dark" ? (
          <Layers className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
        ) : (
          <MapIcon className="w-4 h-4 text-cyan-400 group-hover:text-white transition-colors" />
        )}
      </button>

      <button
        onClick={toggle3D}
        className={`group w-10 h-10 flex items-center justify-center rounded-xl border bg-slate-800/80 backdrop-blur-md transition-all font-mono text-xs font-bold ${
          viewState.pitch > 0
            ? "border-indigo-500/60 text-indigo-400"
            : "border-slate-700/60 text-slate-400 hover:border-slate-500 hover:text-white"
        }`}
        title="Toggle 3D Tilt"
      >
        {viewState.pitch > 0 ? "2D" : "3D"}
      </button>

      <button
        onClick={resetNorth}
        className="group w-10 h-10 flex items-center justify-center rounded-xl border border-slate-700/60 bg-slate-800/80 backdrop-blur-md hover:border-slate-500 transition-all"
        title="Reset to North"
      >
        <RotateCcw className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
      </button>
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
    <main className="relative w-[100vw] h-[100vh] overflow-hidden bg-slate-900 font-sans select-none">
      {/* z-0 Base Map, z-10 DeckGL */}
      <TacticalMap />

      {/* LAYER 1: TOP BAR (z-40) */}
      <div className="absolute top-4 left-4 right-4 h-14 z-40 flex items-center justify-between px-6 rounded-2xl bg-slate-800/80 backdrop-blur-md border border-slate-700 shadow-xl">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-5 h-5 text-indigo-500" />
          <h1 className="text-white text-base font-black tracking-widest uppercase">
            DRISHTI COMMAND
          </h1>
        </div>

        {/* Center: Predictive Time-Scrubber */}
        <div className="flex items-center justify-center h-full">
          <TimeMachine />
          <ZoneCommander />
        </div>

        {/* Right: Global Stats */}
        <div className="flex items-center gap-6">
          <div className="flex flex-col items-end">
            <span className="text-[10px] text-slate-400 font-mono uppercase tracking-widest">Active Hotspots</span>
            <span className="text-rose-500 font-bold font-mono">142 Critical</span>
          </div>
          <div className="flex flex-col items-end border-l border-slate-700 pl-6">
            <span className="text-[10px] text-slate-400 font-mono uppercase tracking-widest">Economic Bleed</span>
            <span className="text-amber-500 font-bold font-mono">₹4.2L / hr</span>
          </div>
        </div>
      </div>

      {/* LAYER 2: LEFT PANEL (z-30) */}
      <DispatchQueue />

      {/* LAYER 4: RIGHT PANEL (z-30) */}
      <PhysicsInspector />

      {/* LAYER 3: BOTTOM CENTER TOGGLES (z-40) */}
      <BottomPillToggles />

      {/* Map controls (z-20) */}
      <MapControls />

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
