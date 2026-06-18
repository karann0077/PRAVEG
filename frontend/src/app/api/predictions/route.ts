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

    if (baseData.features && baseData.features.length > 0) {
      baseData.features.sort((a: any, b: any) => parseFloat(b.properties.eps || 0) - parseFloat(a.properties.eps || 0));
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
