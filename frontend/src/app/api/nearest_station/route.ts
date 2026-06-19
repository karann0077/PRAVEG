import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const segmentId = searchParams.get("segment_id");

  if (!segmentId) {
    return NextResponse.json({ error: "Missing segment_id parameter" }, { status: 400 });
  }

  try {
    const response = await fetch(`http://localhost:8000/nearest_station?segment_id=${encodeURIComponent(segmentId)}`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`FastAPI returned ${response.status}: ${errorText}`);
    }
    const result = await response.json();
    return NextResponse.json(result);
  } catch (err: any) {
    return NextResponse.json({ error: "Failed to find nearest station", details: err.message }, { status: 500 });
  }
}
