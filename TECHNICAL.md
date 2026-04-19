# Quantitative Trading Pipeline: Technical Architecture

This document outlines the technical architecture, data flow, and infrastructure design for the quantitative trading pipeline built on Google Cloud Platform (GCP). The system is designed to be highly modular, cost-efficient, and scalable, transitioning from raw market data ingestion to advanced machine learning and backtesting.

---

## Phase 1: Data Processing and Ingestion
*Status: Implemented & Verified*

The primary objective of Phase 1 is to establish a robust, automated, and idempotent data pipeline that maintains a pristine universe of historical market data and pre-calculated technical indicators. This phase operates entirely autonomously in the background.

### 1.1 Architecture & Component Flow
The ingestion pipeline leverages serverless GCP components to minimize idle compute costs:

1. **Configuration Store (Firestore):** A NoSQL document (`config/trading_universe`) acts as the dynamic configuration layer. It stores the array of target tickers (e.g., Tech mega-caps, ETFs, Semiconductor stocks). This allows universe expansion without code deployments.
2. **Compute (Cloud Run Jobs):** A containerized Python execution environment runs the data extraction and transformation scripts.
3. **Trigger (Cloud Scheduler):** A cron job triggers the Cloud Run Job daily after market close.
4. **Data Warehouse (BigQuery):** The final destination for the processed panel data.

### 1.2 BigQuery Data Model
Data is stored in a strict **Long Panel Data** format to enable efficient cross-sectional machine learning.

* **Dataset:** `market_data`
* **Main Table:** `historical_data`
* **Staging Table:** `staging_panel`
* **Optimization Strategy:**
  * **Time-Partitioning:** Partitioned by `DATE(timestamp)`. This ensures downstream backtests querying specific years only scan relevant data, cutting query costs significantly.
  * **Clustering:** Clustered by `ticker`. This physically sorts the data to optimize queries filtering for specific assets.

### 1.3 Ingestion Logic: Batching & Incremental Load
To prevent redundant API calls, avoid BigQuery partition quota limits, and guarantee data integrity, the pipeline uses a Batched Staging & MERGE pattern:

1. **State Check:** For each ticker in the universe, the engine queries BigQuery for the absolute `MAX(timestamp)`.
2. **Buffer Extraction:** It requests data from the external provider (`yfinance`) starting from the `MAX(timestamp)` **minus a 60-day rolling buffer**.
3. **Transformation:** Technical indicators are calculated on this buffered dataset.
4. **Precision Slicing:** The dataframe is sliced to isolate strictly net-new rows (`df[df['timestamp'] > MAX(timestamp)]`).
5. **Batch Collection:** Net-new rows for all tickers are collected in memory and concatenated into a single master dataframe.
6. **Staging Upload:** The master dataframe is uploaded to the temporary `staging_panel` table using `WRITE_TRUNCATE` (overwrite).
7. **Safe MERGE:** A BigQuery `MERGE` statement is executed to insert data from the staging table into the `historical_data` table. The `ON T.ticker = S.ticker AND T.timestamp = S.timestamp` condition strictly guarantees **zero duplicate rows**, even if the pipeline is triggered redundantly.

### 1.4 Technical Indicators (Feature Engineering)
The following quantitative features are pre-calculated using `pandas_ta`. Float columns are downcast to `float32` for storage optimization.

* **Trend:** Simple Moving Averages (SMA 50, SMA 200), MACD variations, Price Percentage Oscillator (PPO), Absolute Price Oscillator (APO).
* **Momentum:** Relative Strength Index (RSI 14), Rate of Change (ROC), TRIX.
* **Volatility:** Bollinger Bands, Average True Range (ATR 14).
* **Statistical/Relative:** Z-Score (30-period), 20-period Rolling Percentile Rank.
* **Volume:** Volume Weighted Average Price (VWAP).

---

## Phase 2: Machine Learning & MLOps (BQML)
*Status: Pending Implementation*
* Focuses on utilizing BigQuery ML to train predictive models (e.g., Boosted Trees) directly where the data resides, eliminating data egress and complex custom container management. 

## Phase 3: Strategy Backtesting & Evaluation
*Status: Pending Implementation*
* Focuses on vector-based historical simulation (e.g., Triple Barrier method) to evaluate model performance, calculate risk metrics (Sharpe, Max Drawdown), and establish out-of-sample validity.

## Phase 4: Application Orchestration & UI
*Status: Pending Implementation*
* Focuses on the frontend dashboard and middle-tier orchestration, allowing users to interact with the pipeline, modify the data universe, and visualize strategy performance.