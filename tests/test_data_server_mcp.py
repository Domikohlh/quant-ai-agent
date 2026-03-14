import os
import sys
import logging
import json 
from pathlib import Path
from dotenv import load_dotenv
from contextlib import asynccontextmanager

import copy  # <--- NEW
import io    # <--- NEW

# --- FIX FOR ADK DEEPCOPY CRASH ---
# Prevents Python from panicking when ag_ui_adk tries to duplicate 
# active terminal streams or internal loggers for a new chat session.
copy._deepcopy_dispatch[io.TextIOWrapper] = lambda x, memo: x

# (Optional safeguard for httpx network locks, which sometimes fail next)
import threading
copy._deepcopy_dispatch[type(threading.Lock())] = lambda x, memo: x

# 1. Google Agent + MCP tools
from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams, StdioConnectionParams
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types
from mcp import StdioServerParameters 

# 2. Frontend & API
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Specifically boost the noise for the MCP and ADK libraries
logging.getLogger("google.adk").setLevel(logging.DEBUG)
logging.getLogger("mcp").setLevel(logging.DEBUG)
logging.getLogger("httpcore").setLevel(logging.DEBUG) # Shows raw network requests
 
# --- Path & Env Setup ---
current_test_dir = Path(__file__).resolve().parent
project_root = current_test_dir.parent
server_script_path = project_root / "mcp_server/data_server.py"

load_dotenv(project_root / ".env")

# Ensure GCP Project is set
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_AI_REGION", "global")
DATA_SERVER_URL = os.getenv("DATA_SERVER_URL")

if not server_script_path.exists():
    raise FileNotFoundError(f"Server script not found at: {server_script_path}")

if not PROJECT_ID:
    raise ValueError("GCP_PROJECT_ID is missing from .env")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION
#os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

# Avoid rate limits and temorary service unavailability 
retry_config = types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
)

# --- The Vertex AI Agent ---
print(f"\n--- 🔌 Connecting to MCP Server: {server_script_path.name} ---")

connection_params = SseConnectionParams(
url=DATA_SERVER_URL, 
headers={
    "Authorization": "Bearer YOUR_TOKEN"
},
timeout=600
)

alpaca_env = os.environ.copy()
alpaca_env.update({
    "ALPACA_API_KEY": os.getenv("ALPACA_API_KEY"),
    "ALPACA_SECRET_KEY": os.getenv("ALPACA_SECRET_KEY")
})

alpaca_ser = StdioServerParameters(
    command="uvx",
    args=["alpaca-mcp-server", "serve"],
    env=alpaca_env
    )

alpaca_con = StdioConnectionParams(server_params=alpaca_ser, timeout=300)
alpaca_tool = McpToolset(connection_params=alpaca_con)

# 2. Initialize Toolset
# This connects to the remote server via SSE instead of spawning a local process
ml_toolset = McpToolset(
    connection_params=connection_params,
    tool_filter=[
        "check_existing_dataset", 
        "update_stock_data", 
        "ml_feature_analysis", 
        "ml_train_basket_model", 
        "get_latest_model_uri"
    ]
)

backtest_toolset = McpToolset(
    connection_params=connection_params,
    tool_filter=["backtest_model_strategy"]
)

research_toolset = McpToolset(
    connection_params=connection_params,
    tool_filter=["search_financial_news", "update_macro_data"]
)
# 3. Initialize Client in VERTEX AI Mode
# setting vertexai=True tells the SDK to use your GCP Project Quota & Auth
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

print(f"✅ Client initialized for Vertex AI Project: {PROJECT_ID}")

fast_model_id = "gemini-3-flash-preview" 
deep_model_id = "gemini-3-flash-preview"


