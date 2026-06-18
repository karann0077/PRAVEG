import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
  try {
    const metricsPath = path.join(process.cwd(), '../artifacts/parking_model/metrics.json');
    if (!fs.existsSync(metricsPath)) {
        return NextResponse.json({ error: 'Metrics not found at ' + metricsPath }, { status: 404 });
    }
    const data = fs.readFileSync(metricsPath, 'utf-8');
    const metrics = JSON.parse(data);
    return NextResponse.json(metrics);
  } catch (error) {
    return NextResponse.json({ error: 'Failed to load metrics' }, { status: 500 });
  }
}
