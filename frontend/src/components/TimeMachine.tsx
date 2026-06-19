"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useMapStore } from "@/store/useMapStore";
import { Clock, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export default function TimeMachine() {
  const { targetHour, setTargetHour } = useMapStore();
  const [isOpen, setIsOpen] = useState(false);
  const [currentHour, setCurrentHour] = useState(new Date().getHours());

  // Update current hour periodically just in case
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

  // Find the current slider index
  const currentIndex = steps.findIndex(s => s.value === targetHour);
  const sliderValue = currentIndex === -1 ? 0 : currentIndex;

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const index = parseInt(e.target.value, 10);
    setTargetHour(steps[index].value);
  };

  const handleClose = () => {
    setIsOpen(false);
    setTargetHour("live"); // Snap back to live
  };

  const handleOpen = () => {
    setIsOpen(true);
  };

  return (
    <div className="relative z-50">
      <AnimatePresence>
        {!isOpen ? (
          <motion.button
            key="button"
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            onClick={handleOpen}
            className="w-10 h-10 flex items-center justify-center bg-slate-900/90 hover:bg-slate-800 text-cyan-400 rounded-xl border border-cyan-500/30 shadow-[0_0_15px_rgba(34,211,238,0.2)] backdrop-blur-xl transition-all"
            title="Forecast (Future)"
          >
            <Clock className="w-5 h-5" />
          </motion.button>
        ) : (
          <motion.div
            key="panel"
            className="absolute top-14 left-1/2 -translate-x-1/2 w-80 rounded-2xl border border-slate-700/60 overflow-hidden"
            style={{
              background: "rgba(8,15,30,0.85)",
              backdropFilter: "blur(24px)",
              boxShadow: "0 25px 50px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.03)",
            }}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800/60 bg-gradient-to-r from-cyan-950/40 to-transparent">
              <div className="flex items-center gap-2 text-cyan-400">
                <Clock className="w-5 h-5" />
                <span className="font-mono font-bold uppercase tracking-widest text-sm">Forecast</span>
              </div>
              <button onClick={handleClose} className="text-slate-400 hover:text-white transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-5">
              <div className="flex justify-between items-end mb-6">
                <div className="text-xs text-slate-400 font-mono uppercase tracking-widest">Looking Ahead</div>
                <div className="text-2xl font-bold font-mono text-white">
                  {targetHour === "live" ? "LIVE" : `${targetHour}:00`}
                </div>
              </div>

              <input
                type="range"
                min="0"
                max="4"
                step="1"
                value={sliderValue}
                onChange={handleSliderChange}
                className="w-full h-1.5 bg-slate-800 rounded-full appearance-none cursor-pointer
                           [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5 
                           [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full 
                           [&::-webkit-slider-thumb]:shadow-[0_0_12px_rgba(34,211,238,0.9),0_0_0_2px_rgba(34,211,238,0.4)]
                           [&::-webkit-slider-thumb]:cursor-grab [&::-webkit-slider-thumb]:active:cursor-grabbing
                           [&::-webkit-slider-runnable-track]:rounded-full"
                style={{
                  background: `linear-gradient(to right, #06b6d4 0%, #06b6d4 ${(sliderValue / 4) * 100}%, rgba(30,41,59,0.8) ${(sliderValue / 4) * 100}%)`,
                }}
              />
              
              <div className="flex justify-between items-center mt-2 text-[10px] font-mono text-slate-400 px-1">
                {steps.map((s, i) => (
                  <div key={i} className={`flex flex-col items-center ${sliderValue === i ? 'text-cyan-400 font-bold' : ''}`}>
                    <span className="mb-1 h-1.5 w-0.5 bg-slate-600 rounded-full" />
                    {s.label}
                  </div>
                ))}
              </div>
              
              <div className="mt-6 p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg">
                <p className="text-[10px] text-rose-300 font-mono leading-relaxed">
                  <span className="font-bold">NOTE:</span> Predictions are available in 3-hour intervals for the next 12 hours based on historical trends.
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
