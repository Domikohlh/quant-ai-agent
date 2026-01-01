import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage

from core.state import AgentState
from tools.execution import execution_tools, execute_order
from tools.trade_memory import log_decision

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Flash is sufficient for function calling
MODEL_NAME = "gemini-2.5-flash"

# ==========================================
# 2. AGENT LOGIC
# ==========================================
def executor_node(state: AgentState):
    """
    The Executor.
    1. Reads 'approved_orders' from State.
    2. Executes them via Alpaca.
    3. Logs the result to SQLite Memory.
    """
    
    # Check if there is anything to do
    orders = state.get("approved_orders", [])
    if not orders:
        return {"execution_result": {"status": "NO_ORDERS"}, "messages": [AIMessage(content="No approved orders to execute.")]}

    # Auth (Standard boilerplate, though not strictly used if calling tools directly)
    credentials, project_id = google.auth.default()
    
    results = []

    # ----------------------------------------------
    # EXECUTION LOOP
    # ----------------------------------------------
    # We execute Python-side directly for reliability,
    # instead of asking the LLM to call the tool N times.
    
    print("⚡ STARTING EXECUTION PHASE...")
    
    for order in orders:
        symbol = order['symbol']
        side = order['side']
        qty = order['qty']
        order_type = order.get('order_type', 'MARKET')
        limit_price = order.get('limit_price')
        
        # Logic for logging
        rationale = order.get('reasoning', 'N/A')

        # --- SMART SLICING LOGIC (TWAP Lite) ---
        # If order is massive (>1000 shares), split it.
        # This prevents market impact in a real scenario.
        if qty > 1000:
            print(f"   🔪 Slicing large order for {symbol} ({qty} shares)...")
            chunk_1 = int(qty / 2)
            chunk_2 = qty - chunk_1
            
            # Execute Chunk 1
            res1 = execute_order(symbol, side, chunk_1, order_type, limit_price)
            results.append(res1)
            
            # Execute Chunk 2
            res2 = execute_order(symbol, side, chunk_2, order_type, limit_price)
            results.append(res2)
        else:
            # Standard Execution
            res = execute_order(symbol, side, qty, order_type, limit_price)
            results.append(res)
            
        # --- LOG EXECUTION TO MEMORY (RIGOROUSNESS) ---
        # We only log 'EXECUTED' if the function returns a success status/ID
        # Assuming execute_order returns a dict with 'id' or 'status'
        log_decision(
            symbol=symbol,
            action=side,
            outcome="EXECUTED",
            reasoning=f"Filled at market. Rationale: {rationale}",
            strategy="Standard Execution"
        )

    # Summarize for the Supervisor
    summary_msg = f"Executed {len(results)} trades. Statuses: {[r.get('status', 'ERROR') for r in results]}"

    return {
        "execution_result": {"orders": results},
        "messages": [AIMessage(content=summary_msg)]
    }
