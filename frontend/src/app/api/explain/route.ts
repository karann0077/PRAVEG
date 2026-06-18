import { NextResponse } from "next/server";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

// Simple LRU Cache
class LRUCache {
  private cache = new Map<string, any>();
  private maxSize: number;

  constructor(maxSize: number = 100) {
    this.maxSize = maxSize;
  }

  get(key: string) {
    if (!this.cache.has(key)) return null;
    const val = this.cache.get(key);
    this.cache.delete(key);
    this.cache.set(key, val); // Move to most recently used
    return val;
  }

  set(key: string, value: any) {
    if (this.cache.has(key)) {
      this.cache.delete(key);
    } else if (this.cache.size >= this.maxSize) {
      // Evict least recently used (first item)
      this.cache.delete(this.cache.keys().next().value);
    }
    this.cache.set(key, value);
  }
}

const shapCache = new LRUCache(200);

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const segmentId = searchParams.get("segment_id");

  if (!segmentId) {
    return NextResponse.json({ error: "Missing segment_id parameter" }, { status: 400 });
  }

  // Check LRU Cache
  const cached = shapCache.get(segmentId);
  if (cached) {
    return NextResponse.json({ source: "cache", data: cached });
  }

  try {
    // Run python script
    const cmd = `python3 -m parking_engine.explain --segment ${segmentId}`;
    const { stdout, stderr } = await execAsync(cmd, { cwd: "../../" }); // Assuming nextjs is in frontend/

    const result = JSON.parse(stdout);
    
    // Save to LRU Cache
    shapCache.set(segmentId, result);

    return NextResponse.json({ source: "compute", data: result });
  } catch (err: any) {
    return NextResponse.json({ error: "Failed to compute SHAP values", details: err.message }, { status: 500 });
  }
}
