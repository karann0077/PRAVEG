"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useMapStore } from "@/store/useMapStore";
import { Clock, Activity } from "lucide-react";

export default function TimeMachine() {
  const { targetHour, setTargetHour } = useMapStore();
  const [currentHour, setCurrentHour] = useState(new Date().getHours());

  // Update current hour periodically
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentHour(new Date().getHours());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  // Compute the 5 steps: Live, +3h, +6h, +9h, +12h
  const steps = useMemo(() => {
    return [
      { label: "LIVE", value: "live" },
      { label: `+3h`, value: String((currentHour + 3) % 24).padStart(2, "0") },
      { label: `+6h`, value: String((currentHour + 6) % 24).padStart(2, "0") },
      { label: `+9h`, value: String((currentHour + 9) % 24).padStart(2, "0") },
      { label: `+12h`, value: String((currentHour + 12) % 24).padStart(2, "0") },
    ];
  }, [currentHour]);

  const currentIndex = steps.findIndex(s => s.value === targetHour);
  const sliderValue = currentIndex === -1 ? 0 : currentIndex;

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const index = parseInt(e.target.value, 10);
    setTargetHour(steps[index].value);
  };

  return (
    <div className="relative z-50 flex items-center justify-center">
      <div 
        className="flex items-center gap-6 px-6 py-4 rounded-full border border-slate-700/60 backdrop-blur-xl shadow-2xl transition-all duration-300"
        style={{
          background: "rgba(10, 15, 26, 0.85)",
          boxShadow: "0 20px 40px rgba(0,0,0,0.6), inset 0 1px 1px rgba(255,255,255,0.05)",
        }}
      >
        {/* Left Label */}
        <div className="flex items-center gap-3 pr-6 border-r border-slate-700/50">
          <div className="w-10 h-10 rounded-full bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 relative overflow-hidden">
            {sliderValue === 0 ? (
              <>
                <Activity className="w-5 h-5 relative z-10 animate-pulse" />
                <div className="absolute inset-0 bg-cyan-400/20 animate-ping" />
              </>
            ) : (
              <Clock className="w-5 h-5 relative z-10" />
            )}
          </div>
          <div className="flex flex-col justify-center">
            <span className="text-[10px] text-slate-400 font-mono uppercase tracking-[0.2em] leading-tight mb-0.5">
              Timeline
            </span>
            <span className="text-sm font-bold font-mono text-white leading-tight flex items-center gap-1.5">
              {targetHour === "live" ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
                  LIVE
                </>
              ) : (
                <>{targetHour}:00</>
              )}
            </span>
          </div>
        </div>

        {/* Scrubber Area */}
        <div className="relative flex items-center w-[360px] h-12">
          {/* Native Range Input (Invisible but interactive) */}
          <input
            type="range"
            min="0"
            max="4"
            step="1"
            value={sliderValue}
            onChange={handleSliderChange}
            className="absolute inset-0 w-full h-full opacity-0 cursor-grab active:cursor-grabbing z-20"
          />
          
          {/* Track Background */}
          <div className="absolute left-2 right-2 h-1.5 bg-slate-800 rounded-full overflow-hidden z-0">
            <div 
              className="absolute inset-y-0 left-0 bg-gradient-to-r from-cyan-600 to-cyan-400 transition-all duration-300 ease-out"
              style={{ width: `${(sliderValue / 4) * 100}%` }}
            />
          </div>

          {/* Stepper Nodes */}
          <div className="absolute inset-x-0 flex justify-between items-center pointer-events-none z-10 px-2">
            {steps.map((s, i) => {
              const isActive = sliderValue === i;
              const isPast = sliderValue > i;
              
              return (
                <div key={i} className="flex flex-col items-center justify-center relative">
                  {/* The Node Dot */}
                  <div 
                    className={`w-3.5 h-3.5 rounded-full border-2 transition-all duration-300 ${
                      isActive 
                        ? 'bg-white border-cyan-400 scale-[1.3] shadow-[0_0_12px_rgba(34,211,238,0.8)]' 
                        : isPast 
                        ? 'bg-cyan-400 border-cyan-500' 
                        : 'bg-slate-800 border-slate-600'
                    }`} 
                  />
                  
                  {/* The Label under the dot */}
                  <span className={`absolute top-6 text-[10px] font-mono tracking-widest whitespace-nowrap transition-colors duration-300 ${
                    isActive ? 'text-cyan-400 font-bold drop-shadow-md' : 'text-slate-500'
                  }`}>
                    {s.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
