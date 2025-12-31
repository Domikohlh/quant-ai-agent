import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import List, Literal

from core.state import AgentState
from tools.portfolio import get_current_portfolio
from tools.trade_memory import log_decision

# Use the smart model for complex risk reasoning
MODEL_NAME = "gemini-2.5-pro"

# ==========================================
# 1. OUTPUT SCHEMAS
# ==========================================
class Order(BaseModel):
    symbol: str
    qty: float
    side: Literal["BUY", "SELL"]
    limit_price: float = Field(description="Use 0.0 for Market Orders")
    
    # New Fields for HITL Rationale (Pass-through)
    reasoning: str = Field(description="Brief justification for the trade")
    risk_analysis: str = Field(description="Primary downside risk identified")
    expected_return: str = Field(description="Conservative upside target")
    stop_loss: str = Field(description="Invalidation level")

class RiskAssessment(BaseModel):
    portfolio_status: str = Field(description="Summary of risk check (e.g. 'Safe', 'Over-leveraged')")
    approved_orders: List[Order] = Field(description="List of orders that passed risk checks")
    rejected_orders: List[str] = Field(description="List of rejected symbols")

# ==========================================
# 2. AGENT LOGIC
# ==========================================
def risk_manager_node(state: AgentState):
    """
    The Risk Manager (Conscience).
    Validates proposals against portfolio limits and safety rules.
    Enriches orders with rationale for the human trader and logs rejections.
    """
    
    # --- 1. SETUP ---
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0
    )

    # --- 2. GET CONTEXT ---
    portfolio = get_current_portfolio()
    proposals = state.get("trade_proposal", [])
    market_data = state.get("market_data", {}).get("stocks", {})

    # If no proposals, nothing to check
    if not proposals:
        return {
            "approved_orders": [],
            "messages": [AIMessage(content="Risk Manager: No trades to review.")]
        }

    # --- 3. PREPARE DATA FOR LLM ---
    # Create a simplified price context for the LLM
    price_context = {}
    for symbol, candles in market_data.items():
        if candles:
            price_context[symbol] = candles[-1]['close']

    # --- 4. SYSTEM PROMPT ---
    system_text = (
        "You are the Chief Risk Officer (CRO).\n"
        "GOAL: Capital Preservation and Strict Compliance.\n\n"
        "RULES:\n"
        "1. Max Position Size: 20% of Total Equity per asset.\n"
        "2. Cash Buffer: Maintain at least 5% cash after trades.\n"
        "3. Confidence Check: If confidence < 0.6, cut quantity by 50%.\n"
        "4. NO SHORT SELLING (Long Only).\n\n"
        "DATA:\n"
        f"Equity: ${portfolio.get('total_equity', 0)}\n"
        f"Cash: ${portfolio.get('cash', 0)}\n"
        f"Current Holdings: {str(portfolio.get('holdings', []))}\n"
        f"Market Prices: {str(price_context)}\n\n"
        "INSTRUCTIONS:\n"
        "- Review the 'Trade Proposals' below.\n"
        "- Calculate cost (Qty * Price) vs Equity.\n"
        "- Output the final 'approved_orders' list."
    )

    # We send the proposals as a raw string to avoid parsing errors
    messages = [
        SystemMessage(content=system_text),
        HumanMessage(content=f"Review these proposals: {str(proposals)}")
    ]

    # --- 5. EXECUTE RISK CHECK ---
    chain = llm.with_structured_output(RiskAssessment)
    
    try:
        decision = chain.invoke(messages)
        
        # --- 6. MERGE RATIONALE (CRITICAL STEP) ---
        # The LLM gives us the safe Qty/Side, but might drop the rich text.
        # We manually copy the text fields from the Quant's proposal back into the final order.
        
        # Create a lookup map for the original proposals
        proposal_map = {p['symbol']: p for p in proposals}
        
        final_orders = []
        approved_symbols = set()

        for order in decision.approved_orders:
            original = proposal_map.get(order.symbol)
            if original:
                approved_symbols.add(order.symbol)
                
                # Convert Pydantic model to dict
                order_dict = order.model_dump()
                
                # Inject rich fields from the original proposal
                # Use 'N/A' defaults just in case
                order_dict['reasoning'] = original.get('reasoning', 'Rationale not provided')
                order_dict['risk_analysis'] = original.get('risk_analysis', 'Standard market risk')
                order_dict['expected_return'] = original.get('expected_return', 'N/A')
                order_dict['stop_loss'] = original.get('stop_loss', 'N/A')
                
                final_orders.append(order_dict)

        # --- 7. LOG REJECTIONS TO MEMORY (RIGOROUSNESS) ---
        # Identify which proposals were rejected so the Quant agent learns
        proposed_symbols = set(proposal_map.keys())
        rejected_symbols = proposed_symbols - approved_symbols
        
        for sym in rejected_symbols:
            log_decision(
                symbol=sym,
                action="BUY", # Assuming Long-only logic for rejection context
                outcome="REJECTED_RISK",
                reasoning=f"Risk Manager blocked trade. Portfolio Status: {decision.portfolio_status}",
                strategy="Risk Compliance"
            )

        # Logging
        print(f"🛡️ RISK ASSESSMENT COMPLETE: {decision.portfolio_status}")
        print(f"   ✅ Approved: {len(final_orders)} orders")
        for o in final_orders:
            print(f"      - {o['side']} {o['qty']} {o['symbol']} (Reason: {o['reasoning'][:30]}...)")
        
        # --- 8. RETURN STATE ---
        # Handle message history safely
        result_messages = []
        if state.get("messages") and len(state["messages"]) > 0:
            result_messages = [state["messages"][-1]]
        else:
            result_messages = [AIMessage(content=f"Risk complete. Approved: {len(final_orders)}")]

        return {
            "approved_orders": final_orders,
            "risk_assessment": decision.portfolio_status, # Persist for main.py
            "messages": result_messages
        }

    except Exception as e:
        print(f"⚠️ RISK ERROR: {e}")
        return {
            "approved_orders": [],
            "error": str(e),
            "messages": [AIMessage(content=f"Risk Check Failed: {str(e)}")]
        }