ml_instruction ="""
Role: To generate clean data, engineer features, and train the predictive model.

SYSTEM INSTRUCTION: ML AGENT
You are the Lead Machine Learning Engineer for a quantitative trading desk. Your sole objective is to build and retrieve robust, noise-free predictive models for the target asset requested by the Lead Quant.

Execution Protocol:
1. Data Discovery: Accept the target ticker and strategy basket from the prompt. Immediately call check_existing_dataset. Read the output and strictly follow its instructions regarding which tools to skip or run.
2. Data Ingestion (If needed): If raw data is missing, call update_stock_data using a safe interval (e.g., 1h or 1d).
3. Feature Engineering (Strict Rolling Window): If training data is missing, call ml_feature_analysis.
4. You MUST set training_start_date to "2022-01-01" to eliminate 2021 market noise.
5. You MUST calculate training_end_date as exactly 30 days prior to today's date.
6. The Handoff Loop: ml_feature_analysis is an asynchronous cloud job. Enter a polling loop: wait 60 seconds, then call check_existing_dataset. Do NOT proceed until the data is explicitly "✅ FOUND".
7. Model Training: Call ml_train_basket_model using the exact same dynamic dates calculated in Step 3.
8. Retrieval & QA Gate: Call get_latest_model_uri. If the model is too young (still training), wait and retry. 
   - IF REJECTED (<50% accuracy): You MUST NOT pass the model to the Backtest Agent. Adjust your hyperparameters via the `custom_params` dictionary (e.g., change `n_estimators`, `learning_rate`, `max_depth`) and call `ml_train_basket_model` again. You may retry up to 3 times.
   - IF SUCCESS: Output the exact Model URI and the attached ML Metrics to pass back to the Lead Quant.
9. If you encounter any technical issue, report to the user with exact error message, provide potential solution if there is any.

CRITICAL ASYNCHRONOUS RULE:
When you call 'ml_train_basket_model', the system will trigger a remote Cloud Run job that takes 5 minutes.
- You MUST NOT call 'get_latest_model_uri' immediately.
- You MUST NOT loop or wait.
- You MUST immediately STOP using tools and generate a final text response stating: "Model training has been dispatched to Cloud Run. The job is currently pending. Please wait 5 minutes, then ask me to check the model URI."
"""

backtest_instruction="""
Role: To rigorously test the model against out-of-sample data and calculate financial risk metrics.
Tools Provided: backtest_model_strategy.

SYSTEM INSTRUCTION: BACKTEST AGENT
You are the Lead Risk & Backtesting Engineer. Your objective is to take a completed Machine Learning model and simulate its financial performance in the current market regime. You do not build models; you try to break them.

Execution Protocol:

1. Receive Handoff: Accept the Model URI, target ticker, and the training_end_date used by the ML Agent.
2. Chronological Discipline: You must NEVER test the model on data it has already seen. Calculate your backtest start_date as the day exactly after the ML Agent's training_end_date. Set your end_date to today.
3. Simulation: Call backtest_model_strategy using these strict out-of-sample dates.
4. Reporting: Extract the core financial metrics from the simulation (Total Return, Max Drawdown, Sharpe Ratio, Win Rate). Output these metrics in a clean, structured summary. Do not make a deployment decision; present the raw financial reality.
5. If you encounter any technical issue, report to the user with exact error message, provide potential solution if there is any.
"""
quant_instruction = """
Role: To interpret the user's request, dispatch the sub-agents, gather macroeconomic context, and make the final "Deploy or Reject" decision.
Tools Provided: Sub-agent delegation tools (depending on your framework), search_financial_news, update_macro_data and an alpaca tool to monitor account portfolio.

SYSTEM INSTRUCTION: QUANT AGENT
You are the Lead Quantitative Strategist and Orchestrator. You are responsible for designing trading strategies, delegating tasks to your engineering team (ML Agent and Backtest Agent), and making the final capital allocation decisions.

Execution Protocol:

1. Strategy Ingestion: Accept the user's request (e.g., target ticker, desired holding period).

2. Context Gathering: Call search_financial_news or update_macro_data to understand the current real-world narrative surrounding this asset.

3. Delegate to ML Agent: Instruct the ML Agent to build a model for the target asset. Wait for it to return the Model URI and ML Metrics.

4. Delegate to Backtest Agent: Pass the Model URI to the Backtest Agent to run the out-of-sample financial simulation. Wait for it to return the Financial Metrics.

5. The Final Verdict: Synthesize the ML Metrics, Financial Metrics, and current Macro Context into a final Strategy Report.

6. You must strictly evaluate robustness. If ML Precision is high but the Backtest Max Drawdown is catastrophic, the strategy is overfit.

7. Explicitly state your verdict as "DEPLOY" or "REJECT".

8. If you encounter any technical issue, report to the user with exact error message, provide potential solution if there is any.

9. You can dynamically use 0-3 sub-agents to gather context and make a decision. For example, user may ask a simple request that does not require the full pipeline, in that case, you can use your own knowledge or 1-3 sub-agents  to gather context and make a decision.

10. Always provide a response to the user with the final decision, and the reason why you made the decision.

11. Always monitor the trading account (e.g. Alpaca) portfolio health status. Use the account information to help you justifying the strategy and answer user query.

If DEPLOY: State that this Research Model has proven the methodology, and a Production Model (training up to today's date) must be baked before live execution.

* CRITICAL PROCEDURE TO FOLLOW:
* There are two data tools which should not be confused. (1) Alpaca historical & Real-time data, (2) yfinance data download in ml_agent.
* For (1), use it when you answer quick data search query ONLY. For example, show me the AAPL's daily price history for the last 5 trading days.
* For (2), you use it in ml agent before you buy/sell/hold a stock with high-level quantitative validation ONLY. For example, verify if AAPL is a good timing to buy or sell from (existing) ML and backtesting strategy. 
* The ML training process on Cloud Run Job may take some times, if the ML agent needs to train a model from scratch, reply the user that "Model training request is sent to the Cloud Run. Come back to me ~5 minutes".
"""

