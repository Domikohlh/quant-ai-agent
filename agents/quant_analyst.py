# agents/quant_analyst.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Literal, Optional

from core.state import AgentState
from tools.technical_analysis import calculate_technicals

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Gemini 3.0 Pro: We need top-tier reasoning to synthesize signals
MODEL_NAME = "gemini-3.0-pro-001" 

# ==========================================
# 2. OUTPUT SCHEMA
# ==========================================
class TradeSignal(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"] = Field(description="The recommendation action.")
    quantity_weight: float = Field(description="Recommended portfolio weight (0.0 to 1.0). e.g. 0.05 for 5%.")
    confidence: float = Field(description="Confidence score (0.0 to 1.0).")
    reasoning: str = Field(description="Concise technical and fundamental justification.")

class StrategyProposal(BaseModel):
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
    
    # 2. Python-Side Calculation (The "Math Tool")
    # We do this HERE to feed the *results* to the LLM, not the raw CSV
    technicals_summary = []
    
    for symbol, candles in stocks_raw.items():
        # Run TA tool
        tech_data = calculate_technicals(symbol, candles)
        
        # Combine with Sentiment
        s_score = sentiment_scores.get(symbol, 0.0)
        
        # Create a condensed context string for the LLM
        summary = (
            f"TICKER: {symbol}\n"
            f"Price: {tech_data.get('current_price')}\n"
            f"RSI: {tech_data.get('RSI'):.2f} (Overbought > 70, Oversold < 30)\n"
            f"Trend: {tech_data.get('trend')} (Price vs SMA200)\n"
            f"Bollinger Status: Price={tech_data.get('current_price')}, Lower={tech_data.get('BB_LOWER'):.2f}, Upper={tech_data.get('BB_UPPER'):.2f}\n"
            f"News Sentiment: {s_score} (-1.0 to 1.0)\n"
            "---"
        )
        technicals_summary.append(summary)

    # 3. The Prompt
    system_prompt = (
        "You are the Lead Quantitative Analyst for a hedge fund.\n"
        "Your task is to generate trade signals based on Technical Analysis (TA) and News Sentiment.\n\n"
        "STRATEGY RULES:\n"
        "1. **Mean Reversion**: If RSI < 30 AND Sentiment > -0.2 -> BUY (Oversold but news isn't catastrophic).\n"
        "2. **Trend Following**: If Price > SMA200 AND Sentiment > 0.5 -> BUY (Strong trend + Good news).\n"
        "3. **Profit Taking**: If RSI > 75 -> SELL/TRIM.\n"
        "4. **Risk Aversion**: If Sentiment < -0.7 -> SELL/AVOID regardless of technicals.\n"
        "5. **Hold**: If signals are conflicting or weak.\n\n"
        "Produce a JSON proposal containing a signal for every ticker provided."
    )
    
    user_content = "Here is the latest market analysis:\n\n" + "\n".join(technicals_summary)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", user_content)
    ])

    # 4. Generate Proposal
    chain = prompt | llm.with_structured_output(StrategyProposal)
    
    try:
        proposal = chain.invoke({})
        print(f"📈 QUANT PROPOSAL GENERATED: {len(proposal.signals)} signals")
        for sig in proposal.signals:
            print(f"   - {sig.symbol}: {sig.action} (Conf: {sig.confidence}) -> {sig.reasoning}")
            
    except Exception as e:
        print(f"⚠️ QUANT ERROR: {e}")
        return {"error": str(e)}

    # 5. Return to State
    # Note: We convert Pydantic models to dicts for JSON serialization in LangGraph state
    return {
        "trade_proposal": [sig.dict() for sig in proposal.signals],
        "messages": [state["messages"][-1]] # Keep history clean
    }
