# agents/quant_analyst.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from typing import Literal, Optional

from core.state import AgentState
from tools.technical_analysis import calculate_technicals
from tools.trade_memory import fetch_recent_memory

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Gemini 3.0 Pro: We need top-tier reasoning to synthesize signals
MODEL_NAME = "gemini-2.5-pro" 

# ==========================================
# 2. OUTPUT SCHEMA
# ==========================================
class TradeSignal(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"] = Field(description="The recommendation action.")
    confidence: float = Field(description="Confidence score (0.0 to 1.0).")
    
    risk_analysis: str = Field(description="Primary downside risk (e.g., 'High Volatility', 'Earnings risk').")
    expected_return: str = Field(description="Conservative target based on resistance/BB_UPPER.")
    quantity_weight: float = Field(description="Recommended portfolio weight (0.0 to 1.0). e.g. 0.05 for 5%.")
    reasoning: str = Field(description="Concise technical and fundamental justification.")
    stop_loss: str = Field(description="Invalidation level based on support/SMA200.")

class QuantProposal(BaseModel):
    signals: list[TradeSignal]
    rationale: str = Field(description="Overall strategy summary for this batch.")

# ==========================================
# 3. AGENT LOGIC
# ==========================================
def quant_analyst_node(state: AgentState):
    """
    The Quant Analyst.
    1. Receives raw market data + Sentiment scores.
    2. Calculates technical indicators (Python).
    3. Synthesizes data into a Trade Proposal.
    """
    
    # Auth
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0.2 # Low temp for analytical precision
    )

    # 1. Unpack Data
    market_data = state.get("market_data", {})
    sentiment_data = state.get("sentiment_data", {})
    
    stocks_raw = market_data.get("stocks", {})
    sentiment_scores = sentiment_data.get("scores", {})
    
    technicals_summary = []
    
    for symbol, candles in stocks_raw.items():
        tech_data = calculate_technicals(symbol, candles)
        if "error" in tech_data or tech_data.get("RSI") is None:
            continue
            
        s_score = sentiment_scores.get(symbol, 0.0)
        
        # --- NEW: MEMORY CHECK ---
        past_decisions = fetch_recent_memory(symbol)
        memory_context = ""
        if past_decisions:
            memory_context = f"PAST 7 DAYS HISTORY: {'; '.join(past_decisions)}"
        
        summary = (
            f"TICKER: {symbol}\n"
            f"Price: {tech_data.get('current_price')}\n"
            f"RSI: {tech_data.get('RSI'):.2f}\n"
            f"Trend: {tech_data.get('trend')} (Price vs SMA200)\n"
            f"Bands: Lower={tech_data.get('BB_LOWER'):.2f}, Upper={tech_data.get('BB_UPPER'):.2f}\n"
            f"Sentiment: {s_score}\n"
            f"{memory_context}\n"
            "---"
        )
        technicals_summary.append(summary)

    if not technicals_summary:
        return {"trade_proposal": [], "messages": []}

    
    # --- 2. UPDATED SYSTEM PROMPT ---
    system_prompt = (
        "You are a Lead Quantitative Analyst.\n"
        "Your goal is to generate structured trade proposals with clear rationales for a human trader.\n\n"
        "STRATEGY RULES:\n"
        "1. Mean Reversion: BUY if RSI < 30 & Sentiment > -0.5. (Target: SMA50)\n"
        "2. Trend Following: BUY if Price > SMA200 & Sentiment >= 0.2. (Target: BB_UPPER)\n"
        "3. Profit Taking: SELL if RSI > 75. (Target: Current Price)\n\n"
        "OUTPUT INSTRUCTIONS:\n"
        "- 'reasoning': Combine technicals (RSI/Trend) and Sentiment into one punchy sentence.\n"
        "- 'risk_analysis': Identify the main threat (e.g. 'Overbought RSI', 'Negative News').\n"
        "- 'expected_return': Estimate a % upside based on the Bands/SMA levels provided.\n"
        "- 'stop_loss': Suggest a stop level below key support (SMA200 or BB_LOWER).\n"
        "MEMORY RULES:\n"
        "1. If a stock was 'REJECTED_RISK' recently due to 'High Concentration' or 'Sector Exposure', DO NOT propose it again immediately.\n"
        "2. If a stock was 'EXECUTED' recently, only propose adding if the trend is still strong (Pyramiding).\n"
        "3. Explicitly mention in 'reasoning' if you are ignoring a past rejection due to new data.\n"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", f"Analyze these assets:\n{technicals_summary}")
    ])

    chain = prompt | llm.with_structured_output(QuantProposal)
    
    try:
        decision = chain.invoke({})
        print(f"📈 QUANT PROPOSAL: Generated {len(decision.signals)} rich signals.")
        # Return dictionaries so they are JSON serializable for the next node
        return {
            "trade_proposal": [signal.dict() for signal in decision.signals],
            "messages": [AIMessage(content="Strategy analysis complete.")]
        }
    except Exception as e:
        print(f"⚠️ QUANT ERROR: {e}")
        return {"trade_proposal": []}
