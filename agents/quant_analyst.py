# agents/quant_analyst.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from typing import Literal

from core.state import AgentState
from tools.technical_analysis import calculate_technicals
from tools.trade_memory import fetch_recent_memory

# Use the latest available preview or stable model
MODEL_NAME = "gemini-3-pro-preview"

# --- 1. DATA MODELS ---
class TradeSignal(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"] = Field(description="The recommendation.")
    confidence: float = Field(description="0.0 to 1.0 confidence score.")
    current_price: float = Field(description="The latest price used for analysis")
    
    # Rationale Fields
    reasoning: str = Field(description="Concise synthesis of Tech + Sentiment (max 1 sentence).")
    risk_analysis: str = Field(description="Primary downside risk (e.g., 'High Volatility', 'Earnings risk').")
    expected_return: str = Field(description="Conservative target based on resistance/BB_UPPER.")
    stop_loss: str = Field(description="Invalidation level based on support/SMA200.")

class QuantProposal(BaseModel):
    signals: list[TradeSignal]

# --- 2. AGENT LOGIC ---
def quant_analyst_node(state: AgentState):
    """
    The Quant Analyst.
    Analyzes Technicals + Sentiment + Memory + Portfolio Status to generate a Trade Proposal.
    """
    credentials, project_id = google.auth.default()
    
    # Initialize Model (GLOBAL LOCATION IS CRITICAL FOR PREVIEW MODELS)
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        location="global",
        credentials=credentials
    )

    # --- LOAD DATA ---
    market_data = state.get("market_data") or {}
    stocks_raw = market_data.get("stocks", {})
    
    sentiment_data = state.get("sentiment_data") or {}
    sentiment_scores = sentiment_data.get("scores", {})
    
    current_holdings = market_data.get("holdings", [])
    
    # Handle mandate safely (convert to string to be safe)
    raw_mandate = state.get("strategy_mandate", "Balanced Steady Growth")
    mandate_str = str(raw_mandate)
    
    technicals_summary = []
    real_prices = {}

    # --- ANALYSIS LOOP ---
    for symbol, candles in stocks_raw.items():
        # Calculate Technicals
        tech_data = calculate_technicals(symbol, candles)
        
        if "error" in tech_data:
            continue
            
        current_price = tech_data.get('current_price')
        real_prices[symbol] = current_price
        
        s_score = sentiment_scores.get(symbol, 0.0)
        
        # Memory Check
        past_decisions = fetch_recent_memory(symbol, lookback_days=7)
        memory_context = "No recent history."
        if past_decisions:
            memory_context = f"⚠️ PAST HISTORY (7 Days): {'; '.join(past_decisions)}"

        # Holding Status
        position_status = "❌ NOT OWNED (Watchlist)"
        if symbol in current_holdings:
            position_status = "✅ CURRENT HOLDING (Re-evaluate: HOLD/SELL/BUY MORE?)"

        # Create Summary String
        # We manually format this block, but we DON'T put it into the prompt yet.
        summary = (
            f"TICKER: {symbol}\n"
            f"STATUS: {position_status}\n"
            f"Price: {current_price}\n"
            f"RSI: {tech_data.get('RSI'):.2f}\n"
            f"Trend: {tech_data.get('trend')} (Price vs SMA200)\n"
            f"Bands: Lower={tech_data.get('BB_LOWER'):.2f}, Upper={tech_data.get('BB_UPPER'):.2f}\n"
            f"Sentiment Score: {s_score}\n"
            f"Memory Check: {memory_context}\n"
            "---"
        )
        technicals_summary.append(summary)

    if not technicals_summary:
        print("⚠️ QUANT: No technical data available to analyze.")
        return {"trade_proposal": [], "messages": []}

    # --- 3. PROMPT ENGINEERING (FIXED) ---
    # ERROR FIX: DO NOT use f-strings (f"...") for the Prompt Template inputs.
    # Use {variable_name} placeholders instead.
    
    system_prompt = (
        "You are a Senior Portfolio Manager.\n"
        "CURRENT STRATEGY MANDATE: '{mandate}'\n\n"  # <--- Placeholder, not f-string
        "GOAL: Manage the lifecycle of the portfolio (Buy New / Sell Existing).\n\n"
        "DECISION RULES:\n"
        "1. FOR CURRENT HOLDINGS (Re-Evaluation):\n"
        "   - HOLD: If Trend is still Bullish (Price > SMA50).\n"
        "   - SELL: If Thesis Broken (Price < SMA200) OR Profit Take (RSI > 80).\n"
        "   - BUY MORE: If Strong Pullback (Price touches Lower Band) AND Bullish Sentiment.\n\n"
        "2. FOR WATCHLIST (New Entries):\n"
        "   - BUY: If Momentum (RSI < 40) + Sentiment > 0.2 + Trend Alignment.\n"
        "   - IGNORE: If no clear setup.\n\n"
        "MEMORY RULES:\n"
        "- If 'REJECTED_RISK' recently, DO NOT buy unless conditions changed drastically.\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- 'reasoning': Combine Status + Technicals + Memory into one punchy sentence.\n"
        "- 'current_price': Use the price provided in the data.\n"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Analyze these assets:\n{asset_data}") # <--- Placeholder
    ])

    chain = prompt | llm.with_structured_output(QuantProposal)
    
    # Join the summary list into one big string
    assets_text_block = "\n".join(technicals_summary)

    try:
        # --- EXECUTE WITH ALL VARIABLES ---
        # We pass BOTH 'mandate' and 'asset_data' here.
        # This prevents LangChain from confusing data content with prompt variables.
        decision = chain.invoke({
            "mandate": mandate_str,
            "asset_data": assets_text_block
        })
        
        print(f"📈 QUANT PROPOSAL: Generated {len(decision.signals)} signals.")
        
        # --- Format Output ---
        final_proposals = []
        for signal in decision.signals:
            sig_dict = signal.dict()
            
            # Force overwrite price to ensure exact match with market data
            if signal.symbol in real_prices:
                sig_dict['current_price'] = real_prices[signal.symbol]
            
            if signal.action in ["BUY", "SELL"]:
                final_proposals.append(sig_dict)
            elif signal.action == "HOLD" and signal.symbol in current_holdings:
                final_proposals.append(sig_dict)

        return {
            "trade_proposal": final_proposals,
            "messages": [AIMessage(content="Strategy analysis complete.")]
        }
    except Exception as e:
        print(f"⚠️ QUANT ERROR: {e}")
        return {"trade_proposal": []}
