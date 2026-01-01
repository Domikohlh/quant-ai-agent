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

MODEL_NAME = "gemini-2.5-pro"

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
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials
    )

    # --- LOAD DATA ---
    market_data = state.get("market_data", {})
    stocks_raw = market_data.get("stocks", {})
    sentiment_data = state.get("sentiment_data", {})
    sentiment_scores = sentiment_data.get("scores", {})
    
    # Retrieve current holdings (passed from Data Engineer)
    current_holdings = market_data.get("holdings", [])
    
    # --- CRITICAL FIX: DEFINE MANDATE ---
    # Retrieve the strategy mandate from the Portfolio Manager (or default)
    mandate = state.get("strategy_mandate", "Balanced Steady Growth")
    
    technicals_summary = []
    # Store real prices to force-inject later (preventing LLM hallucinations)
    real_prices = {}

    # --- ANALYSIS LOOP ---
    for symbol, candles in stocks_raw.items():
        # Calculate Technicals
        tech_data = calculate_technicals(symbol, candles)
        
        if "error" in tech_data:
            continue
            
        current_price = tech_data.get('current_price')
        real_prices[symbol] = current_price
        
        # Get Sentiment
        s_score = sentiment_scores.get(symbol, 0.0)
        
        # --- 1. MEMORY CHECK ---
        past_decisions = fetch_recent_memory(symbol, lookback_days=7)
        memory_context = "No recent history."
        if past_decisions:
            memory_context = f"⚠️ PAST HISTORY (7 Days): {'; '.join(past_decisions)}"

        # --- 2. HOLDING STATUS CHECK ---
        # Explicitly tell the LLM if we own this stock or if it's new
        position_status = "❌ NOT OWNED (Watchlist)"
        if symbol in current_holdings:
            position_status = "✅ CURRENT HOLDING (Re-evaluate: HOLD/SELL/BUY MORE?)"

        # Create Summary String for LLM
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

    # --- 3. PROMPT ENGINEERING ---
    system_prompt = (
        "You are a Senior Portfolio Manager.\n"
        f"CURRENT STRATEGY MANDATE: '{mandate}'\n\n"
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
        ("human", f"Analyze these assets:\n{technicals_summary}")
    ])

    chain = prompt | llm.with_structured_output(QuantProposal)
    
    try:
        decision = chain.invoke({})
        print(f"📈 QUANT PROPOSAL: Generated {len(decision.signals)} signals.")
        
        # Format for State (and force correct prices)
        final_proposals = []
        for signal in decision.signals:
            sig_dict = signal.dict()
            
            # Force overwrite price to ensure exact match with market data
            if signal.symbol in real_prices:
                sig_dict['current_price'] = real_prices[signal.symbol]
            
            # Only pass active signals (BUY/SELL) to Risk Manager to save tokens
            # (Optional: You can pass HOLDs if you want them logged, but usually we filter)
            if signal.action in ["BUY", "SELL"]:
                final_proposals.append(sig_dict)
            elif signal.action == "HOLD" and signal.symbol in current_holdings:
                 # Optionally keep HOLDs for existing positions so we know they were checked
                 final_proposals.append(sig_dict)

        return {
            "trade_proposal": final_proposals,
            "messages": [AIMessage(content="Strategy analysis complete.")]
        }
    except Exception as e:
        print(f"⚠️ QUANT ERROR: {e}")
        return {"trade_proposal": []}
