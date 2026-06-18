import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const hourParam = searchParams.get("hour");
  const hour = hourParam ? (hourParam === "live" ? "live" : parseInt(hourParam, 10).toString().padStart(2, "0")) : "live";

  const jsonDirectory = path.join(process.cwd(), "..", "artifacts", "predictions");
  const geojsonPath = path.join(jsonDirectory, `predictions_${hour}.geojson`);
  const ripplePath = path.join(jsonDirectory, `ripples_${hour}.geojson`);

  try {
    let baseData = { type: "FeatureCollection", features: [] };
    let rippleData = { type: "FeatureCollection", features: [] };

    try {
      const file = await fs.readFile(geojsonPath, "utf8");
      baseData = JSON.parse(file);
    } catch (e) {
      // Fallback
      try {
        const fb = await fs.readFile(path.join(jsonDirectory, "predictions.geojson"), "utf8");
        baseData = JSON.parse(fb);
      } catch (err) {}
    }

    try {
      const file = await fs.readFile(ripplePath, "utf8");
      rippleData = JSON.parse(file);
    } catch (e) {}

    // Normalize EPS for base data
    if (baseData.features && baseData.features.length > 0) {
      const allEps = baseData.features.map((f: any) => parseFloat(f.properties.eps) || 0);
      const maxEps = Math.max(...allEps);
      const minEps = Math.min(...allEps);
      const range = maxEps - minEps || 1;

      baseData.features = baseData.features.map((f: any) => {
        const rawEps = parseFloat(f.properties.eps) || 0;
        const normalized = ((rawEps - minEps) / range) * 100;
        return {
          ...f,
          properties: {
            ...f.properties,
            raw_eps: rawEps,
            eps: parseFloat(normalized.toFixed(2)),
          },
        };
      });
      baseData.features.sort((a: any, b: any) => b.properties.eps - a.properties.eps);
    }

    // Combine features (ripples don't need normalization since they use eps_spillover)
    const combinedFeatures = [...(baseData.features || []), ...(rippleData.features || [])];

    return NextResponse.json({
      type: "FeatureCollection",
      features: combinedFeatures
    });
  } catch (error) {
    console.error("Error reading predictions:", error);
    return NextResponse.json(
      { error: "Failed to load spatial data." },
      { status: 500 }
    );
  }
}
