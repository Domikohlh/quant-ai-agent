# Quantitative Trading Pipeline: Technical Architecture

This document outlines the technical architecture, data flow, and infrastructure design for the quantitative trading pipeline built on Google Cloud Platform (GCP). The system is designed to be highly modular, cost-efficient, and scalable, transitioning from raw market data ingestion to advanced machine learning and backtesting.

---

## Phase 1: Data Processing, Feature Expansion, and Labeling
*Status: Implemented & Verified*

The primary objective of Phase 1 is to establish a robust, automated, and idempotent data pipeline. It maintains a pristine universe of historical market data, calculates an expansive "Alpha Vault" of hundreds of technical/regime-aware features, and pre-labels targets using path-dependent methods. This phase operates entirely autonomously in the background.

### 1.1 Architecture & Component Flow
The ingestion pipeline leverages serverless GCP components to minimize idle compute costs:

1. **Configuration Store (Firestore):** A NoSQL document (`config/trading_universe`) acts as the dynamic configuration layer. It stores the array of target tickers, allowing universe expansion without code deployments.
2. **Compute (Cloud Run Jobs):** A containerized Python execution environment runs the data extraction, heavy feature expansion, and transformation scripts.
3. **Trigger (Cloud Scheduler):** A cron job triggers the Cloud Run Job daily after market close (EST).
4. **Data Warehouse (BigQuery):** The final destination for the processed panel data, acting as a columnar feature store.

### 1.2 BigQuery Data Model
Data is stored in a strict **Long Panel Data** format to enable efficient cross-sectional machine learning.

* **Dataset:** `market_data`
* **Main Table:** `historical_data`
* **Staging Table:** `staging_panel`
* **Optimization Strategy:**
  * **Time-Partitioning:** Partitioned by `DATE(timestamp)` to ensure downstream queries only scan relevant data, cutting costs significantly.
  * **Clustering:** Clustered by `ticker` to physically sort the data, optimizing queries filtering for specific assets or baskets.
  * **Columnar Storage:** Ensures the 400+ feature columns cost nothing in compute unless explicitly queried during Phase 2.

### 1.3 Ingestion Logic: Batching & Incremental Load
To prevent redundant API calls, avoid BigQuery partition quota limits, and guarantee data integrity, the pipeline uses a Batched Staging & MERGE pattern:

1. **State Check:** The engine queries BigQuery for the absolute `MAX(timestamp)` per ticker.
2. **Buffer Extraction:** It requests data from the external provider (`yfinance`) starting from the `MAX(timestamp)` **minus a 90-day rolling buffer** to allow complex indicators to "warm up."
3. **Transformation & Expansion:** Base indicators, permutation windows, and target labels are calculated in-memory.
4. **Batch Collection:** Net-new rows for all tickers are collected and concatenated into a single master dataframe.
5. **Staging Upload:** The master dataframe is uploaded to the temporary `staging_panel` table using `WRITE_TRUNCATE`.
6. **Self-Healing MERGE:** A BigQuery `MERGE` statement is executed against the main table. 
   * `WHEN NOT MATCHED`: Inserts strictly new rows.
   * `WHEN MATCHED`: Updates existing rows to backfill time-lagged Target Labels (e.g., resolving `NaN` values as future market data arrives).

### 1.4 Quantitative Feature Engineering & Labeling
Phase 1 transforms standard OHLCV data into a massive, machine-learning-ready matrix (~432 columns). Float columns are downcast to `float32` for memory/storage optimization.

**A. Base Technical Indicators:**
* **Trend & Momentum:** SMA (50, 200), MACD (multiple configurations), RSI (14), ROC, TRIX, PPO, APO.
* **Volatility & Volume:** Bollinger Bands, ATR (14), VWAP.
* **Statistical/Relative:** Z-Score (30-period), 20-period Rolling Percentile Rank.

**B. Dimensionality Multipliers (Feature Expansion):**
To capture market regime stability and acceleration, all base indicators are expanded across multiple permutation windows (`[1, 3, 6, 12, 24, 36, 48, 72]`).
* **Momentum/Acceleration (`_diff`):** Calculates the rate of change of the indicator across the window to identify signal velocity.
* **Volatility/Noise (`_vol`):** Calculates the rolling standard deviation of the indicator to measure signal stability and regime shifts.

**C. Vectorized Target Generation (Triple Barrier Labeling):**
Solves the path-dependency problem of financial time-series forecasting. 
* Uses a 20-day rolling volatility metric to dynamically set upper (profit-taking) and lower (stop-loss) barriers.
* Looks forward across multiple horizons (e.g., 5-day, 10-day) to assign labels: `1` (Hit Upper), `-1` (Hit Lower), or `0` (Time Barrier/Sideways).

