# Quant AI Agent

An autonomous quantitative trading research system powered by Large Language Models (LLMs), FastMCP, and Google Cloud. 

This system utilizes a multi-agent architecture to research, engineer, train, and validate algorithmic trading strategies using strict chronological out-of-sample testing and machine learning.

## 🚀 Current Status
* **Backend & ML Pipeline:** **Fully Operational.** The core infrastructure (BigQuery, Cloud Run, GCS, Firestore) and the asynchronous machine learning pipeline (Triple Barrier Labeling, XGBoost, Backtesting) are successfully deployed and functional.
* **Frontend:** **Work in Progress (WIP).** A Next.js App Router web application built with Tailwind CSS and Shadcn UI. It is currently being integrated with **CopilotKit** for an AI sidebar and WebSockets for sub-second live market charting.

## Improvements
* **Machine Learning Parameters **(Full Automation):**** The current infrastructure is running, but it lacks of dynamic and flexibility.
* **Backtesting Optimisation** The backtesting is working but lack of sophistication on handling complex patterns, leading to a mostly failed strategies. 

## System Architecture

The system enforces a strict Separation of Concerns using a **Three-Agent Architecture**:

1. **The Quant Agent (Orchestrator):** Ingests user requests, gathers macroeconomic context (FRED, Financial News), delegates tasks to sub-agents, and makes the final "Deploy or Reject" capital allocation decision.
2. **The ML Agent (Builder):** Operates securely via Model Context Protocol (MCP). It handles data ingestion, dynamic rolling-window feature engineering, and triggers asynchronous Google Cloud Run jobs to train XGBoost models.
3. **The Backtest Agent (Validator):** Tests the completed models on strictly unseen, out-of-sample chronological data to calculate true financial risk metrics (Sharpe, Max Drawdown, Total Return) without data leakage.

### Cloud Infrastructure
* **Google Cloud Run:** Executes heavy, long-running ML jobs asynchronously to prevent agent timeouts.
* **Google BigQuery:** Serves as the central data warehouse for raw market data, technical indicators, and chronologically split training/testing datasets.
* **Google Cloud Storage (GCS):** Stores compiled `.joblib` models. Employs a "Metadata Sidecar" pattern to stamp true ML metrics directly onto the file for seamless agent retrieval.
* **Google Cloud Firestore:** A serverless NoSQL document database used for ultra-fast, cost-effective transaction logging and agent thought tracing.

## 📂 Project Structure

```text
├── agents/                 # Multi-agent routing and prompt definitions
├── core/
│   └── database.py         # GCP connections (BigQuery, GCS, Firestore) & Garbage Collection
├── frontend/               # Next.js web application (WIP)
│   ├── app/                # Next.js App Router (pages, layouts, API routes)
│   └── ...
├── helpers/                # Core quantitative and machine learning logic
│   ├── backtest_helper.py  # Vectorized backtesting engine
│   ├── data_helper.py      # YFinance/FRED ingestion and indicator calculation
│   └── ml_helper.py        # Triple Barrier Labeling, Clustering, XGBoost training
├── infra/                  # Infrastructure as Code
│   ├── Dockerfile          # Container definition for Cloud Run ML jobs
│   ├── variables.tf        # Terraform variable declarations
│   └── main.tf             # Terraform configuration for GCP resources
├── mcp_server/             # Model Context Protocol (MCP) server
│   ├── data_server.py      # FastMCP tools exposed to the AI Agents
│   └── training_logic.py   # CLI entrypoint for asynchronous Cloud Run ML jobs
├── tests/
│   └── test_data_server_mcp.py # Local ADK agent testing and pipeline execution
├── main.py                 # Primary entry point for the local system
└── requirements.txt        # Python dependencies
```

## 🔬 Key Quantitative Features

* **Noise-Free Feature Selection:** Uses Correlation Clustering and Random Forest feature importance on a strict historical window (e.g., 2022-2025) to prevent regime noise from bleeding into current market predictions.
* **Triple Barrier Method:** Advanced financial labeling technique dynamically adjusted by asset volatility.
* **Incremental Learning via Rolling Windows:** Supports updating existing models with fresh market data without suffering from catastrophic forgetting or look-ahead bias.
* **Chronological Split Validation:** Strictly enforces time-series physics. Models are evaluated entirely out-of-sample to prevent the Catch-22 of data leakage.
* **Automated MLOps Garbage Collection:** The database manager automatically prunes stale `.joblib` models from Google Cloud Storage during incremental training, keeping only the 2 most recent versions per asset to aggressively optimize cloud storage costs.

## 🛠️ Setup & Installation

### Prerequisites
* Python 3.12+
* Google Cloud SDK (`gcloud`) authenticated
* Node.js & npm (for frontend development)
* Terraform (for infrastructure provisioning)

### Backend Initialization
1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment Variables(Create a .env file in the root directory with your GCP credentials and bucket names):**
    ```bash
    GCP_PROJECT_ID="your-project-id"
    GCP_COMPUTE_REGION="us-central1"
    GCS_MODEL_BUCKET="your-project-id-models"
    # ... add DB and API keys as needed
    ```

3. **Infrastructure Configuration (Create a terraform.tfvars file inside the infra/ folder securely pass your GCP project ID to terraform:):**
    ```bash
    project_id = "your-project-id"
    ```
4. **Deploy to Cloud Run:**
* Build and push the Docker container to Google Artifact Registry, then deploy the quant-training-job via Terraform (`terraform apply`) or (`gcloud`).

5. **Running the Agent Locally (* To run the research pipeline locally via the test script in your terminal):**
    ```bash 
    python tests/test_data_server_mcp.py
    ```

## 🗺️ Roadmap
- [x] Establish MCP Server and Firestore/BigQuery database connections.
- [x] Deploy asynchronous ML training to Cloud Run.
- [x] Implement Triple Barrier Labeling and chronological backtesting.
- [x] Integrate multi-agent LLM orchestration.
- [ ] Connect the Next.js frontend via WebSocket for live market charting.
- [ ] Integrate CopilotKit for a unified UI/Agent chat experience.
- [ ] Implement paper-trading execution endpoints.