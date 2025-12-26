# agents/risk_manager.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import List, Literal
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from core.state import AgentState
from tools.portfolio import get_current_portfolio

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_NAME = "gemini-2.5-pro" 

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

    system_text = (
        "You are the Chief Risk Officer (CRO).\n"
        "GOAL: Capital Preservation.\n\n"
        "RULES:\n"
        "1. Max Position: 20% of Equity.\n"
        "2. Cash Buffer: 5%.\n"
        "3. Confidence Check: If conf < 0.6, halve the size.\n"
        "4. NO SHORTING.\n\n"
        "DATA:\n"
        f"Equity: ${portfolio.get('total_equity', 0)}\n"
        f"Cash: ${portfolio.get('cash', 0)}\n"
        f"Holdings: {str(portfolio.get('holdings', {}))}\n" # str() ensures it's text
        f"Prices: {str(price_context)}\n\n" # str() ensures it's text
        "OUTPUT: JSON with approved_orders."
    )

# We skip the 'ChatPromptTemplate' wrapper to avoid variable parsing errors
    messages = [
        SystemMessage(content=system_text),
        HumanMessage(content=f"Review these proposals: {str(proposals)}")
    ]

    # 3. Generate Assessment
    chain = llm.with_structured_output(RiskAssessment)
    
    try:
        # Pass the message list directly
        decision = chain.invoke(messages)
        
        # ... keep the rest of the print/return logic ...
        print(f"🛡️ RISK ASSESSMENT COMPLETE: {decision.portfolio_status}")
        print(f"   ✅ Approved: {len(decision.approved_orders)} orders")
        for o in decision.approved_orders:
            print(f"      - {o.side} {o.qty} {o.symbol} (Limit: {o.limit_price})")
        
        # Handle message history safely
        result_messages = []
        
        if state.get("messages") and len(state["messages"]) > 0:
            result_messages = [state["messages"][-1]]
        else:
            # If history is empty, create a new log message
            result_messages = [AIMessage(content=f"Risk check complete. Approved: {len(decision.approved_orders)}")]

        return {
            "approved_orders": [order.dict() for order in decision.approved_orders],
            "messages": result_messages
        }

    except Exception as e:
        print(f"⚠️ RISK ERROR: {e}")
        return {"error": str(e)}
