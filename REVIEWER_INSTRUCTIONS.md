# PRAVEG - Reviewer Instructions

Welcome to the PRAVEG repository! 
To meet the **50MB upload limit**, we have excluded the raw dataset, the node_modules, and the 24-hour prediction cache from this zip file. 

However, we have **included the pre-trained model (`artifacts/parking_model_v5`) and the Live Prediction cache**. This means you can run the live frontend map out of the box without needing to retrain the model or download the dataset!

**Note on API Keys:** The `.env` file containing the required MapMyIndia and TomTom API keys is already included in this zip file. You do **not** need to set up any developer accounts or configure environment variables. It will work completely out-of-the-box.

## How to run the project out-of-the-box (Live Map):
1. Navigate to the `frontend/` directory.
2. Run `npm install` to install frontend dependencies.
3. Run `npm run dev` to start the frontend UI on `localhost:3000`.
4. Open your browser and explore the Tactical Map! The Live Predictions overlay will work immediately using the pre-cached OSM geometries and the trained CatBoost model weights included in the zip.

## How to recreate the entire pipeline (Full Evaluation):
If you would like to run the ML pipeline from scratch (including the 24-hour Time Machine ripples and model retraining), please follow these steps:

1. **Obtain the dataset**: Place the provided hackathon dataset (`jan to may police violation...csv`) into the `dataset/` folder.
2. **Setup Python Environment**: 
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Train the Model**: Run `make train` in the root directory. This will parse the dataset, snap events to OpenStreetMap geometries, and train the V5 CatBoost model. (This takes ~10-15 mins).
4. **Generate the Time Machine Cache**: Run `make predict` to generate all 24-hour prediction ripples.
5. **Start the Live Daemon & Server**:
   ```bash
   python server.py &
   python live_traffic_daemon.py &
   ```
6. **Start the Frontend**: Navigate to `frontend/`, run `npm install`, and `npm run dev`.

Thank you for reviewing PRAVEG!
