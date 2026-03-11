# Quant AI Agent

An enterprise-grade, autonomous quantitative trading research system powered by Large Language Models (LLMs), FastMCP, and Google Cloud. 

This system utilizes a multi-agent architecture to research, engineer, train, and validate algorithmic trading strategies using strict chronological out-of-sample testing and machine learning.

## 🚀 Current Status
* **Backend & ML Pipeline:** **Fully Operational.** The core infrastructure (BigQuery, Cloud Run, GCS) and the asynchronous machine learning pipeline (Triple Barrier Labeling, XGBoost, Backtesting) are successfully deployed and functional.
* **Frontend:** **Work in Progress (WIP).** A Next.js-based web interface is currently under development to provide live charting and a Copilot chat interface.

## Improvements
* **Machine Learning Parameters **(Full Automation):**** The current infrastructure is running, but it lacks of dynamic and flexibility.
* **Backtesting Optimisation** The backtesting is working but lack of sophistication on handling complex patterns, leading to a mostly failed strategies. 

## 🧠 System Architecture

The system enforces a strict Separation of Concerns using a **Three-Agent Architecture**:

1. **The Quant Agent (Orchestrator):** Ingests user requests, gathers macroeconomic context (FRED, Financial News), delegates tasks to sub-agents, and makes the final "Deploy or Reject" capital allocation decision.
2. **The ML Agent (Builder):** Operates securely via Model Context Protocol (MCP). It handles data ingestion, dynamic rolling-window feature engineering, and triggers asynchronous Google Cloud Run jobs to train XGBoost models.
3. **The Backtest Agent (Validator):** Tests the completed models on strictly unseen, out-of-sample chronological data to calculate true financial risk metrics (Sharpe, Max Drawdown, Total Return) without data leakage.

### Cloud Infrastructure
* **Google Cloud Run:** Executes heavy, long-running ML jobs asynchronously to prevent agent timeouts.
* **Google BigQuery:** Serves as the central data warehouse for raw market data, technical indicators, and chronologically split training/testing datasets.
* **Google Cloud Storage (GCS):** Stores compiled `.joblib` models. Employs a "Metadata Sidecar" pattern to stamp true ML metrics directly onto the file for seamless agent retrieval.
* **Cloud SQL & Firestore:** Manages transaction logging and agent thought tracing.

## 📂 Project Structure

```text
├── agents/                 # Multi-agent routing and prompt definitions
├── core/
│   └── database.py         # GCP connections (BigQuery, GCS, SQL, Firestore) & Garbage Collection
├── frontend/               # Next.js web application (WIP)
│   ├── app/                # Next.js App Router (pages, layouts, API routes)
│   └── ...
├── helpers/                # Core quantitative and machine learning logic
│   ├── backtest_helper.py  # Vectorized backtesting engine
│   ├── data_helper.py      # YFinance/FRED ingestion and indicator calculation
│   └── ml_helper.py        # Triple Barrier Labeling, Clustering, XGBoost training
├── infra/                  # Infrastructure as Code
│   ├── Dockerfile          # Container definition for Cloud Run ML jobs
│   └── main.tf             # Terraform configuration for GCP resources
├── mcp_server/             # Model Context Protocol (MCP) server
│   ├── data_server.py      # FastMCP tools exposed to the AI Agents
│   └── training_logic.py   # CLI entrypoint for asynchronous Cloud Run ML jobs
├── tests/
│   └── test_data_server_mcp.py # Local ADK agent testing and pipeline execution
├── main.py                 # Primary entry point for the local system
└── requirements.txt        # Python dependencies