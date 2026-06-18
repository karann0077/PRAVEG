import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { edge_id, predicted_eps, actual_accuracy, officer_id } = body;

    if (!edge_id || !actual_accuracy) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    const response = await fetch("http://localhost:8000/feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        edge_id,
        predicted_eps,
        actual_accuracy,
        officer_id: officer_id || "unknown",
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`FastAPI returned ${response.status}: ${errorText}`);
    }

    return NextResponse.json({ success: true });
  } catch (err: any) {
    return NextResponse.json({ error: "Failed to log feedback", details: err.message }, { status: 500 });
  }
}
