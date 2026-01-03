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
    2. Filters out HOLDs/Zero-Qty orders (Passive Action).
    3. Executes BUY/SELL orders via Alpaca.
    4. Logs the result to SQLite Memory.
    """
    
    # Check if there is anything to do
    orders = state.get("approved_orders", [])
    if not orders:
        return {"execution_result": {"status": "NO_ORDERS"}, "messages": [AIMessage(content="No approved orders to execute.")]}

    # Auth (Standard boilerplate)
    credentials, project_id = google.auth.default()
    
    results = []

    # ----------------------------------------------
    # EXECUTION LOOP
    # ----------------------------------------------
    print("\n⚡ STARTING EXECUTION PHASE...")
    
    for order in orders:
        symbol = order['symbol']
        side = order['side']
        qty = float(order['qty']) # Ensure float
        order_type = order.get('order_type', 'MARKET')
        limit_price = order.get('limit_price')
        rationale = order.get('reasoning', 'N/A')

        # --- 1. ACTION FILTER (CRITICAL FIX) ---
        # If the strategy says HOLD, or the quantity is 0, DO NOT call the API.
        if side == "HOLD" or qty <= 0:
            print(f"   ⏸️ PASS: {symbol} (Decision: HOLD)")
            
            # Log it so we know why we didn't act
            log_decision(
                symbol=symbol,
                action="HOLD",
                outcome="EXECUTED", # Successfully executed the "do nothing" instruction
                reasoning=f"Passive Hold. Original Rationale: {rationale}",
                strategy="Passive Management"
            )
            continue

        # --- 2. SMART SLICING LOGIC (TWAP Lite) ---
        # If order is massive (>1000 shares), split it.
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
            print(f"   🚀 EXECUTING: {side} {qty} {symbol}")
            res = execute_order(symbol, side, qty, order_type, limit_price)
            results.append(res)
            
        # --- 3. LOG EXECUTION TO MEMORY ---
        # We assume execute_order returns a dict. If it failed, log as FAILED.
        status = res.get('status', 'UNKNOWN') if isinstance(res, dict) else 'SUBMITTED'
        
        log_decision(
            symbol=symbol,
            action=side,
            outcome="EXECUTED" if "error" not in str(res).lower() else "FAILED",
            reasoning=f"Filled at market. Status: {status}. Rationale: {rationale}",
            strategy="Standard Execution"
        )

    # Summarize for the Supervisor
    summary_msg = f"Processed {len(orders)} instructions. Active trades executed: {len(results)}."

    return {
        "execution_result": {"orders": results},
        "messages": [AIMessage(content=summary_msg)]
    }
