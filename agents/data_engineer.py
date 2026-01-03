# agents/data_engineer.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import ToolMessage

from tools.market_data import fetch_market_data, fetch_macro_data
from tools.screener import screen_stocks
from tools.portfolio import get_current_portfolio
from core.state import AgentState

MODEL_NAME = "gemini-2.5-flash"

def data_engineer_node(state: AgentState):
    """
    The Data Engineer.
    Role: Configures the Screener based on Retry Count to find *fresh* stocks.
    """
    
    credentials, project_id = google.auth.default()
    tools = [screen_stocks, fetch_market_data, fetch_macro_data]
    
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0
    ).bind_tools(tools)

    # --- 1. DETERMINE STRATEGY BASED ON RETRY COUNT ---
    retry_count = state.get("retry_count", 0)
    # Load list of stocks we already checked this session (to exclude them)
    analyzed_tickers = state.get("analyzed_tickers", [])
    
    # Switch Strategy on failure
    screener_mode = "standard"
    if retry_count == 1:
        screener_mode = "undervalued" # Strategy B: Value hunting
    elif retry_count >= 2:
        screener_mode = "momentum"    # Strategy C: Aggressive growth
        
    print(f"🔄 DATA ENGINEER: Iteration {retry_count} | Mode: {screener_mode}")
    print(f"   🚫 Excluding {len(analyzed_tickers)} previously checked tickers.")

    system_prompt = (
        "You are the Data Engineer.\n"
        "TASK EXECUTION ORDER:\n"
        f"1. CALL `screen_stocks` using mode='{screener_mode}'.\n"
        "   - The system handles exclusions automatically.\n"
        "2. CALL `fetch_macro_data`.\n"
        "3. Respond with 'DATA_READY'."
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", "Execute the data pipeline.")
    ])

    chain = prompt | llm
    response = chain.invoke({"messages": state["messages"]})
    
    new_messages = [response]
    market_data_update = {}
    newly_scanned = []

    if response.tool_calls:
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            content = ""
            
            print(f"📊 DATA ENGINEER ACTION: {tool_name}")

            try:
                if tool_name == "screen_stocks":
                    # --- CRITICAL: INJECT EXCLUSIONS ---
                    # We override the LLM's args to ensure Python logic prevails
                    new_candidates = screen_stocks(
                        mode=screener_mode,
                        exclude_tickers=analyzed_tickers
                    )
                    content = f"Screener ({screener_mode}) found: {new_candidates}"
                    
                    # Merge with Holdings
                    print("   ↳ 🔄 Merging with Current Holdings...")
                    portfolio = get_current_portfolio()
                    current_holdings = [p['Symbol'] for p in portfolio.get('holdings', [])]
                    
                    full_universe = list(set(new_candidates + current_holdings))
                    newly_scanned = new_candidates # Save these to ignore next time
                    
                    print(f"   ↳ 📉 Fetching data for: {full_universe}")
                    
                    stock_data = fetch_market_data(symbols=full_universe, period="1mo", interval="1h")
                    
                    market_data_update["stocks"] = stock_data
                    market_data_update["universe"] = full_universe
                    market_data_update["holdings"] = current_holdings

                elif tool_name == "fetch_macro_data":
                    macro_data = fetch_macro_data(**tool_args)
                    market_data_update["macro"] = macro_data
                    content = "Macro data fetched successfully."

                elif tool_name == "fetch_market_data":
                    data = fetch_market_data(**tool_args)
                    market_data_update["stocks"] = data
                    content = "Market data fetched."

            except Exception as e:
                content = f"Tool Error: {str(e)}"
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
        "market_data": final_market_data,
        # Update the exclusion list for the next loop
        "analyzed_tickers": analyzed_tickers + newly_scanned
    }
