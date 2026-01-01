import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import List, Literal

from core.state import AgentState
from tools.portfolio import get_current_portfolio
from tools.trade_memory import log_decision

MODEL_NAME = "gemini-2.5-pro"

# --- OUTPUT SCHEMA ---
class Order(BaseModel):
    symbol: str
    qty: float
    # FIX: Add "HOLD" to allowed sides
    side: Literal["BUY", "SELL", "HOLD"]
    limit_price: float = Field(description="Use 0.0 for Market Orders")
    current_price: float = Field(description="Price at time of decision")
    
    # Rationale Fields
    reasoning: str = Field(description="Brief justification for the trade/hold")
    risk_analysis: str = Field(description="Primary downside risk identified")
    expected_return: str = Field(description="Conservative upside target")
    stop_loss: str = Field(description="Invalidation level")

class RiskAssessment(BaseModel):
    portfolio_status: str = Field(description="Summary of risk check")
    approved_orders: List[Order] = Field(description="List of orders (and verified holds)")
    rejected_orders: List[str] = Field(description="List of rejected symbols")

def risk_manager_node(state: AgentState):
    """
    The Risk Manager.
    Validates BUY/SELLs.
    Verifies HOLDs (Pass-through with risk check).
    """
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0
    )

    # Load Context
    portfolio = get_current_portfolio()
    proposals = state.get("trade_proposal", [])
    market_data = state.get("market_data", {}).get("stocks", {})

    if not proposals:
        return {"approved_orders": [], "messages": [AIMessage(content="No proposals.")]}

    # Price Context
    price_context = {s: c[-1]['close'] for s, c in market_data.items() if c}

    # --- UPDATED SYSTEM PROMPT ---
    system_text = (
        "You are the Chief Risk Officer (CRO).\n"
        "GOAL: Capital Preservation and Portfolio Health.\n\n"
        "RULES:\n"
        "1. MAX SIZE: 20% of Equity per asset.\n"
        "2. CASH BUFFER: Keep 5% cash available.\n"
        "3. HOLD SIGNALS: Approve 'HOLD' recommendations if the asset is not dangerously concentrated (>25% of portfolio).\n"
        "   - For HOLDs, set 'qty' to 0 (or the current holding amount if known).\n"
        "4. NO SHORT SELLING.\n\n"
        "DATA:\n"
        f"Equity: ${portfolio.get('total_equity', 0)}\n"
        f"Holdings: {str(portfolio.get('holdings', []))}\n"
        "INSTRUCTIONS:\n"
        "- Review 'Trade Proposals'.\n"
        "- Output 'approved_orders' including both TRADES and VERIFIED HOLDS."
    )

    messages = [
        SystemMessage(content=system_text),
        HumanMessage(content=f"Review these proposals: {str(proposals)}")
    ]

    # Execute
    chain = llm.with_structured_output(RiskAssessment)
    
    try:
        decision = chain.invoke(messages)
        
        # Merge Rationale (Critical for "Why we hold")
        proposal_map = {p['symbol']: p for p in proposals}
        final_orders = []
        
        for order in decision.approved_orders:
            original = proposal_map.get(order.symbol)
            if original:
                order_dict = order.model_dump()
                # Copy rich text
                order_dict['reasoning'] = original.get('reasoning', 'N/A')
                order_dict['risk_analysis'] = original.get('risk_analysis', 'N/A')
                order_dict['expected_return'] = original.get('expected_return', 'N/A')
                order_dict['stop_loss'] = original.get('stop_loss', 'N/A')
                order_dict['current_price'] = original.get('current_price', order.current_price)
                
                final_orders.append(order_dict)

        return {
            "approved_orders": final_orders,
            "risk_assessment": decision.portfolio_status,
            "messages": [AIMessage(content=f"Risk complete. Approved: {len(final_orders)}")]
        }

    except Exception as e:
        print(f"⚠️ RISK ERROR: {e}")
        return {"approved_orders": [], "error": str(e)}
