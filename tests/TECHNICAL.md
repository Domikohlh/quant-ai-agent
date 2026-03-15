# Quant AI Agent: Autonomous Multi-Agent Trading System

## 🎯 Objective

The Quant AI Agent is a decoupled, multi-agent microservice architecture designed to automate quantitative financial research, machine learning feature engineering, and vectorized backtesting. By leveraging LLMs (Gemini 3 models) as orchestrators, the system autonomously gathers macroeconomic context, trains predictive XGBoost models on historical data, runs out-of-sample financial simulations, and synthesizes the results into a final "Deploy or Reject" capital allocation report.

# 🏗️ System Architecture

## The repository is strictly divided into four functional layers:

- Frontend (Next.js & CopilotKit): A React-based chat interface (frontend/app/page.tsx) that captures user prompts and streams them to the backend API.
- The Orchestrator (Google ADK): A FastAPI backend (tests/test_data_server_mcp.py) that hosts the LLM personas and manages the multi-turn agent execution loop.
- The Tool Gateway (FastMCP): A Server-Sent Events (SSE) server (mcp_server/data_server.py) that exposes Python data retrieval and compute functions as strictly defined JSON-RPC tools.
- Compute & Infrastructure (GCP): Terraform-managed infrastructure (infra/main.tf) utilizing BigQuery for market data, Google Cloud Storage (GCS) for serialized .joblib models, Firestore for QA tracking, and Cloud Run for asynchronous ML training

# 🤖 Agent Personas

## The orchestration layer utilizes the "Agent-as-a-Tool" pattern, isolating responsibilities into specific personas:

- quant_agent (Lead Strategist): Manages sub-agents, evaluates macroeconomic narratives against ML/Backtest metrics, and makes the final deployment verdict.
- research_agent: Fetches real-time qualitative data via Brave Search (search_financial_news) and FRED (update_macro_data).
- ml_agent: Handles data ingestion, Triple Barrier feature engineering, and triggers remote XGBoost training pipelines.
- backtest_agent: Executes strict out-of-sample vectorized backtesting on the trained models to calculate Max Drawdown, Sharpe Ratio, and Win Rate.

# 🚀 Progress & Current State

- Core Tools Operational: The FastMCP server successfully executes complex financial pipelines, including check_existing_dataset, update_stock_data, and get_latest_model_uri.
- Asynchronous Compute: Heavy machine learning tasks (ml_feature_analysis and ml_train_basket_model) have been offloaded to separate GCP Cloud Run Jobs to prevent API gateway timeouts during model training.
- Backend Loop Integrity: By hiding raw tools inside sub-agents, the system successfully bypasses single-turn UI framework limitations (CopilotKit) and allows agents to loop autonomously on the backend.
- Agent is able to look at the Alpaca account.

# 🛠️ Recent Improvements

- Cost Optimization: Migrated API routing from the paid Vertex AI enterprise SDK to Google AI Studio's Pay-As-You-Go tier, significantly reducing infrastructure and search grounding overhead.
- Schema Flattening: Updated MCP return types to output flat dictionaries instead of strings, bypassing FastMCP's redundant JSON wrapping (x-fastmcp-wrap-result) and curing LLM infinite tool-call loops.
- Tools are filtered by 'tool_filter' to avoid tool hallucination.

# 🚧 Current Bottlenecks & Directions

- ML agent has a logical conflict. 
- The LLM continuously reruns the ML module on CloudRun service 
- Need to ask the research agent to provide more information instead of only 3 bullet points.
- Increase the complexity and robustness of backtesting strategy
- Session implementation
- Web re-design
- Frontend showing the training processes

