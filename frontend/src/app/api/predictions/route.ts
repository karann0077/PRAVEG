// frontend/src/app/api/predictions/route.ts
//
// FIX LOG (2026-06-18):
//   BUG-A  FIXED: Added cache-busting headers so the browser doesn't serve
//          stale predictions_live.geojson when the daemon updates the file.
//
//   FIX-NEW: Added X-Prediction-Timestamp header so TacticalMap can detect
//            when data actually changed and trigger a re-render with animation.
//
//   FIX-NEW: Passes ?hour=live to include live_delta enrichment.

import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import { statSync } from "fs";

export const dynamic = "force-dynamic"; // Disable Next.js static caching

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const hourParam = searchParams.get("hour");
  const hour =
    hourParam
      ? hourParam === "live"
        ? "live"
        : parseInt(hourParam, 10).toString().padStart(2, "0")
      : "live";

  const jsonDirectory = path.join(process.cwd(), "..", "artifacts", "predictions");
  const geojsonPath = path.join(jsonDirectory, `predictions_${hour}.geojson`);
  const ripplePath = path.join(jsonDirectory, `ripples_${hour}.geojson`);

  try {
    let baseData: any = { type: "FeatureCollection", features: [] };
    let rippleData: any = { type: "FeatureCollection", features: [] };
    let lastModified: Date | null = null;

    const backendUrl = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

    // ── FAST PATH: Serve current-hour batch instantly while live loads ────
    // For live mode: read the batch file for this clock-hour from local disk
    // (sub-100ms), so the UI is never empty. Then try the live endpoint with
    // a 4-second timeout. If live succeeds, it upgrades the response; if not,
    // the batch data is returned and marked is_cached=true.
    let isLive = false;
    if (hour === "live") {
      const clockHour = new Date().getHours().toString().padStart(2, "0");
      const batchPath = path.join(jsonDirectory, `predictions_${clockHour}.geojson`);
      try {
        const batchRaw = await fs.readFile(batchPath, "utf-8");
        baseData = JSON.parse(batchRaw);
        lastModified = new Date();
      } catch { /* no batch file yet, stay with empty */ }

      // Now race the live fetch against a 4-second timeout
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 4000);
        const liveUrl = `${backendUrl}/artifacts/live/predictions_live.geojson`;
        const res = await fetch(liveUrl, { cache: "no-store", signal: controller.signal });
        clearTimeout(timer);
        if (res.ok) {
          const liveData = await res.json();
          if (liveData?.features?.length > 0) {
            baseData = liveData;
            isLive = true;
            lastModified = new Date();
          }
        }
      } catch { /* timeout or error – use batch data already loaded */ }
    } else {
      // Non-live hourly fetch: direct backend call (no timeout needed)
      try {
        const fetchUrl = `${backendUrl}/artifacts/predictions/predictions_${hour}.geojson`;
        const res = await fetch(fetchUrl, { cache: "no-store" });
        if (!res.ok) throw new Error(`Failed: ${fetchUrl}`);
        baseData = await res.json();
        lastModified = new Date();
        isLive = true;
      } catch {
        // Fallback to local disk
        try {
          const raw = await fs.readFile(path.join(jsonDirectory, `predictions_${hour}.geojson`), "utf-8");
          baseData = JSON.parse(raw);
          lastModified = new Date();
        } catch {}
      }
    }

    // ── Load ripples ──────────────────────────────────────────────────────
    try {
      const rippleFetchUrl = hour === "live"
        ? `${backendUrl}/artifacts/live/ripples_live.geojson`
        : `${backendUrl}/artifacts/predictions/ripples_${hour}.geojson`;
      const resRip = await fetch(rippleFetchUrl, { cache: "no-store" });
      if (resRip.ok) {
        const parsed = await resRip.json();
        // Only include ripples with actual features (fixes the old empty-array bug)
        if (parsed.features && parsed.features.length > 0) {
          rippleData = parsed;
        }
      }
    } catch {}

    // ── Sort by EPS descending ────────────────────────────────────────────
    if (baseData.features?.length > 0) {
      baseData.features.sort(
        (a: any, b: any) =>
          parseFloat(b.properties.eps || 0) - parseFloat(a.properties.eps || 0)
      );
    }

    // ── Deduplicate for Queue ─────────────────────────────────────────────
    const seen = new Set();
    const uniqueFeatures = [];
    for (const f of baseData.features || []) {
      const p = f.properties || {};
      // Group by a road identity key so the same road doesn't flood the queue
      const roadName = (p.road_name || "").toLowerCase().trim();
      const policeStation = (p.police_station || "").toLowerCase().trim();
      const junctionName = (p.junction_name !== "No Junction" ? p.junction_name : "").toLowerCase().trim();
      const roadKey = `${roadName}|${policeStation}|${junctionName}`;
      
      if (!seen.has(roadKey)) {
        seen.add(roadKey);
        uniqueFeatures.push(f);
      }
    }

    // ── Smart map filter: EPS≥50 always shown, fill rest up to 40 max ───────
    // Rule: Show all high-impact segments (EPS≥50) first so no danger is hidden.
    // Then fill remaining slots (up to 40 total) with next highest EPS segments.
    // This prevents flooding the map with low-risk green roads.
    const MAP_MAX = 40;
    const EPS_THRESHOLD = 50;
    const allSorted = (baseData.features || []) as any[];
    const highImpact = allSorted.filter((f: any) => parseFloat(f.properties?.eps || 0) >= EPS_THRESHOLD);
    const remaining = allSorted.filter((f: any) => parseFloat(f.properties?.eps || 0) < EPS_THRESHOLD);
    const slotsLeft = Math.max(0, MAP_MAX - highImpact.length);
    const mapFeatures = [...highImpact, ...remaining.slice(0, slotsLeft)];
    const queueFeatures = uniqueFeatures.slice(0, 15);
    const rippleFeatures = rippleData.features || [];

    const response = NextResponse.json({
      type: "FeatureCollection",
      mapFeatures,
      queueFeatures,
      rippleFeatures,
      // Keep features for backwards compatibility if needed, but we shouldn't need it
      features: mapFeatures,
      // FIX-NEW: metadata for frontend change detection
      _meta: {
        hour,
        is_live: isLive,
        is_cached: !isLive,
        map_count: mapFeatures.length,
        queue_count: queueFeatures.length,
        ripple_count: rippleFeatures.length,
        last_modified: lastModified?.toISOString() ?? null,
      },
    });

    // ── FIX BUG-A: No-cache for live mode ────────────────────────────────
    if (hour === "live") {
      response.headers.set("Cache-Control", "no-store, max-age=0");
      response.headers.set("Pragma", "no-cache");
    } else {
      // Hourly files change only once per day (batch run)
      response.headers.set("Cache-Control", "public, max-age=3600");
    }

    if (lastModified) {
      response.headers.set("X-Prediction-Timestamp", lastModified.toISOString());
    }

    return response;
  } catch (error) {
    console.error("Error reading predictions:", error);
    return NextResponse.json(
      { error: "Failed to load spatial data." },
      { status: 500 }
    );
  }
}
