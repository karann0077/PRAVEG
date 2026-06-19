import { NextResponse } from "next/server";

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
      const firstKey = this.cache.keys().next().value;
      if (firstKey !== undefined) {
        this.cache.delete(firstKey);
      }
    }
    this.cache.set(key, value);
  }
}

const shapCache = new LRUCache(200);

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const segmentId = searchParams.get("segment_id");
  const targetHour = searchParams.get("target_hour") || "live";

  if (!segmentId) {
    return NextResponse.json({ error: "Missing segment_id parameter" }, { status: 400 });
  }

  const cacheKey = `${segmentId}_${targetHour}`;

  // Check LRU Cache
  const cached = shapCache.get(cacheKey);
  if (cached) {
    return NextResponse.json({ source: "cache", data: cached });
  }

  try {
    const response = await fetch(`http://localhost:8000/explain?segment_id=${segmentId}&target_hour=${targetHour}`);
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`FastAPI returned ${response.status}: ${errorText}`);
    }
    const result = await response.json();
    
    // Save to LRU Cache
    shapCache.set(cacheKey, result);

    return NextResponse.json({ source: "compute", data: result });
  } catch (err: any) {
    return NextResponse.json({ error: "Failed to compute SHAP values", details: err.message }, { status: 500 });
  }
}
