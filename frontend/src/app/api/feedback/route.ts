import { NextResponse } from "next/server";
import sqlite3 from "sqlite3";
import { open } from "sqlite";

// Ensure short transactions by initializing connection on demand
async function openDb() {
  return open({
    filename: "../../artifacts/feedback.sqlite",
    driver: sqlite3.Database
  });
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { edge_id, predicted_eps, actual_accuracy, officer_id } = body;

    if (!edge_id || !actual_accuracy) {
      return NextResponse.json({ error: "Missing required fields" }, { status: 400 });
    }

    const db = await openDb();
    
    // Create table if not exists (In production, do this in migrations)
    await db.exec(`
      CREATE TABLE IF NOT EXISTS model_recalibration_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        edge_id TEXT,
        predicted_eps REAL,
        actual_accuracy TEXT,
        officer_id TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // Extremely short transaction: Insert and close immediately to prevent DB locking
    await db.run(
      "INSERT INTO model_recalibration_logs (edge_id, predicted_eps, actual_accuracy, officer_id) VALUES (?, ?, ?, ?)",
      [edge_id, predicted_eps, actual_accuracy, officer_id || "unknown"]
    );

    await db.close();

    return NextResponse.json({ success: true });
  } catch (err: any) {
    return NextResponse.json({ error: "Failed to log feedback", details: err.message }, { status: 500 });
  }
}
