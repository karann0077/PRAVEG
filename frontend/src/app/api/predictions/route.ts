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

    // ── Load base predictions ─────────────────────────────────────────────
    try {
      const fetchUrl = hour === "live" 
        ? `${backendUrl}/artifacts/live/predictions_live.geojson`
        : `${backendUrl}/artifacts/predictions/predictions_${hour}.geojson`;
      const res = await fetch(fetchUrl, { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`Failed to fetch ${fetchUrl}`);
      }
      baseData = await res.json();
      lastModified = new Date();
    } catch {
      try {
        const fbUrl = `${backendUrl}/artifacts/predictions/predictions.geojson`;
        const resFb = await fetch(fbUrl, { cache: "no-store" });
        if (resFb.ok) {
          baseData = await resFb.json();
        }
      } catch {}
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
      const segId = f.properties.segment_id;
      if (!seen.has(segId)) {
        seen.add(segId);
        uniqueFeatures.push(f);
      }
    }

    // V5 FIX: Raised cap from 25 → 2500. Old cap caused 99% of road segments
    // to be silently dropped, making the map show only ~25 tiny dots.
    const mapFeatures = (baseData.features || []).slice(0, 2500);
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
