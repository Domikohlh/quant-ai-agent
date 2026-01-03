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
    Data Engineer.
    1. Fetches data for HOLDINGS (for Gatekeeper).
    2. Screens for NEW CANDIDATES (for Quant), strictly excluding holdings.
    """
    credentials, project_id = google.auth.default()
    tools = [screen_stocks, fetch_market_data, fetch_macro_data]
    
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0
    ).bind_tools(tools)

    # --- 1. DETERMINE CONTEXT ---
    retry_count = state.get("retry_count", 0)
    forced_mode = state.get("forced_screener_mode", "standard")
    
    # Logic: Fallback to "standard" if retry_count is high, or rotate strategies
    screener_mode = forced_mode
    if retry_count == 1: screener_mode = "undervalued"
    elif retry_count >= 2: screener_mode = "momentum"

    # --- 2. GET EXCLUSION LIST (CRITICAL FIX) ---
    # We must exclude:
    # A. Stocks we already own (Don't buy what we have)
    # B. Stocks we already checked in this session (Don't check twice)
    portfolio = get_current_portfolio()
    current_holdings = [p['Symbol'] for p in portfolio.get('holdings', [])]
    session_analyzed = state.get("analyzed_tickers", [])
    
    # Master Exclusion List
    exclusion_list = list(set(current_holdings + session_analyzed))
    
    print(f"🔄 DATA ENGINEER: Mode='{screener_mode}' | Retrying: {retry_count}")
    print(f"   🚫 Excluding {len(exclusion_list)} tickers (Holdings + Analyzed).")

    # --- 3. SYSTEM PROMPT ---
    system_prompt = (
        "You are the Data Engineer.\n"
        "EXECUTION PLAN:\n"
        f"1. CALL `screen_stocks` with mode='{screener_mode}'.\n"
        "   - The system will inject the exclusion list automatically.\n"
        "2. CALL `fetch_macro_data`.\n"
        "3. Respond with 'DATA_READY'."
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", "Execute.")
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
                    # --- OVERRIDE: INJECT EXCLUSIONS ---
                    new_candidates = screen_stocks(
                        mode=screener_mode,
                        exclude_tickers=exclusion_list # <--- THE ZOMBIE FIX
                    )
                    content = f"Screener found: {new_candidates}"
                    newly_scanned = new_candidates
                    
                    # Merge New Candidates + Current Holdings for data fetching
                    # (We need holdings data for Gatekeeper, new data for Quant)
                    full_universe = list(set(new_candidates + current_holdings))
                    
                    print(f"   ↳ 📉 Fetching data for: {full_universe}")
                    stock_data = fetch_market_data(symbols=full_universe, period="1mo", interval="1h")
                    
                    market_data_update["stocks"] = stock_data
                    market_data_update["universe"] = full_universe
                    market_data_update["holdings"] = current_holdings

                elif tool_name == "fetch_macro_data":
                    macro_data = fetch_macro_data(**tool_args)
                    market_data_update["macro"] = macro_data
                    content = "Macro data fetched."

                elif tool_name == "fetch_market_data":
                    # Fallback if LLM calls this directly
                    data = fetch_market_data(**tool_args)
                    market_data_update["stocks"] = data
                    content = "Data fetched."

            except Exception as e:
                content = f"Error: {str(e)}"
                print(f"❌ ERROR in {tool_name}: {e}")

            new_messages.append(ToolMessage(
                tool_call_id=tool_call["id"],
                content=str(content),
                name=tool_name
            ))

    # --- 4. MERGE DATA (CRITICAL FIX FOR RETRY LOOPS) ---
    # Instead of replacing, we merge with existing state to prevent data loss
    prev_data = state.get("market_data") or {}
    
    # Helper to merge dictionaries safely
    merged_stocks = prev_data.get("stocks", {}) | market_data_update.get("stocks", {})
    
    final_market_data = {
        "stocks": merged_stocks,
        "macro": market_data_update.get("macro", prev_data.get("macro")),
        "holdings": current_holdings
    }

    return {
        "messages": new_messages,
        "market_data": final_market_data,
        "analyzed_tickers": session_analyzed + newly_scanned
    }
