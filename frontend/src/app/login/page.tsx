"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert, User, Lock, ArrowRight, Activity, Terminal } from "lucide-react";
import Map from "react-map-gl/maplibre";
import DeckGL from "@deck.gl/react";
import { ArcLayer, ScatterplotLayer } from "@deck.gl/layers";
import "maplibre-gl/dist/maplibre-gl.css";

const MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const CENTER = [77.5946, 12.9716]; // Bangalore

// Generate fake tactical nodes and dispatch events
const generateSimulationData = () => {
  const hubs = Array.from({ length: 5 }).map(() => [
    CENTER[0] + (Math.random() - 0.5) * 0.1,
    CENTER[1] + (Math.random() - 0.5) * 0.1
  ]);
  
  const hotspots = Array.from({ length: 40 }).map(() => ({
    position: [
      CENTER[0] + (Math.random() - 0.5) * 0.25,
      CENTER[1] + (Math.random() - 0.5) * 0.25
    ],
    hub: hubs[Math.floor(Math.random() * hubs.length)],
    delay: Math.random() * 5000,
    isActive: Math.random() > 0.5
  }));

  return { hubs, hotspots };
};

function TacticalBackground() {
  const [viewState, setViewState] = useState({
    longitude: CENTER[0],
    latitude: CENTER[1],
    zoom: 12.5,
    pitch: 50,
    bearing: 0
  });
  
  const [time, setTime] = useState(0);
  const data = useMemo(() => generateSimulationData(), []);

  useEffect(() => {
    let animationId: number;
    let startTime = Date.now();
    const animate = () => {
      setTime(Date.now() - startTime);
      setViewState(prev => ({
        ...prev,
        bearing: (prev.bearing + 0.05) % 360,
      }));
      animationId = requestAnimationFrame(animate);
    };
    animationId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationId);
  }, []);

  // Filter arcs to only those that should be firing right now based on time
  const activeArcs = data.hotspots.filter(h => h.isActive && (time % 4000) > (h.delay % 4000) && (time % 4000) < (h.delay % 4000) + 1500);

  const layers = [
    // The Command Hubs (Blue)
    new ScatterplotLayer({
      id: 'hubs-layer',
      data: data.hubs.map(h => ({ position: h })),
      getPosition: (d: any) => d.position,
      getFillColor: [59, 130, 246, 255],
      getRadius: 150,
      radiusMinPixels: 4,
      stroked: true,
      getLineColor: [255, 255, 255, 200],
      getLineWidth: 2,
    }),

    // The Violation Hotspots (Pulsing Red)
    new ScatterplotLayer({
      id: 'hotspots-layer',
      data: data.hotspots,
      getPosition: (d: any) => d.position,
      getFillColor: [244, 63, 94, 200],
      getRadius: (d: any) => {
        const pulse = Math.sin((time - d.delay) / 150) * 40;
        return Math.max(10, 60 + pulse);
      },
      radiusMinPixels: 2,
      updateTriggers: {
        getRadius: [time]
      },
      transitions: {
        getRadius: { type: 'spring', stiffness: 0.1, damping: 0.5 }
      }
    }),

    // Live Dispatch Arcs (Firing continuously)
    new ArcLayer({
      id: 'dispatch-arcs',
      data: activeArcs,
      getSourcePosition: (d: any) => d.hub,
      getTargetPosition: (d: any) => d.position,
      getSourceColor: [59, 130, 246, 255],
      getTargetColor: [244, 63, 94, 255],
      getWidth: 6,
      widthMinPixels: 3,
      getHeight: 0.8,
      tilt: 15,
      transitions: {
        getSourceColor: 500,
        getTargetColor: 500
      }
    })
  ];

  return (
    <div className="absolute inset-0 z-0 bg-[#060910] overflow-hidden">
      <DeckGL
        initialViewState={viewState}
        layers={layers}
        controller={false}
      >
        <Map
          mapStyle={MAP_STYLE}
          reuseMaps
          attributionControl={false}
        />
      </DeckGL>
      
      {/* Soft gradient to keep the login panel readable without obscuring the map */}
      <div className="absolute inset-0 bg-gradient-to-r from-[#060910] via-[#060910]/80 to-transparent pointer-events-none" />
    </div>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("praveg2026");
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [error, setError] = useState(false);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setIsAuthenticating(true);
    setError(false);

    setTimeout(() => {
      if (username === "admin" && password === "praveg2026") {
        sessionStorage.setItem("praveg_auth", "true");
        router.push("/");
      } else {
        setError(true);
        setIsAuthenticating(false);
      }
    }, 1500);
  };

  return (
    <main className="relative min-h-screen flex items-center bg-[#060910] overflow-hidden selection:bg-blue-500/30">
      
      {/* TACTICAL MAP BACKGROUND (Clear map with live animations) */}
      <TacticalBackground />

      {/* LEFT SIDE: LOGIN PANEL */}
      <div className="relative z-10 w-full lg:w-[500px] xl:w-[600px] h-full min-h-screen flex flex-col justify-center px-8 sm:px-16 pointer-events-none">
        
        <motion.div 
          initial={{ opacity: 0, x: -50 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="w-full max-w-[400px] relative pointer-events-auto"
        >
          {/* Header */}
          <div className="relative z-10 flex items-center gap-4 mb-10">
            <motion.div 
              initial={{ rotate: -90, scale: 0 }}
              animate={{ rotate: 0, scale: 1 }}
              transition={{ delay: 0.4, type: "spring", stiffness: 200 }}
              className="relative w-14 h-14 rounded-xl bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shadow-[0_0_30px_rgba(59,130,246,0.3)] backdrop-blur-md"
            >
              <ShieldAlert className="w-7 h-7 text-blue-400" />
              <div className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-rose-500 border-2 border-[#060910] animate-pulse" />
            </motion.div>
            <div>
              <h1 className="text-3xl font-bold text-white tracking-[0.2em] font-heading leading-tight drop-shadow-lg">PRAVEG</h1>
              <p className="text-[10px] text-blue-400 font-mono tracking-[0.2em] uppercase mt-1">Predictive Routing & Violation Enforcement Grid</p>
            </div>
          </div>

          <form onSubmit={handleLogin} className="relative z-10 space-y-6 bg-[#0B0F1A]/70 backdrop-blur-xl p-8 rounded-2xl border border-white/5 shadow-2xl">
            <div className="space-y-2">
              <label className="text-[10px] font-mono tracking-[0.15em] text-zinc-500 uppercase flex items-center justify-between">
                <span>Operator ID</span>
                <span className="text-rose-500/80">REQ</span>
              </label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <User className="h-4 w-4 text-zinc-500 group-focus-within:text-blue-400 transition-colors" />
                </div>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="block w-full pl-12 pr-4 py-3.5 bg-black/40 border border-white/10 rounded-xl text-sm text-white placeholder-zinc-700 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all font-mono hover:bg-black/60"
                  placeholder="Enter Operator ID"
                  disabled={isAuthenticating}
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-mono tracking-[0.15em] text-zinc-500 uppercase flex items-center justify-between">
                <span>Access Code</span>
                <span className="text-rose-500/80">REQ</span>
              </label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <Lock className="h-4 w-4 text-zinc-500 group-focus-within:text-blue-400 transition-colors" />
                </div>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="block w-full pl-12 pr-4 py-3.5 bg-black/40 border border-white/10 rounded-xl text-sm text-white placeholder-zinc-700 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50 transition-all font-mono hover:bg-black/60"
                  placeholder="••••••••••"
                  disabled={isAuthenticating}
                />
              </div>
            </div>

            <AnimatePresence>
              {error && (
                <motion.div 
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="text-[10px] font-mono text-rose-400 bg-rose-500/10 border border-rose-500/30 px-4 py-3 rounded-xl flex items-center gap-3 mt-4">
                    <Activity className="w-4 h-4 flex-shrink-0" />
                    ACCESS DENIED. UNAUTHORIZED CREDENTIALS.
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <button
              type="submit"
              disabled={isAuthenticating}
              className="relative w-full group overflow-hidden rounded-xl mt-8 shadow-[0_10px_20px_-10px_rgba(59,130,246,0.3)]"
            >
              <div className="absolute inset-0 bg-blue-600 opacity-90 transition-opacity group-hover:opacity-100 group-disabled:bg-zinc-800 group-disabled:opacity-50" />
              <div className="absolute inset-0 bg-[linear-gradient(45deg,transparent_25%,rgba(255,255,255,0.2)_50%,transparent_75%)] bg-[length:250%_250%,100%_100%] bg-[position:200%_0,0_0] bg-no-repeat transition-[background-position_0s_ease] hover:bg-[position:-200%_0,0_0] duration-[1500ms]" />
              
              <div className="relative flex items-center justify-center py-4 px-4">
                {isAuthenticating ? (
                  <div className="flex items-center gap-3">
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span className="text-[11px] font-mono font-bold tracking-[0.2em] text-white uppercase">Establishing Uplink...</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <Terminal className="w-4 h-4 text-white/90" />
                    <span className="text-[11px] font-bold font-mono tracking-[0.2em] text-white uppercase">Initialize System</span>
                    <ArrowRight className="w-4 h-4 text-white/90 group-hover:translate-x-1.5 transition-transform" />
                  </div>
                )}
              </div>
            </button>
          </form>

          {/* Prototype Credentials Hint */}
          <div className="relative z-10 mt-8 flex flex-col items-center gap-2">
            <span className="text-[9px] text-zinc-500 font-mono uppercase tracking-[0.2em]">
              Prototype Test Credentials
            </span>
            <div className="flex items-center gap-4 text-[10px] font-mono text-zinc-400 bg-white/[0.02] px-4 py-2 rounded-lg border border-white/5">
              <span>ID: <strong className="text-white">admin</strong></span>
              <div className="w-px h-3 bg-zinc-700" />
              <span>PWD: <strong className="text-white">praveg2026</strong></span>
            </div>
          </div>
        </motion.div>
      </div>

    </main>
  );
}
