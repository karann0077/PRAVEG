# Model And Architecture Notes

The attached architecture points to a road-network, multi-task count forecasting system. The implemented engine follows that structure while keeping the current training run executable with only the provided CSV.

## Chosen Model

- Multi-output LightGBM is used for hourly count forecasting by vehicle class. This matches the PDF's target vector: two-wheeler, car, auto, light-commercial, heavy, and other.
- LightGBM is a strong fit for this dataset because the available signals are tabular, sparse, categorical, spatial, and calendar-heavy. It trains quickly on hundreds of thousands of segment-hour rows and supports a Poisson objective for non-negative count targets.
- A graph neural network such as STGCN is a reasonable future upgrade only after an exact road graph and continuous traffic-flow sensors are available. With the current police event CSV, a tree model with road/cell lags and climatology is more reliable than a deep graph model that would need denser edge-time observations.

## Architecture Mapping

- Phase 1, geospatial graph engineering: `parking_engine.road_graph` provides optional OSMnx nearest-edge matching. The trained artifact in this workspace uses `grid_fallback` because OSMnx and a local road graph are not installed.
- Phase 2, bottleneck simulation: `parking_engine.scoring` maps vehicle classes to physical widths, imputes road widths, applies a peak-hour multiplier, and computes traffic interruption plus emergency-clearance flags.
- Phase 3, multi-task ML engine: `parking_engine.modeling` trains one LightGBM regressor per vehicle-class target through scikit-learn's `MultiOutputRegressor`.
- Phase 4, live calibration: prediction accepts `--live-congestion-multiplier`, representing `duration_in_traffic / duration` from a routing API such as MapmyIndia/Mappls.
- Phase 5, visualization: prediction writes GeoJSON LineStrings with EPS/action properties.

## Practical Accuracy Note

No model can promise perfect future prediction from historical violation events alone. The engine therefore reports temporal test metrics and exposes the uncertainty through predicted counts, traffic-interruption scores, and EPS. Accuracy should improve materially after adding exact OSM road edges, legal parking supply, road widths, event calendars, weather, and live traffic API calibration.
