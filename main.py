from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams, StdioConnectionParams
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types
from mcp import StdioServerParameters 
from google.adk.apps.app import App, EventsCompactionConfig
import os

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION = os.getenv("GCP_AI_REGION", "global")
DATA_SERVER_URL = os.getenv("DATA_SERVER_URL")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = LOCATION

# Avoid rate limits and temorary service unavailability 
retry_config = types.HttpRetryOptions(
    attempts=5,  # Maximum retry attempts
    exp_base=7,  # Delay multiplier
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],  # Retry on these HTTP errors
)

# ========= MCP SERVER CONNECTION =========

# 1. yfinance data retrieval 

# 2. BQ Client 

# 3. BQML Client

# 4. Backtest Client 

# 5. BraveSearch + FRED Client

# 5. Alpaca Client
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
alpaca_tool = McpToolset(
    connection_params=alpaca_con,
    tool_filter=[
        "get_account_info",
        "get_all_positions",
        "get_open_position",
        "get_orders",
        "get_portfolio_history",          
        
        # --- Order Execution ---
        "place_stock_order",
        "cancel_order_by_id",
        "close_position",
        "close_all_positions",
        "cancel_all_orders",
        
        # --- Watchlist Management (Brokerage Memory) ---
        "get_watchlists",                 
        "create_watchlist",              
        "get_watchlist_by_id",  
        "update_watchlist_by_id"          
        "add_asset_to_watchlist_by_id",   
        "remove_asset_from_watchlist_by_id",
        "delete_watchlist_by_id"
        
        # --- Fundamental & Event Data ---
        "get_corporate_actions",

        # --- Market Calendar ---
        "get_calendar",
        "get_clock"

    ]
    )

# ============ AGENT INITIALIZATION ============
client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION
)

fast_model_id = "gemini-3-flash-preview" 
deep_model_id = "gemini-3.1-pro-preview"

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


