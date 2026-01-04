# agents/quant_analyst.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from typing import Literal
import pandas as pd # Import pandas for nice tables

from core.state import AgentState
from tools.technical_analysis import calculate_technicals
from tools.trade_memory import fetch_recent_memory

# Use the latest available preview or stable model
MODEL_NAME = "gemini-3-pro-preview"

# --- 1. DATA MODELS ---
class TradeSignal(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD", "WAIT"] = Field(description="The recommendation.")
    confidence: float = Field(description="0.0 to 1.0 confidence score.")
    current_price: float = Field(description="The latest price used for analysis")
    
    # Rationale Fields
    reasoning: str = Field(description="Concise synthesis of Tech + Sentiment (max 1 sentence).")
    risk_analysis: str = Field(description="Primary downside risk (e.g., 'High Volatility', 'Earnings risk').")
    expected_return: str = Field(description="Conservative target based on resistance/BB_UPPER.")
    stop_loss: str = Field(description="Invalidation level based on support/SMA200.")

class QuantProposal(BaseModel):
    signals: list[TradeSignal]

# --- 2. HELPER: TECHNICAL SCORE CALCULATOR ---
def calculate_technical_score(data: dict) -> float:
    """Calculates a deterministic Technical Score (0-100)."""
    score = 0
    # 1. Trend (30 pts)
    if data.get('trend') == "Bullish": score += 30
    elif data.get('trend') == "Neutral": score += 15
    
    # 2. RSI Setup (30 pts)
    rsi = data.get('RSI', 50)
    if rsi < 35: score += 30      # Oversold (Buy dip)
    elif 35 <= rsi <= 60: score += 15 # Healthy
    
    # 3. Bollinger Band Value (20 pts)
    price = data.get('current_price', 0)
    bb_lower = data.get('BB_LOWER', 0)
    if price <= bb_lower * 1.02: score += 20 # Near Lower Band
    
    # 4. Momentum/ROC (20 pts) - Simplified proxy
    if rsi > 50: score += 20
    
    return min(100, score)

# --- 3. AGENT LOGIC ---
def quant_analyst_node(state: AgentState):
    """
    The Quant Analyst.
    Analyzes Technicals + Sentiment + Memory + Portfolio Status to generate a Trade Proposal.
    Implements 70/30 Weighted Scoring (Tech/Sent).
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
    scoreboard = []

    # --- ANALYSIS LOOP ---
    for symbol, candles in stocks_raw.items():
        # --- SKIP HOLDINGS (Gatekeeper handles these) ---
        if symbol in current_holdings:
            continue

        # 1. Calculate Technicals
        tech_data = calculate_technicals(symbol, candles)
        if "error" in tech_data:
            continue
            
        current_price = tech_data.get('current_price')
        real_prices[symbol] = current_price
        
        # 2. Get Sentiment
        raw_sent = sentiment_scores.get(symbol, 0.0)
        
        # 3. Calculate Scores (70/30 Logic)
        tech_score = calculate_technical_score(tech_data)
        
        # Normalize Sentiment (-1 to 1) -> (0 to 100)
        # -1 = 0, 0 = 50, 1 = 100
        sent_score = (raw_sent + 1) * 50
        
        # Weighted Composite
        final_score = (tech_score * 0.70) + (sent_score * 0.30)
        
        # Determine Verdict for Context
        verdict = "WAIT"
        if final_score > 60: verdict = "BUY_CANDIDATE"

        # Add to Scoreboard for visualization
        scoreboard.append({
            "Ticker": symbol,
            "Tech": tech_score,
            "Sent": int(sent_score),
            "Final": f"{final_score:.1f}",
            "Verdict": verdict
        })

        # 4. Memory Check
        past_decisions = fetch_recent_memory(symbol, lookback_days=7)
        memory_context = "No recent history."
        if past_decisions:
            memory_context = f"⚠️ PAST HISTORY (7 Days): {'; '.join(past_decisions)}"

        # 5. Create Summary String
        summary = (
            f"TICKER: {symbol}\n"
            f"SCORES: Tech={tech_score:.1f}, Sent={sent_score:.1f} ({raw_sent})\n"
            f"COMPOSITE SCORE: {final_score:.1f}/100\n"
            f"VERDICT: {verdict}\n"
            f"Data: RSI={tech_data.get('RSI'):.1f}, Trend={tech_data.get('trend')}\n"
            f"Memory: {memory_context}\n"
            "---"
        )
        technicals_summary.append(summary)

    if not technicals_summary:
        print("⚠️ QUANT: No technical data available to analyze.")
        return {"trade_proposal": [], "messages": []}

    # --- PRINT SCOREBOARD (VISUAL PROOF) ---
    print("\n📊 QUANT SCOREBOARD (Threshold: 60.0)")
    if scoreboard:
        print(pd.DataFrame(scoreboard).to_string(index=False))
    else:
        print("   (No Valid Candidates in Batch)")
    print("-" * 60)

    # --- 4. PROMPT ENGINEERING ---
    system_prompt = (
        "You are a Senior Portfolio Manager using a Weighted Scoring System (70% Technical, 30% Sentiment).\n"
        "CURRENT STRATEGY MANDATE: '{mandate}'\n\n"
        "GOAL: Filter candidates based on their Composite Score.\n\n"
        "DECISION RULES:\n"
        "1. IF Composite Score > 60: You MUST propose a BUY.\n"
        "2. IF Composite Score < 60: You MUST propose WAIT.\n"
        "3. DIVERGENCE EXCEPTION: If Tech Score is high (>70) but Sentiment is low (<40), Buy as 'Contrarian Play'.\n\n"
        "MEMORY RULES:\n"
        "- If 'REJECTED_RISK' recently, DO NOT buy unless conditions changed drastically.\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- 'reasoning': Mention the Composite Score and the key driver (Tech or Sentiment).\n"
        "- 'current_price': Use the price provided in the data.\n"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Analyze these candidates:\n{asset_data}")
    ])

    chain = prompt | llm.with_structured_output(QuantProposal)
    
    # Join the summary list into one big string
    assets_text_block = "\n".join(technicals_summary)

    try:
        decision = chain.invoke({
            "mandate": mandate_str,
            "asset_data": assets_text_block
        })
        
        # --- Format Output ---
        final_proposals = []
        for signal in decision.signals:
            sig_dict = signal.dict()
            
            # Force overwrite price to ensure exact match with market data
            if signal.symbol in real_prices:
                sig_dict['current_price'] = real_prices[signal.symbol]
            
            # Only allow BUY/SELL (Holdings handled by Gatekeeper)
            if signal.action in ["BUY", "SELL"]:
                final_proposals.append(sig_dict)

        print(f"📈 QUANT PROPOSAL: {len(decision.signals)} Raw Signals -> {len(final_proposals)} Actionable Buys")

        return {
            "trade_proposal": final_proposals,
            "messages": [AIMessage(content="Strategy analysis complete.")]
        }
    except Exception as e:
        print(f"⚠️ QUANT ERROR: {e}")
        return {"trade_proposal": []}
