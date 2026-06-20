# Frontend Architecture (The Dashboard)

This document explains the Frontend User Interface of PRAVEG. It is a highly interactive, modern web application built for police commanders to visualize and action parking violations.

## Overview
The frontend is built using **Next.js** (React) and styled with **Tailwind CSS**. It uses **Zustand** for state management and **Deck.GL / React-Map-GL** for high-performance 3D mapping.

## Directory Structure & File Explanations

All code lives in the `frontend/` directory, specifically inside `frontend/src/`.

### 1. The App Router (`src/app/`)
Next.js uses folder-based routing.
- **`page.tsx`**: The main dashboard page. This is the entry point that mounts the Map and all the UI panels.
- **`globals.css`**: Contains global styling and Tailwind directives.
- **`api/`**: The Backend-for-Frontend (BFF). These are Next.js route handlers that proxy requests to the Python FastAPI server. This avoids CORS issues and keeps API keys secret. For example, `src/app/api/predict/route.ts` securely forwards requests to the Python backend.

### 2. State Management (`src/store/`)
- **`useMapStore.ts`**: The "brain" of the frontend. Because the map, the left panel, and the right panel all need to talk to each other, they share data here. It stores things like:
  - `selectedEdge`: Which road the user clicked on.
  - `targetHour`: Whether the timeline is set to "LIVE" or "+3h".
  - `patrolRouteGeometry`: The simulated driving route for a tow truck.

### 3. The Components (`src/components/`)
This is where the visible UI pieces live:

- **`TacticalMap.tsx`**: The massive 3D map in the background. It renders multiple layers:
  - *PathLayer*: Draws the glowing red/orange lines over roads where violations are predicted.
  - *IconLayer*: Draws the pulsing "Ripples" that show how traffic jams spread.
  - *TripsLayer*: Animates the blue glowing dot simulating a police tow truck driving to the scene.

- **`DispatchQueue.tsx`**: The **Left Panel**. 
  - Lists the top 15 predicted hotspots in the city, sorted by their Enforcement Priority Score (EPS).
  - Displays the "Road Blockage %" so commanders instantly know how choked a road is.

- **`PhysicsInspector.tsx`**: The **Right Panel**. 
  - Opens when you click on a specific road. 
  - **Traffic Flow Recovery**: Shows a visual progress bar of current traffic speed vs. cleared speed.
  - **Why this Alert?**: Displays the SHAP explanations (e.g. "School pickup hour rush").
  - **Action Button**: Allows the commander to "Dispatch" a team, triggering the map animation.

- **`TimeMachine.tsx`**: The **Bottom Slider**.
  - Allows the commander to scrub forward in time (LIVE, +3h, +6h, +9h). When changed, it updates the `targetHour` in the store, which triggers the map to download the future prediction files.

- **`ZoneCommander.tsx`**: The **Top Bar**.
  - Displays high-level global metrics like the current time, total city-wide economic loss, and system status.

## How it works (Step-by-Step)
1. User opens the website. `page.tsx` loads the `TacticalMap` and UI components.
2. The `TacticalMap` looks at the `useMapStore` to see the `targetHour` (defaults to "live").
3. The map fetches `/api/predictions?hour=live`.
4. It receives the GeoJSON file containing hundreds of roads and renders them as glowing lines.
5. The user clicks a glowing red road. The `TacticalMap` updates `selectedEdge` in the store.
6. The `PhysicsInspector` detects the click, slides in from the right, fetches deeper data (like SHAP explanations and Traffic Recovery stats), and presents it to the user.
