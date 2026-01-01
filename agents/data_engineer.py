# agents/data_engineer.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import ToolMessage

# Import tools
from tools.market_data import fetch_market_data, fetch_macro_data
from tools.screener import screen_stocks
from tools.portfolio import get_current_portfolio # <--- IMPORT THIS
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
    1. Identify 'Universe' (Current Holdings + New Screener Picks).
    2. Fetch market data (Yahoo Finance) & Macro data (FRED).
    """
    
    credentials, project_id = google.auth.default()
    
    # Bind Tools
    tools = [screen_stocks, fetch_market_data, fetch_macro_data]
    
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0
    ).bind_tools(tools)

    # Updated System Prompt to emphasize "Full-Cycle" data gathering
    system_prompt = (
        "You are the Data Engineer for a hedge fund.\n"
        "Your goal is to prepare a complete dataset for analysis.\n\n"
        "TASK EXECUTION ORDER:\n"
        "1. CALL `screen_stocks` to find NEW opportunities.\n"
        "2. CALL `fetch_macro_data` for market context.\n"
        "3. (The system will automatically merge Screener picks with Current Holdings and fetch prices).\n"
        "4. Respond with 'DATA_READY' once tools are triggered."
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", "Execute the data pipeline: Screen + Holdings -> Macro -> Prices.")
    ])

    chain = prompt | llm
    
    response = chain.invoke({"messages": state["messages"]})
    
    new_messages = [response]
    market_data_update = {}
    
    if response.tool_calls:
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            content = ""
            
            print(f"📊 DATA ENGINEER ACTION: {tool_name}")

            try:
                # A. SCREENER LOGIC (Discovery)
                if tool_name == "screen_stocks":
                    new_candidates = screen_stocks(**tool_args)
                    content = f"Screener found: {new_candidates}"
                    
                    # --- CRITICAL UPGRADE: MERGE WITH HOLDINGS ---
                    print("   ↳ 🔄 Merging with Current Holdings...")
                    portfolio = get_current_portfolio()
                    current_holdings = [p['Symbol'] for p in portfolio.get('holdings', [])]
                    
                    # Combine and Deduplicate (Set logic)
                    full_universe = list(set(new_candidates + current_holdings))
                    
                    print(f"   ↳ 📉 Fetching data for FULL UNIVERSE: {full_universe}")
                    
                    # Fetch 1-Hour candles for the combined list
                    stock_data = fetch_market_data(symbols=full_universe, period="1mo", interval="1h")
                    
                    market_data_update["stocks"] = stock_data
                    market_data_update["universe"] = full_universe # List of all assets being analyzed
                    market_data_update["holdings"] = current_holdings # Keep track of what we already own

                # B. MACRO LOGIC
                elif tool_name == "fetch_macro_data":
                    macro_data = fetch_macro_data(**tool_args)
                    market_data_update["macro"] = macro_data
                    content = "Macro data fetched successfully."

                # C. FALLBACK
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
