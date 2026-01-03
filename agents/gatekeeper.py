# agents/gatekeeper.py
from core.state import AgentState
from tools.gatekeeper import run_gatekeeper_checks

def gatekeeper_node(state: AgentState):
    """
    Non-LLM Node.
    Runs strictly before the Quant Analyst to identify forced exits.
    """
    market_data = state.get("market_data", {})
    
    # Run the math
    forced_exits = run_gatekeeper_checks(market_data)
    
    # If we have forced exits, we must pass them downstream
    # We format them to match the 'TradeSignal' schema expected by Risk/Executor
    
    proposals = state.get("trade_proposal") or []
    
    # Convert format
    for exit_order in forced_exits:
        signal = {
            "symbol": exit_order["symbol"],
            "action": "SELL",
            "confidence": 1.0, # Certainty
            "current_price": 0.0, # Will be filled by execution
            "reasoning": exit_order["reasoning"],
            "risk_analysis": "Forced compliance action.",
            "expected_return": "Capital Preservation",
            "stop_loss": "N/A"
        }
        proposals.append(signal)
    
    # Update State
    return {
        "trade_proposal": proposals
    }
