# agents/risk_manager.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import List, Literal

from core.state import AgentState
from tools.portfolio import get_current_portfolio

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_NAME = "gemini-3.0-pro-001" 

# ==========================================
# 2. OUTPUT SCHEMA
# ==========================================
class Order(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int = Field(description="Number of shares to execute.")
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: float = Field(default=0.0, description="Limit price if applicable.")
    reason: str = Field(description="Why this specific quantity was approved.")

class RiskAssessment(BaseModel):
    approved_orders: List[Order]
    rejected_orders: List[str] = Field(description="List of symbols rejected and why.")
    portfolio_status: str = Field(description="Summary of current exposure (e.g., 'Safe', 'Over-leveraged').")

# ==========================================
# 3. AGENT LOGIC
# ==========================================
def risk_manager_node(state: AgentState):
    """
    The Risk Manager.
    1. Fetches current Portfolio (Cash/Positions).
    2. Reviews Trade Proposals.
    3. Sizes the bets based on Equity % and Risk Rules.
    """
    
    # Auth
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0 # Zero temp = Strict Compliance
    )

    # 1. Get Context
    portfolio = get_current_portfolio() # Call tool directly
    proposals = state.get("trade_proposal", [])
    market_data = state.get("market_data", {}).get("stocks", {})

    if not proposals:
        print("🛡️ RISK MANAGER: No proposals to review.")
        return {"approved_orders": []}

    # 2. Prepare Context for LLM
    # We need to give the LLM the PRICE of the stocks to calculate share counts.
    # (Portfolio equity * weight) / Price = Shares
    
    price_context = {}
    for symbol, candles in market_data.items():
        # Get latest close from the list of dicts
        if candles:
            price_context[symbol] = candles[-1]['close']

    system_prompt = (
        "You are the Chief Risk Officer (CRO) of a hedge fund.\n"
        "Your goal is CAPITAL PRESERVATION. You evaluate trade proposals from the Quant Analyst.\n\n"
        "### PORTFOLIO CONSTRAINTS:\n"
        "1. **Max Position Size**: No single position > 20% of Total Equity.\n"
        "2. **Cash Buffer**: Maintain at least 5% cash reserve.\n"
        "3. **Confidence Adjustment**: If Signal Confidence < 0.6, reduce suggested size by 50%.\n"
        "4. **Short Selling**: WE DO NOT SHORT. If proposal is SELL, only sell what we currently own.\n\n"
        "### INPUT DATA:\n"
        f"Portfolio Equity: ${portfolio.get('total_equity', 0)}\n"
        f"Cash Available: ${portfolio.get('cash', 0)}\n"
        f"Current Holdings: {portfolio.get('holdings', {})}\n"
        f"Market Prices: {price_context}\n\n"
        "Task: Output a list of `approved_orders`. Calculate the exact `qty` (shares) based on the % weight requested."
    )

    user_content = f"Trade Proposals to Review:\n{proposals}"

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", user_content)
    ])

    # 3. Generate Assessment
    chain = prompt | llm.with_structured_output(RiskAssessment)
    
    try:
        decision = chain.invoke({})
        print(f"🛡️ RISK ASSESSMENT COMPLETE: {decision.portfolio_status}")
        print(f"   ✅ Approved: {len(decision.approved_orders)} orders")
        for o in decision.approved_orders:
            print(f"      - {o.side} {o.qty} {o.symbol} (Limit: {o.limit_price})")
        print(f"   ❌ Rejected: {decision.rejected_orders}")

        # 4. Return to State
        return {
            "approved_orders": [order.dict() for order in decision.approved_orders],
            "messages": [state["messages"][-1]] 
        }

    except Exception as e:
        print(f"⚠️ RISK ERROR: {e}")
        return {"error": str(e)}