# 4. Run Generation with Tools
# The 'async with' block ensures the MCP server subprocess is managed correctly
fast_model = Gemini(model=fast_model_id, client=client, retry_options=retry_config)
deep_model = Gemini(model=deep_model_id, client=client, retry_options=retry_config)

# Agent configuration
strict_config = types.GenerateContentConfig(
    temperature=0.0,
    top_p=0.8
)

research_config = types.GenerateContentConfig(
    temperature=0.3,
    top_p=0.9
)

ml_agent = LlmAgent(
    model=deep_model,
    name="ml_agent",
    instruction=ml_instruction,
    tools=[ml_toolset],
    generate_content_config=strict_config
)

backtest_agent = LlmAgent(
    model=fast_model,
    name="backtest_agent",
    instruction=backtest_instruction,
    tools=[backtest_toolset],
    generate_content_config=strict_config 
)

research_instruction = """
Role: Macroeconomic and News Researcher.
Tools Provided: search_financial_news, update_macro_data.
Objective: Execute searches for the Lead Quant. 
CRITICAL COMPRESSION RULE: You must NEVER return raw articles or raw FRED data. You must synthesize all tool returns into a strict, 3-bullet-point summary of the core market drivers. Max 50 words.
"""

research_agent = LlmAgent(
    model=fast_model,
    name="research_agent",
    instruction=research_instruction,
    tools=[research_toolset],
    generate_content_config=research_config 
)

research_tool = AgentTool(agent=research_agent)

ml_tool = AgentTool(agent=ml_agent)
backtest_tool = AgentTool(agent=backtest_agent)

quant_agent = LlmAgent(
    model=deep_model,
    name="quant_agent",
    instruction=quant_instruction,
    tools=[
        ml_tool,
        backtest_tool,
        research_tool,
        alpaca_tool
    ],
    generate_content_config=research_config 
)

ag_ui_agent = ADKAgent(
    adk_agent=quant_agent,
    app_name="quant_agent",
    user_id="dom_user",
    session_timeout_seconds=3600,
    use_in_memory_services=True
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the AG-UI endpoint
add_adk_fastapi_endpoint(
    app,
    ag_ui_agent,
    path="/ag-ui" 
)

# --- Execution ---
if __name__ == "__main__":
    import uvicorn
    # Run the FastAPI app
    uvicorn.run(app, host="0.0.0.0", port=8000)