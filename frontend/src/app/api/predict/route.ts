import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const datetime = searchParams.get("datetime");
  const lat = searchParams.get("lat");
  const lon = searchParams.get("lon");
  const topK = searchParams.get("top_k") || "25";

  if (!datetime) {
    return NextResponse.json({ error: "Missing datetime parameter" }, { status: 400 });
  }

  try {
    let url = `${(process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "")}/predict?datetime=${encodeURIComponent(datetime)}&top_k=${topK}`;
    if (lat && lon) {
        url += `&lat=${lat}&lon=${lon}`;
    }

    const response = await fetch(url);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`FastAPI returned ${response.status}: ${errorText}`);
    }
    
    const result = await response.json();
    return NextResponse.json(result);
  } catch (err: any) {
    return NextResponse.json({ error: "Failed to generate predictions", details: err.message }, { status: 500 });
  }
}
