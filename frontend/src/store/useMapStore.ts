import { create } from 'zustand';

interface MapState {
  targetHour: string | null;
  setTargetHour: (hour: string) => void;
  selectedEdge: any | null;
  setSelectedEdge: (edge: any | null) => void;
  mapStyle: 'dark' | 'satellite';
  setMapStyle: (style: 'dark' | 'satellite') => void;
  viewState: {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch: number;
    bearing: number;
  };
  setViewState: (viewState: any) => void;
  flyTo: (longitude: number, latitude: number, zoom?: number) => void;
}

export const useMapStore = create<MapState>((set) => ({
  targetHour: null,
  setTargetHour: (hour) => set({ targetHour: hour }),
  selectedEdge: null,
  setSelectedEdge: (edge) => set({ selectedEdge: edge }),
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
}));
