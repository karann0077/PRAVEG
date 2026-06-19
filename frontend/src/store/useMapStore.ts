import { create } from 'zustand';

interface MapState {
  targetHour: string | null;
  setTargetHour: (hour: string) => void;
  selectedEdge: any | null;
  setSelectedEdge: (edge: any | null) => void;
  selectedHeatmapZone: any | null;
  setSelectedHeatmapZone: (zone: any | null) => void;
  isSimulatingResolution: boolean;
  setIsSimulatingResolution: (val: boolean) => void;
  activeLayerMode: 'tactical' | 'heatmap';
  setActiveLayerMode: (mode: 'tactical' | 'heatmap') => void;
  isSimulationActive: boolean;
  setIsSimulationActive: (val: boolean) => void;
  mapStyle: 'dark' | 'satellite' | 'light';
  setMapStyle: (style: 'dark' | 'satellite' | 'light') => void;
  viewState: {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch: number;
    bearing: number;
  };
  setViewState: (viewState: any) => void;
  flyTo: (longitude: number, latitude: number, zoom?: number) => void;
  geoData: any | null;
  setGeoData: (data: any | null) => void;

  // Resolution impact data from backend
  resolutionImpact: any | null;
  setResolutionImpact: (data: any | null) => void;

  // Nearest station info
  nearestStation: any | null;
  setNearestStation: (data: any | null) => void;

  // Heatmap weight mode toggle
  heatmapWeightMode: 'violation_density' | 'congestion_impact';
  setHeatmapWeightMode: (mode: 'violation_density' | 'congestion_impact') => void;
}

export const useMapStore = create<MapState>((set) => ({
  targetHour: "live",
  setTargetHour: (hour) => set({ targetHour: hour }),
  selectedEdge: null,
  setSelectedEdge: (edge) => set({ selectedEdge: edge, resolutionImpact: null, nearestStation: null }),
  selectedHeatmapZone: null,
  setSelectedHeatmapZone: (zone) => set({ selectedHeatmapZone: zone }),
  isSimulatingResolution: false,
  setIsSimulatingResolution: (val) => set({ isSimulatingResolution: val }),
  activeLayerMode: 'tactical',
  setActiveLayerMode: (mode) => set({ activeLayerMode: mode }),
  isSimulationActive: false,
  setIsSimulationActive: (val) => set({ isSimulationActive: val }),
  mapStyle: 'dark',
  setMapStyle: (style) => set({ mapStyle: style }),
  viewState: {
    longitude: 77.5946,
    latitude: 12.9716,
    zoom: 13,
    pitch: 0,
    bearing: 0,
  },
  setViewState: (viewState) => set({ viewState }),
  flyTo: (longitude, latitude, zoom = 16) =>
    set((state) => ({
      viewState: {
        ...state.viewState,
        longitude,
        latitude,
        zoom,
        pitch: 45,
      },
    })),
  geoData: null,
  setGeoData: (data) => set({ geoData: data }),

  resolutionImpact: null,
  setResolutionImpact: (data) => set({ resolutionImpact: data }),
  nearestStation: null,
  setNearestStation: (data) => set({ nearestStation: data }),
  heatmapWeightMode: 'violation_density',
  setHeatmapWeightMode: (mode) => set({ heatmapWeightMode: mode }),
}));
