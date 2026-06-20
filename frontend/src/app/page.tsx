"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import TacticalMap from "@/components/TacticalMap";
import DispatchQueue from "@/components/DispatchQueue";
import PhysicsInspector from "@/components/PhysicsInspector";
import TimeMachine from "@/components/TimeMachine";
import ZoneCommander from "@/components/ZoneCommander";
import { useMapStore } from "@/store/useMapStore";
import { ShieldAlert, Layers, Map as MapIcon, RotateCcw, Activity, AlignLeft, Hexagon, ArrowUpRight, Box } from "lucide-react";

function BottomPillToggles() {
  const { activeLayerMode, setActiveLayerMode } = useMapStore();
  
  return (
    <div className="flex items-center gap-2 bg-[#0B0F1A]/80 backdrop-blur-xl border border-white/10 p-1.5 rounded-full shadow-2xl">
      <button
        onClick={() => setActiveLayerMode("action_roads")}
        className={`px-4 py-2 rounded-full text-xs font-bold tracking-widest uppercase transition-all duration-300 ${
          activeLayerMode === "action_roads" 
            ? "bg-[#3b82f6] text-white shadow-[0_0_15px_rgba(59,130,246,0.5)]" 
            : "text-zinc-400 hover:text-white hover:bg-white/5"
        }`}
      >
        <div className="flex items-center gap-2">
          <AlignLeft className="w-3.5 h-3.5" />
          Road Intelligence
        </div>
      </button>
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
  const router = useRouter();
  const [isAuth, setIsAuth] = useState(false);
  const { geoData } = useMapStore();
  const [time, setTime] = useState("");

  useEffect(() => {
    if (!sessionStorage.getItem("praveg_auth")) {
      router.push("/login");
    } else {
      setIsAuth(true);
    }
  }, [router]);

  const stats = React.useMemo(() => {
    let hotspots = 0;
    let bleed = 0;
    if (geoData?.features) {
      geoData.features.forEach((f: any) => {
        if (!f.properties.is_ripple) {
          hotspots++;
        }
        if (f.properties.eps > 0) {
           // Estimate bleed: ~50 Rs per delayed vehicle hr, approx 500 cars per high-eps spot
           const eps = f.properties.eps || 0;
           bleed += (eps / 100) * 500 * 50; 
        }
      });
    }
    return {
      hotspots: hotspots || 0,
      bleedLakhs: bleed > 0 ? (bleed / 100000).toFixed(1) : "0.0"
    };
  }, [geoData]);

  useEffect(() => {
    const update = () =>
      setTime(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  if (!isAuth) {
    return <div className="h-screen w-screen bg-[#060910]" />;
  }

  return (
    <main className="relative w-screen h-screen overflow-hidden bg-[#060910] font-sans selection:bg-[#3b82f6]/30">
      {/* z-0 Base Map, z-10 DeckGL */}
      <TacticalMap />

      {/* LAYER 1: TOP BAR (z-40) */}
      <div className="absolute top-0 left-0 right-0 h-16 z-40 flex items-center justify-between px-6 bg-gradient-to-b from-zinc-900 to-[#0d1117]/95 backdrop-blur-xl border-b border-[#3b82f6]/30 shadow-2xl">
        {/* Left: Branding */}
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-6 h-6 text-indigo-500 drop-shadow-[0_0_8px_rgba(99,102,241,0.8)]" />
          <div className="flex flex-col">
            <h1 className="text-white text-lg font-black tracking-widest uppercase font-heading leading-tight">
              PRAVEG
            </h1>
            <span className="text-[10px] text-zinc-400 font-mono uppercase tracking-[0.05em] leading-tight">
              Predictive Routing and Violation Enforcement Grid
            </span>
          </div>
        </div>

        {/* Center: Live Time + Scrubber */}
        <div className="flex items-center justify-center h-full gap-6">
          <div className="text-zinc-300 font-mono text-sm font-medium tracking-widest bg-black/40 px-4 py-1.5 rounded-full border border-white/5">
            {time || "00:00:00"}
          </div>
          <ZoneCommander />
        </div>

        {/* Right: Global Stats */}
        <div className="flex items-center gap-8 h-full py-2">


          {/* Economic Bleed */}
          <div className="flex flex-col items-end justify-center">
            <span className="text-[10px] text-zinc-500 font-bold uppercase tracking-[0.12em] mb-0.5">Est. Public Impact</span>
            <div className="flex items-baseline gap-1.5 text-amber-500">
              <span className="text-2xl font-bold font-mono leading-none drop-shadow-[0_0_8px_rgba(245,158,11,0.4)]">₹{stats.bleedLakhs}L</span>
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

      {/* LAYER 3: BOTTOM CENTER COMPONENTS (z-40) */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-4 z-40 pointer-events-none">
        <div className="pointer-events-auto">
          <TimeMachine />
        </div>
        <div className="flex items-center justify-center">
          <BottomPillToggles />
        </div>
      </div>

      {/* Map controls (z-20) */}
      <MapControls />

      {/* Footer Attribution (z-20) */}
      <div className="absolute bottom-4 right-4 z-20 flex items-center gap-3 text-[10px] font-mono opacity-50 hover:opacity-100 transition-opacity">
        <span className="text-zinc-500/60 uppercase tracking-widest">DRISHTI AI Engine · Admin Mode</span>
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
