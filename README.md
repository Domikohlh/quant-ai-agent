# Quant AI Agent 🚀

**A Multi-Agent System for Quantitative Finance on GCP**

`quant_AI_agent` is an autonomous trading system built with **LangGraph** and **Google Gemini** models. It orchestrates specialized AI agents to analyze market data, assess sentiment, manage risk, and execute trades via Interactive Brokers.

---

## 🏗 Architecture

The system operates on a **Hub-and-Spoke** graph architecture:

1.  **Supervisor (Gemini 3.0 Pro):** Orchestrates workflow and handles errors.
2.  **Data Engineer (Gemini 2.5 Flash):** Fetches OHLCV, VIX, and macro data.
3.  **Sentiment Analyst (Gemini 3.0 Flash):** Scans news/tweets with massive context window.
4.  **Quant Analyst (Gemini 3.0 Pro):** Calculates indicators & generates signals.
5.  **Risk Manager (Gemini 3.0 Pro):** Validates signals against portfolio constraints.
6.  **Executor (Gemini 2.5 Flash):** Handles order execution (TWAP/VWAP) with Human-in-the-Loop.

**Infrastructure:**
* **Compute:** Google Cloud Run (Agents) + Compute Engine (IB Gateway/MCP).
* **Database:** SQLite (via MCP) for trade logs.
* **Observability:** LangSmith.

---

## ⚡️ Quick Start

### Prerequisites
* Python 3.11+
* Google Cloud Project (with Vertex AI API enabled)
* Interactive Brokers Account (Paper Trading recommended)
* LangSmith API Key

### Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/your-username/quant_AI_agent.git](https://github.com/your-username/quant_AI_agent.git)
    cd quant_AI_agent
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment:**
    Copy `.env.example` to `.env` and fill in your keys:
    ```bash
    cp .env.example .env
    ```

### Usage

**Run locally (Development):**
```bash
python main.py --mode=dev
