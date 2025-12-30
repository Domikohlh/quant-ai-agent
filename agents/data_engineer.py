# agents/data_engineer.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import ToolMessage

# Import tools
from tools.market_data import fetch_market_data, fetch_macro_data
from tools.screener import screen_stocks
from core.state import AgentState

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_NAME = "gemini-2.5-flash"

# ==========================================
# 2. AGENT LOGIC
# ==========================================
def data_engineer_node(state: AgentState):
    """
    The Data Engineer.
    Role: 
    1. Screen the market for the best stocks.
    2. Fetch market data (Yahoo Finance) & Macro data (FRED).
    """
    
    # Auth
    credentials, project_id = google.auth.default()
    
    # Bind Tools
    tools = [screen_stocks, fetch_market_data, fetch_macro_data]
    
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0
    ).bind_tools(tools)

    # Updated System Prompt to reference Yahoo Finance and Intervals
    system_prompt = (
        "You are the Data Engineer for a hedge fund.\n"
        "Your goal is to build a high-quality watchlist and fetch data.\n\n"
        "TASK EXECUTION ORDER:\n"
        "1. CALL `screen_stocks` to find the top 5 steady growth stocks.\n"
        "2. CALL `fetch_macro_data` to get the VIX.\n"
        "3. (System handles price fetching automatically for screened stocks).\n"
        "4. Respond with 'DATA_READY' once tools are triggered.\n\n"
        "NOTE: Market data source is Yahoo Finance (yfinance)."
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", "Execute the data pipeline: Screen -> Macro -> Prices.")
    ])

    chain = prompt | llm
    
    # Invoke LLM
    response = chain.invoke({"messages": state["messages"]})
    
    new_messages = [response]
    market_data_update = {}
    
    # ----------------------------------------------
    # SMART TOOL EXECUTION HANDLER
    # ----------------------------------------------
    if response.tool_calls:
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            content = ""
            
            print(f"📊 DATA ENGINEER ACTION: {tool_name}")

            try:
                # A. SCREENER LOGIC
                if tool_name == "screen_stocks":
                    tickers = screen_stocks(**tool_args)
                    content = f"Screener found: {tickers}"
                    
                    # AUTO-CHAIN: Fetch 1-Hour candles for better granularity
                    print(f"   ↳ ⛓️ Chaining: Fetching 1h data for {tickers}...")
                    
                    # We default to 1-month period with 1-hour intervals for detail
                    stock_data = fetch_market_data(symbols=tickers, period="1mo", interval="1h")
                    
                    market_data_update["stocks"] = stock_data
                    market_data_update["selected_tickers"] = tickers

                # B. MACRO LOGIC
                elif tool_name == "fetch_macro_data":
                    macro_data = fetch_macro_data(**tool_args)
                    market_data_update["macro"] = macro_data
                    content = "Macro data fetched successfully."

                # C. MARKET DATA (Fallback Direct Call)
                elif tool_name == "fetch_market_data":
                    data = fetch_market_data(**tool_args)
                    market_data_update["stocks"] = data
                    content = "Market data fetched successfully."
                
                else:
                    content = "Error: Tool not found."

            except Exception as e:
                content = f"Tool Execution Error: {str(e)}"
                print(f"❌ ERROR in {tool_name}: {e}")

            new_messages.append(ToolMessage(
                tool_call_id=tool_call["id"],
                content=str(content),
                name=tool_name
            ))

    current_data = state.get("market_data") or {}
    final_market_data = {**current_data, **market_data_update}

    return {
        "messages": new_messages,
        "market_data": final_market_data
    }
