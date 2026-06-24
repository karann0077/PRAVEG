.PHONY: all fetch merge train predict

all: fetch merge train predict

fetch:
	@echo "Fetching OSM POIs, Parking Capacities, Weather, and Event Data..."
	# In a full pipeline, these would generate artifacts locally
	# python3 -m parking_engine.feature_poi
	# python3 -m parking_engine.feature_parking
	# python3 -m parking_engine.feature_weather
	# python3 -m parking_engine.feature_events
	@echo "Data fetching complete."

merge:
	@echo "Merging external features into main dataset..."
	# In a full pipeline, this integrates the dataframes
	# python3 -m parking_engine.features
	@echo "Feature engineering complete."

train:
	@echo "Training parking model with full OSM road alignment..."
	python3 -m parking_engine.train \
		--data "dataset/jan to may police violation_anonymized791b166.csv" \
		--out artifacts/parking_model_v5 \
		--min-segment-events 20 \
		--zero-multiplier 1.25 \
		--test-days 21 \
		--n-estimators 300 \
		--use-osm-roads
	@echo "Model training complete."

predict:
	@echo "Generating Predictions and EPS Scores..."
	python3 generate_all_ripples.py
	python3 run_batch.py
	@echo "Batch inference complete."

daemon:
	@echo "Starting Live Traffic Daemon..."
	python3 live_traffic_daemon.py
