# agents/data_engineer.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage

from tools.market_data import fetch_market_data, fetch_macro_data
from tools.screener import screen_stocks
from tools.portfolio import get_current_portfolio
from core.state import AgentState

MODEL_NAME = "gemini-2.5-flash-lite"

# Volatility Threshold (2%)
VOLATILITY_THRESHOLD = 0.02
TARGET_PENDING_ORDERS = 10

class SearchStrategy(BaseModel):
    screener_mode: str
    search_query: str = Field(description="Optimized search query for Brave.")
    macro_indicators: list[str] = Field(description="List of VALID FRED Series IDs only.")
    reasoning: str

class TickerValidation(BaseModel):
    valid_tickers: list[str]
    hallucinations: list[str]

def data_engineer_node(state: AgentState):
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0.3
    )

    # Context
    retry_count = state.get("retry_count", 0)
    forced_mode = state.get("forced_screener_mode", "standard")
    system_mode = state.get("system_mode", "HIGH_MODE")
    
    # Calculate Total Pending (Existing File + Current Session)
    initial_pending = state.get("pending_count", 0)
    approved_orders = state.get("approved_orders") or []
    current_total_pending = initial_pending + len(approved_orders)
    
    portfolio = get_current_portfolio()
    current_holdings = [p['Symbol'] for p in portfolio.get('holdings', [])]
    session_analyzed = state.get("analyzed_tickers", [])
    exclusion_list = list(set(current_holdings + session_analyzed))

    market_data_update = {}
    newly_scanned = []
    condition = "CALM"

    print(f"🔄 DATA ENGINEER: Mode={system_mode} | Total Pending: {current_total_pending}/{TARGET_PENDING_ORDERS}")

    # --- A. SENTINEL MODE (Monitor Holdings) ---
    print(f"   🛡️ Monitoring {len(current_holdings)} holdings...")
    if current_holdings:
        holdings_data = fetch_market_data(symbols=current_holdings, period="2d", interval="1h")
        market_data_update["stocks"] = holdings_data
        
        if system_mode == "LOW_MODE":
            for sym, candles in holdings_data.items():
                if len(candles) >= 2:
                    pct_change = abs((candles[-1]['close'] - candles[-2]['close']) / candles[-2]['close'])
                    if pct_change > VOLATILITY_THRESHOLD:
                        print(f"   🚨 ALERT: {sym} moved {pct_change*100:.2f}%. Waking System.")
                        condition = "VOLATILE"
                        break

    # --- B. HUNTER MODE (Find New Stocks) ---
    # Hunt ONLY if:
    # 1. We are under the 20 order limit
    # 2. AND (We are in High Mode OR Market is Calm/Opportunity)
    
    should_hunt = False
    if current_total_pending < TARGET_PENDING_ORDERS:
        should_hunt = True
        
    valid_universe = []
    
    if should_hunt:
        attempt_counter = 0
        max_internal_retries = 3
        
        while len(valid_universe) < 5 and attempt_counter < max_internal_retries:
            attempt_counter += 1
            print(f"\n   🔍 Hunting Loop {attempt_counter}/{max_internal_retries} (Need 5, have {len(valid_universe)})...")

            # Strategy Generation
            strategy_prompt = (
                "You are a Data Engineer. Generate a search query.\n"
                f"CONTEXT: Retry #{retry_count}. Attempt #{attempt_counter}.\n"
                f"MODE: {forced_mode}\n"
                "RULES:\n"
                "1. BROADEN query if Attempt > 1.\n"
                "2. NO URLs or 'Brave Search' in query.\n"
                "3. Use valid FRED IDs only.\n"
            )
            chain = ChatPromptTemplate.from_messages([("system", strategy_prompt), ("human", "Go.")]) | llm.with_structured_output(SearchStrategy)
            strategy = chain.invoke({})
            print(f"   🧠 STRATEGY: '{strategy.search_query}'")

            # Execution
            try:
                raw_candidates = screen_stocks(
                    mode=strategy.screener_mode,
                    exclude_tickers=exclusion_list,
                    custom_query=strategy.search_query
                )
            except Exception as e:
                print(f"   ❌ Screener Error: {e}")
                raw_candidates = []

            # Validation
            if raw_candidates:
                val_prompt = f"Validate tickers: {raw_candidates}. Return valid US symbols only."
                val_chain = ChatPromptTemplate.from_messages([("system", val_prompt), ("human", "Validate.")]) | llm.with_structured_output(TickerValidation)
                result = val_chain.invoke({})
                
                new_valid = [t for t in result.valid_tickers if t not in valid_universe and t not in exclusion_list]
                valid_universe.extend(new_valid)
                exclusion_list.extend(new_valid)
                print(f"   ✅ Added {len(new_valid)} tickers.")
            else:
                print("   ⚠️ No raw candidates.")

        if valid_universe:
            condition = "OPPORTUNITY"
            newly_scanned = valid_universe
            print(f"📉 Fetching Data for {len(valid_universe)} new assets...")
            candidates_data = fetch_market_data(symbols=valid_universe, period="1mo", interval="1h")
            current_stocks = market_data_update.get("stocks", {})
            market_data_update["stocks"] = {**current_stocks, **candidates_data}
            
            valid_fred = ["VIXCLS", "DGS10", "FEDFUNDS", "CPIAUCSL", "GDP", "UNRATE"]
            safe_inds = [m for m in strategy.macro_indicators if m in valid_fred]
            if safe_inds:
                market_data_update["macro"] = fetch_macro_data(series_ids=safe_inds)
    else:
        print("   zzZ Basket Full (20/20). Skipping Hunt.")

    # --- RETURN ---
    prev_data = state.get("market_data") or {}
    merged_stocks = prev_data.get("stocks", {}) | market_data_update.get("stocks", {})
    
    final_market_data = {
        "stocks": merged_stocks,
        "macro": market_data_update.get("macro", prev_data.get("macro")),
        "holdings": current_holdings,
        "universe": newly_scanned
    }

    return {
        "market_data": final_market_data,
        "analyzed_tickers": session_analyzed + newly_scanned,
        "market_condition": condition,
        "trade_proposal": None,
        # Note: We do NOT reset approved_orders here, Supervisor handles accumulation check
        "messages": [AIMessage(content=f"Status: {condition}")]
    }
