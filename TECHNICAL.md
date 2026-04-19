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
*Status: Pending Implementation*

Focuses on dynamically reducing dimensionality and utilizing BigQuery ML to train predictive models (e.g., Boosted Trees/XGBoost) directly where the data resides.

1. **Agentic Orchestration:** An AI Agent acts as the intelligent trigger, translating user requests for specific stock baskets into ML workflows.
2. **Dynamic Feature Selection:** A Python tool pulls the specific requested basket from the Alpha Vault, applies Correlation Clustering and Random Forest Importance, and aggressively prunes the 400+ columns down to the top regime-stable, cross-asset features.
3. **In-Database Training:** The Agent constructs a BQML `CREATE MODEL` statement using only the optimal features, executing model training with zero data egress.

--- 

## Phase 3: Strategy Backtesting & Evaluation
*Status: Pending Implementation*
* Focuses on vector-based historical simulation to evaluate out-of-sample model performance, calculate risk metrics (Sharpe, Max Drawdown, Win Rate), and visualize equity curves.

---

## Phase 4: Application Orchestration & UI
*Status: Pending Implementation*
* Focuses on the frontend dashboard and middle-tier orchestration, allowing users to interact with the AI Agent, request specific basket analyses, and visualize strategy performance.