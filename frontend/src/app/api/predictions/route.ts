import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export async function GET() {
  try {
    const jsonDirectory = path.join(process.cwd(), "..", "artifacts", "predictions");
    const filePath = path.join(jsonDirectory, "predictions.geojson");
    const fileContents = await fs.readFile(filePath, "utf8");
    const data = JSON.parse(fileContents);

    if (!data.features || data.features.length === 0) {
      return NextResponse.json(data);
    }

    // Always normalize EPS to 0–100 relative to dataset's own max
    // so the UI always has visual variation regardless of prediction scale
    const allEps = data.features.map((f: any) => parseFloat(f.properties.eps) || 0);
    const maxEps = Math.max(...allEps);
    const minEps = Math.min(...allEps);
    const range = maxEps - minEps || 1;

    data.features = data.features.map((f: any) => {
      const rawEps = parseFloat(f.properties.eps) || 0;
      // Normalize to 0–100, map the top 5% to 90–100 (Red), next 15% to 60–90 (Orange)
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

    // Sort: highest EPS first
    data.features.sort((a: any, b: any) => b.properties.eps - a.properties.eps);

    return NextResponse.json(data);
  } catch (error) {
    console.error("Error reading predictions.geojson:", error);
    return NextResponse.json(
      { error: "Failed to load spatial predictions data." },
      { status: 500 }
    );
  }
}
