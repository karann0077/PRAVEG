"use client";

import React, { useEffect, useState } from "react";
import TacticalMap from "@/components/TacticalMap";
import DispatchQueue from "@/components/DispatchQueue";
import PhysicsInspector from "@/components/PhysicsInspector";
import TimeMachine from "@/components/TimeMachine";
import ZoneCommander from "@/components/ZoneCommander";
import { useMapStore } from "@/store/useMapStore";
import { ShieldAlert, Layers, Map as MapIcon, RotateCcw, Activity, AlignLeft, Hexagon, ArrowUpRight, Box } from "lucide-react";

function BottomPillToggles() {
  const { activeLayerMode, setActiveLayerMode } = useMapStore();
  
  const buttons = [
    { id: "tactical", label: "Tactical Lines", icon: <AlignLeft className="w-4 h-4" /> },
    { id: "heatmap", label: "Heatmap", icon: <Activity className="w-4 h-4" /> }
  ] as const;

  return (
    <div className="absolute bottom-8 left-[424px] z-40 flex items-center p-1 bg-[#0B0F1A]/90 backdrop-blur-md rounded-lg border border-white/5 shadow-2xl">
      {buttons.map((btn) => {
        const isActive = activeLayerMode === btn.id;
        return (
          <button
            key={btn.id}
            onClick={() => setActiveLayerMode(btn.id)}
            className={`relative flex items-center gap-2 px-4 py-2 rounded-md text-xs font-bold uppercase tracking-widest transition-colors z-10 ${
              isActive ? "text-white" : "text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {isActive && (
              <div className="absolute inset-0 bg-[#3b82f6]/20 border border-[#3b82f6]/30 rounded-md -z-10 shadow-[0_0_15px_rgba(59,130,246,0.2)]" />
            )}
            {btn.icon}
            {btn.label}
          </button>
        );
      })}
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
    <div className="absolute bottom-32 right-6 z-20 flex flex-col bg-[#0D1117]/70 backdrop-blur-[12px] rounded-xl border border-white/5 shadow-2xl overflow-hidden divide-y divide-white/5">
      <button
        onClick={() => setMapStyle(mapStyle === "dark" ? "satellite" : "dark")}
        className="group w-10 h-10 flex items-center justify-center hover:bg-white/5 transition-colors relative"
      >
        {mapStyle === "dark" ? (
          <Layers className="w-[18px] h-[18px] text-zinc-400 group-hover:text-white transition-colors" />
        ) : (
          <MapIcon className="w-[18px] h-[18px] text-[#3b82f6] group-hover:text-white transition-colors" />
        )}
        <span className="absolute right-12 bg-black/80 text-white text-[10px] font-mono px-2 py-1 rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap transition-opacity">
          {mapStyle === "dark" ? "Switch to Satellite" : "Switch to Dark Map"}
        </span>
      </button>

      <button
        onClick={toggle3D}
        className={`group w-10 h-10 flex items-center justify-center hover:bg-white/5 transition-colors relative ${
          viewState.pitch > 0 ? "text-[#3b82f6]" : "text-zinc-400 hover:text-white"
        }`}
      >
        <Box className="w-[18px] h-[18px]" />
        <span className="absolute right-12 bg-black/80 text-white text-[10px] font-mono px-2 py-1 rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap transition-opacity">
          Toggle 3D View
        </span>
      </button>

      <button
        onClick={resetNorth}
        className="group w-10 h-10 flex items-center justify-center hover:bg-white/5 transition-colors relative"
      >
        <RotateCcw className="w-[18px] h-[18px] text-zinc-400 group-hover:text-white transition-colors" />
        <span className="absolute right-12 bg-black/80 text-white text-[10px] font-mono px-2 py-1 rounded opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap transition-opacity">
          Reset North
        </span>
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
    <main className="relative w-[100vw] h-[100vh] overflow-hidden bg-background font-sans select-none">
      {/* z-0 Base Map, z-10 DeckGL */}
      <TacticalMap />

      {/* LAYER 1: TOP BAR (z-40) */}
      <div className="absolute top-0 left-0 right-0 h-16 z-40 flex items-center justify-between px-6 bg-gradient-to-b from-zinc-900 to-[#0d1117]/95 backdrop-blur-xl border-b border-[#3b82f6]/30 shadow-2xl">
        {/* Left: Branding */}
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-6 h-6 text-indigo-500 drop-shadow-[0_0_8px_rgba(99,102,241,0.8)]" />
          <div className="flex flex-col">
            <h1 className="text-white text-lg font-black tracking-widest uppercase font-heading leading-tight">
              DRISHTI COMMAND
            </h1>
            <span className="text-[10px] text-zinc-400 font-mono uppercase tracking-[0.15em] leading-tight">
              Traffic Intelligence Command
            </span>
          </div>
        </div>

        {/* Center: Live Time + Scrubber */}
        <div className="flex items-center justify-center h-full gap-6">
          <div className="text-zinc-300 font-mono text-sm font-medium tracking-widest bg-black/40 px-4 py-1.5 rounded-full border border-white/5">
            {time || "00:00:00"}
          </div>
          <TimeMachine />
          <ZoneCommander />
        </div>

        {/* Right: Global Stats */}
        <div className="flex items-center gap-8 h-full py-2">
          {/* Active Hotspots */}
          <div className="flex flex-col items-end justify-center">
            <span className="text-[10px] text-zinc-500 font-bold uppercase tracking-[0.12em] mb-0.5">Active Hotspots</span>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold font-mono text-white leading-none relative">
                142
                <span className="absolute -inset-2 bg-rose-500/20 blur-md rounded-full animate-pulse -z-10" />
              </span>
              <span className="text-rose-500 text-xs font-bold font-mono uppercase tracking-wider drop-shadow-[0_0_8px_rgba(244,63,94,0.4)]">Critical</span>
            </div>
          </div>
          
          <div className="w-[1px] h-full bg-white/10" />

          {/* Economic Bleed */}
          <div className="flex flex-col items-end justify-center">
            <span className="text-[10px] text-zinc-500 font-bold uppercase tracking-[0.12em] mb-0.5">Economic Bleed</span>
            <div className="flex items-baseline gap-1.5 text-amber-500">
              <span className="text-2xl font-bold font-mono leading-none drop-shadow-[0_0_8px_rgba(245,158,11,0.4)]">₹4.2L</span>
              <span className="text-xs font-mono">/ hr</span>
              <ArrowUpRight className="w-3.5 h-3.5 text-rose-500 ml-1" />
            </div>
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

      {/* Footer Attribution (z-20) */}
      <div className="absolute bottom-4 right-4 z-20 flex items-center gap-3 text-[10px] font-mono">
        <span className="text-zinc-500/60 uppercase tracking-widest">LightGBM · MapmyIndia</span>
        <div className="bg-[#0D1117]/80 backdrop-blur-md border border-white/5 text-[#3b82f6] px-2 py-1 rounded flex items-center gap-1.5 shadow-lg">
          <span className="w-1.5 h-1.5 rounded-full bg-[#3b82f6] animate-pulse" />
          298K EVENTS
        </div>
      </div>

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
