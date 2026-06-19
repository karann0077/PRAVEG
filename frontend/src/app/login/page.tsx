"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert, User, Lock, ArrowRight, Activity, Terminal } from "lucide-react";

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

    // Simulate network delay for effect
    setTimeout(() => {
      if (username === "admin" && password === "praveg2026") {
        sessionStorage.setItem("praveg_auth", "true");
        router.push("/");
      } else {
        setError(true);
        setIsAuthenticating(false);
      }
    }, 1200);
  };

  return (
    <main className="relative min-h-screen flex items-center justify-center bg-[#060910] overflow-hidden selection:bg-blue-500/30">
      {/* Dynamic Background Elements */}
      <div className="absolute inset-0 z-0 flex items-center justify-center">
        <div className="absolute w-[800px] h-[800px] bg-blue-600/10 rounded-full blur-[120px] animate-pulse" style={{ animationDuration: '4s' }} />
        <div className="absolute w-[600px] h-[600px] bg-rose-600/5 rounded-full blur-[100px] -translate-x-1/3 -translate-y-1/3" />
        
        {/* Tech Grid */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `linear-gradient(rgba(255, 255, 255, 1) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 255, 255, 1) 1px, transparent 1px)`,
            backgroundSize: "40px 40px",
            backgroundPosition: "center center",
          }}
        />
        
        {/* Scanline overlay */}
        <div
          className="absolute inset-0 opacity-[0.02] pointer-events-none"
          style={{
            backgroundImage: "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,1) 2px, rgba(255,255,255,1) 3px)",
          }}
        />
      </div>

      <motion.div 
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="relative z-10 w-full max-w-md p-8 sm:p-10"
      >
        <div className="absolute inset-0 bg-[#0B0F1A]/80 backdrop-blur-2xl rounded-3xl border border-white/5 shadow-[0_0_80px_rgba(0,0,0,0.8)] pointer-events-none" />
        
        <div className="relative z-10">
          {/* Logo & Header */}
          <div className="flex flex-col items-center mb-10">
            <motion.div 
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.3, type: "spring", stiffness: 200 }}
              className="relative w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500/20 to-blue-600/5 border border-blue-500/30 flex items-center justify-center mb-6 shadow-[0_0_30px_rgba(59,130,246,0.2)]"
            >
              <ShieldAlert className="w-8 h-8 text-blue-400" />
              <div className="absolute top-0 right-0 w-2 h-2 rounded-full bg-rose-500 animate-ping" />
            </motion.div>
            
            <h1 className="text-3xl font-bold text-white tracking-widest mb-2 font-heading text-center">PRAVEG</h1>
            <p className="text-[10px] text-blue-400 font-mono tracking-[0.2em] uppercase text-center opacity-80">
              Predictive Routing & Violation Enforcement Grid
            </p>
          </div>

          <form onSubmit={handleLogin} className="space-y-5">
            {/* Username Input */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-mono tracking-widest text-zinc-500 uppercase ml-1">Operator ID</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <User className="h-4 w-4 text-zinc-500 group-focus-within:text-blue-400 transition-colors" />
                </div>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="block w-full pl-11 pr-4 py-3.5 bg-black/40 border border-white/10 rounded-xl text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-transparent transition-all font-mono"
                  placeholder="Enter Operator ID"
                  disabled={isAuthenticating}
                />
              </div>
            </div>

            {/* Password Input */}
            <div className="space-y-1.5">
              <label className="text-[10px] font-mono tracking-widest text-zinc-500 uppercase ml-1">Access Code</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <Lock className="h-4 w-4 text-zinc-500 group-focus-within:text-blue-400 transition-colors" />
                </div>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="block w-full pl-11 pr-4 py-3.5 bg-black/40 border border-white/10 rounded-xl text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-transparent transition-all font-mono"
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
                  className="text-[11px] font-mono text-rose-400 bg-rose-500/10 border border-rose-500/20 px-3 py-2 rounded flex items-center justify-center gap-2"
                >
                  <Activity className="w-3 h-3" />
                  ACCESS DENIED. INVALID CREDENTIALS.
                </motion.div>
              )}
            </AnimatePresence>

            <button
              type="submit"
              disabled={isAuthenticating}
              className="relative w-full group overflow-hidden rounded-xl mt-4"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-blue-600 to-blue-400 opacity-90 transition-opacity group-hover:opacity-100" />
              <div className="absolute -inset-[100%] bg-white/20 blur-[20px] rounded-full translate-x-[-150%] skew-x-[45deg] group-hover:translate-x-[150%] transition-transform duration-700 ease-out" />
              
              <div className="relative flex items-center justify-center py-3.5 px-4">
                {isAuthenticating ? (
                  <div className="flex items-center gap-3">
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span className="text-xs font-mono font-bold tracking-widest text-white uppercase">Authenticating...</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-3">
                    <Terminal className="w-4 h-4 text-white/80" />
                    <span className="text-sm font-bold tracking-[0.15em] text-white uppercase">Initialize System</span>
                    <ArrowRight className="w-4 h-4 text-white/80 group-hover:translate-x-1 transition-transform" />
                  </div>
                )}
              </div>
            </button>
          </form>

          {/* Prototype Credentials Hint */}
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1 }}
            className="mt-8 flex flex-col items-center gap-1 opacity-60 hover:opacity-100 transition-opacity"
          >
            <span className="text-[9px] text-zinc-500 font-mono uppercase tracking-widest border-b border-zinc-700 pb-1 mb-1">
              Prototype Test Credentials
            </span>
            <div className="flex items-center gap-4 text-[10px] font-mono text-zinc-400">
              <span>ID: <strong className="text-white">admin</strong></span>
              <span>PWD: <strong className="text-white">praveg2026</strong></span>
            </div>
          </motion.div>
        </div>
      </motion.div>
    </main>
  );
}
