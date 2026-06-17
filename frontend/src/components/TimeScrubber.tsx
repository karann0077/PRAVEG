"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useMapStore } from "@/store/useMapStore";
import { Clock, Play, Pause, SkipForward, Sunrise, Sun, Moon } from "lucide-react";
import { motion } from "framer-motion";

// Time labels for the 48 tick positions (every 30min over 24h)
const HOUR_LABELS = Array.from({ length: 25 }, (_, i) => {
  const h = i % 24;
  return h === 0 ? "NOW" : h === 6 ? "6AM" : h === 12 ? "NOON" : h === 18 ? "6PM" : h === 24 ? "+24H" : "";
});

function getPeakInfo(hour: number) {
  if (hour >= 8 && hour <= 11) return { label: "Morning Rush", color: "text-rose-400", icon: Sunrise };
  if (hour >= 17 && hour <= 20) return { label: "Evening Rush", color: "text-orange-400", icon: Sun };
  if (hour >= 23 || hour <= 5) return { label: "Late Night", color: "text-blue-400", icon: Moon };
  return { label: "Off-Peak", color: "text-emerald-400", icon: Sun };
}

export default function TimeScrubber() {
  const { setTargetHour } = useMapStore();
  const [progress, setProgress] = useState(0); // 0 to 24 hours
  const [isPlaying, setIsPlaying] = useState(false);
  const playRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const currentDate = new Date();
  currentDate.setHours(currentDate.getHours() + progress, 0, 0, 0);
  const displayTime = currentDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const displayDate = currentDate.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });

  const peakInfo = getPeakInfo(currentDate.getHours());
  const PeakIcon = peakInfo.icon;

  const updateHour = useCallback(
    (val: number) => {
      setProgress(val);
      const dt = new Date();
      dt.setHours(dt.getHours() + val, 0, 0, 0);
      setTargetHour(dt.toISOString().slice(0, 16));
    },
    [setTargetHour]
  );

  useEffect(() => {
    if (isPlaying) {
      playRef.current = setInterval(() => {
        setProgress((p) => {
          if (p >= 24) {
            setIsPlaying(false);
            return 24;
          }
          const next = parseFloat((p + 0.25).toFixed(2));
          updateHour(next);
          return next;
        });
      }, 300);
    } else if (playRef.current) {
      clearInterval(playRef.current);
    }
    return () => {
      if (playRef.current) clearInterval(playRef.current);
    };
  }, [isPlaying, updateHour]);

  // EPS intensity bar — shows predicted violation density at each hour
  const epsProfile = Array.from({ length: 25 }, (_, i) => {
    const h = i % 24;
    if ((h >= 8 && h <= 11) || (h >= 17 && h <= 20)) return 0.85 + Math.random() * 0.15;
    if (h >= 23 || h <= 5) return 0.05 + Math.random() * 0.1;
    return 0.2 + Math.random() * 0.35;
  });

  return (
    <motion.div
      initial={{ y: 120, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ type: "spring", stiffness: 100, damping: 20, delay: 0.3 }}
      className="absolute bottom-5 left-1/2 -translate-x-1/2 w-[760px] z-20 rounded-2xl border border-slate-700/60 overflow-hidden"
      style={{
        background: "rgba(8,15,30,0.92)",
        backdropFilter: "blur(28px)",
        boxShadow: "0 25px 50px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.03)",
      }}
    >
      {/* Top row: info + controls */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/60">
        <div className="flex items-center gap-3">
          <div className="p-1.5 bg-cyan-500/15 rounded-lg">
            <Clock className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <p className="text-slate-400 text-[10px] font-mono uppercase tracking-widest">
              Predictive Horizon
            </p>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold font-mono text-lg">{displayTime}</span>
              <span className="text-slate-500 text-xs font-mono">{displayDate}</span>
              <span className="text-cyan-400 text-xs font-mono font-bold">T+{progress.toFixed(0)}H</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-1.5 text-xs font-mono ${peakInfo.color}`}>
            <PeakIcon className="w-3.5 h-3.5" />
            {peakInfo.label}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setIsPlaying((p) => !p)}
              className="w-8 h-8 flex items-center justify-center rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-all border border-slate-700 hover:border-slate-600"
            >
              {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 ml-0.5" />}
            </button>
            <button
              onClick={() => updateHour(Math.min(24, progress + 1))}
              className="w-8 h-8 flex items-center justify-center rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-all border border-slate-700 hover:border-slate-600"
            >
              <SkipForward className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Violation density sparkbar */}
      <div className="px-5 pt-3">
        <div className="flex items-end gap-0.5 h-8">
          {epsProfile.map((intensity, i) => {
            const isActive = i <= progress;
            const isPeak = (i >= 8 && i <= 11) || (i >= 17 && i <= 20);
            const barColor = isPeak
              ? isActive ? "bg-rose-500" : "bg-rose-500/25"
              : isActive ? "bg-cyan-500/60" : "bg-slate-700/50";
            return (
              <div
                key={i}
                onClick={() => updateHour(i)}
                className={`flex-1 rounded-sm cursor-pointer transition-all hover:opacity-80 ${barColor}`}
                style={{ height: `${Math.max(15, intensity * 100)}%` }}
                title={`T+${i}H`}
              />
            );
          })}
        </div>
      </div>

      {/* Slider + labels */}
      <div className="px-5 pt-2 pb-4">
        <div className="relative flex items-center">
          <input
            type="range"
            min="0"
            max="24"
            step="0.25"
            value={progress}
            onChange={(e) => updateHour(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-slate-800 rounded-full appearance-none cursor-pointer
                       [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5 
                       [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full 
                       [&::-webkit-slider-thumb]:shadow-[0_0_12px_rgba(34,211,238,0.9),0_0_0_2px_rgba(34,211,238,0.4)]
                       [&::-webkit-slider-thumb]:cursor-grab [&::-webkit-slider-thumb]:active:cursor-grabbing
                       [&::-webkit-slider-runnable-track]:rounded-full"
            style={{
              background: `linear-gradient(to right, #06b6d4 0%, #06b6d4 ${(progress / 24) * 100}%, rgba(30,41,59,0.8) ${(progress / 24) * 100}%)`,
            }}
          />
        </div>
        <div className="flex justify-between mt-1.5 px-0.5">
          {HOUR_LABELS.map((label, i) => (
            <span key={i} className="text-[9px] font-mono text-slate-600 w-0 overflow-visible text-center">
              {label}
            </span>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