---

## Phase 2: Machine Learning & MLOps (BQML)
*Status: Implemented (Asynchronous MCP Pipeline)*

Phase 2 focuses on dynamically reducing the dimensionality of the "Alpha Vault" (Phase 1) and utilizing BigQuery ML (BQML) to train predictive multi-class classification models directly where the data resides. To prevent LLM context timeouts and support stateless deployments, the entire ML training loop is heavily decoupled into an asynchronous, "Fire-and-Forget" architecture.

### 2.1 Agentic Orchestration (FastMCP)
The AI Agent acts as the intelligent orchestrator, interacting with a dedicated Model Context Protocol (MCP) server. To accommodate the heavy compute time of machine learning without freezing the Agent, the pipeline relies on two distinct tools:
1. **`start_model_pipeline` (Asynchronous Trigger):** The Agent submits a Human-In-The-Loop (HITL) approved basket of tickers and the desired algorithm. The tool spawns a background Python thread and instantly returns a `Job ID` to the Agent, freeing the LLM to continue chatting with the user.
2. **`check_pipeline_logs` (State Reader):** The Agent can dynamically query this tool to read the real-time processing state (e.g., "Downloading", "Training", "Completed") or retrieve the final evaluation metrics.

### 2.2 Dynamic Dimensionality Reduction
Because the predictive power of technical features shifts drastically depending on the specific combination of tickers in a basket, feature selection cannot be pre-calculated. It is executed dynamically in Python memory at training time:
* **Target Basket Extraction:** The background thread pulls the ~432 features specifically for the requested tickers.
* **Correlation Clustering:** Drops highly collinear features (Pearson correlation > 0.85) to reduce noise.
* **Random Forest Importance:** Fits a fast Random Forest Classifier against the `target_5d` labels to identify the cross-asset regime-stable features, aggressively pruning the dataset down to the Top 20 most impactful columns.

### 2.3 Zero-Egress BQML Training
Once the Top 20 features are identified, the Python thread constructs a dynamic BQML `CREATE MODEL` SQL statement. The model is trained directly inside BigQuery, eliminating massive data egress costs.
* **Algorithm Constraints:** To prevent LLM hallucination and ensure mathematical compatibility with Triple Barrier discrete targets, the Agent is strictly restricted to two institutional baselines:
  * `BOOSTED_TREE_CLASSIFIER` (XGBoost): The default heavy lifter for capturing complex, non-linear market interactions.
  * `LOGISTIC_REG` (Penalized Logistic Regression): The strict linear baseline used to test if complex models are simply overfitting noise.

### 2.4 Automated Evaluation & "PRIME" Promotion
Following training, the background thread automatically executes `ML.EVALUATE` and applies rigid quantitative gating before allowing a model into production.
* **The Mathematical Bouncer:** The model must achieve a baseline **Accuracy > 50%**. Because the Triple Barrier labels include a heavy class imbalance of `0` (sideways market), any model below 50% is deemed mathematically blind and is instantly dropped via a SQL `DROP MODEL` command.
* **Secondary Analysis:** If the model passes, it is saved to BigQuery as a `PRIME` model. The pipeline extracts the **Precision, Recall, F1 Score, and ROC AUC**. The Agent uses these advanced metrics to advise the user on the model's true trading viability (e.g., identifying models that pass the accuracy filter but have a dangerously low precision/high false-positive rate).

### 2.5 Stateless Logging Architecture (Firestore)
To support deployment on ephemeral environments like Vertex AI Agent Engine, local file logging is entirely abandoned. 
* The pipeline utilizes **Google Cloud Firestore** as a real-time state machine. 
* Logs are written to `document(target_ticker)` rather than by Job ID. This overwrite design natively tracks the status of the ML pipeline across disconnected SSE or Stdio connections while keeping database storage costs near absolute zero.

--- 

## Phase 3: Strategy Backtesting & Evaluation
*Status: Pending Implementation*
* Focuses on vector-based historical simulation to evaluate out-of-sample model performance, calculate risk metrics (Sharpe, Max Drawdown, Win Rate), and visualize equity curves.

---

## Phase 4: Application Orchestration & UI
*Status: Pending Implementation*
* Focuses on the frontend dashboard and middle-tier orchestration, allowing users to interact with the AI Agent, request specific basket analyses, and visualize strategy performance.