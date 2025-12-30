# main.py
import os
import sys
from typing import Literal
from dotenv import load_dotenv

# Load Env Vars
load_dotenv()

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from core.state import AgentState

from tools.portfolio import print_portfolio_dashboard

# Import Agents
from agents.supervisor import supervisor_node
from agents.data_engineer import data_engineer_node
from agents.sentiment_analyst import sentiment_analyst_node
from agents.quant_analyst import quant_analyst_node
from agents.risk_manager import risk_manager_node
from agents.executor import executor_node

# ==========================================
# 1. BUILD THE GRAPH
# ==========================================
def build_graph():
    workflow = StateGraph(AgentState)

    # A. Add Nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("data_engineer", data_engineer_node)
    workflow.add_node("sentiment_analyst", sentiment_analyst_node)
    workflow.add_node("quant_analyst", quant_analyst_node)
    workflow.add_node("risk_manager", risk_manager_node)
    workflow.add_node("executor", executor_node)

    # B. Define Edges (Routing Logic)
    # The Supervisor decides 'next_step', so we map that string to a node
    workflow.set_entry_point("supervisor")
    
    conditional_map = {
        "data_engineer": "data_engineer",
        "sentiment_analyst": "sentiment_analyst",
        "quant_analyst": "quant_analyst",
        "risk_manager": "risk_manager",
        "executor": "executor",
        "FINISH": END
    }
    
    workflow.add_conditional_edges(
        "supervisor", 
        lambda x: x["next_step"], 
        conditional_map
    )

    # C. Return Edges
    # After work is done, always report back to Supervisor
    workflow.add_edge("data_engineer", "supervisor")
    workflow.add_edge("sentiment_analyst", "supervisor")
    workflow.add_edge("quant_analyst", "supervisor")
    workflow.add_edge("risk_manager", "supervisor")
    workflow.add_edge("executor", "supervisor")

    # --- FIX IS HERE ---
    # 1. Initialize Memory
    memory = MemorySaver()
    
    # 2. Attach Checkpointer to the Graph
    app = workflow.compile(
        checkpointer=memory,           # <--- This enables .get_state()
        interrupt_before=["executor"]  # <--- This enables Pausing
    )
    
    return app
    
def print_trade_deal_sheet(approved_orders):
    """Prints a detailed 'Deal Sheet' for the Human Executive."""
    if not approved_orders:
        print("   (No orders generated - Strategy matched HOLD)")
        return

    print(f"\n📋 PROPOSED TRADE DEALS ({len(approved_orders)})")
    print("="*60)
    
    for i, o in enumerate(approved_orders, 1):
        # Calculate approximate deal size
        # (Assuming you might not have price here, but if you do, use it)
        action_icon = "🟢" if o['side'] == "BUY" else "🔴"
        
        print(f"{i}. {action_icon} {o['side']} {o['symbol']}")
        print(f"   ├─ Quantity:  {o['qty']}")
        print(f"   ├─ Rationale: {o.get('reasoning', 'N/A')}")
        print(f"   ├─ Return:    {o.get('expected_return', 'N/A')}")
        print(f"   ├─ Risk:      {o.get('risk_analysis', 'N/A')}")
        print(f"   └─ Stop Loss: {o.get('stop_loss', 'N/A')}")
        print("-" * 60)

# ==========================================
# 2. RUNTIME LOGIC
# ==========================================
if __name__ == "__main__":
    app = build_graph()
    
    # Initial State
    initial_state = {
        "messages": [],
        "market_data": None,
        "sentiment_data": None,
        "trade_proposal": None,
        "approved_orders": None # <--- Good practice to initialize it
    }

    print("🚀 QUANT AI AGENT STARTED...")
    
    # 1. Run until interruption (Executor)
    # This runs Supervisor -> Data -> Sentiment -> Quant -> Risk... STOP
    thread = {"configurable": {"thread_id": "1"}}
    
    for event in app.stream(initial_state, thread):
        for key, value in event.items():
            print(f"\nExample Output from Node: {key}")
            # print(value) # Uncomment to see full state dump

    # 2. Inspect State at Interruption
    snapshot = app.get_state(thread)
    if snapshot.next and snapshot.next[0] == "executor":
        
        # --- VISUALIZATION STARTS HERE ---
        # A. Show the Portfolio Book
        print_portfolio_dashboard()
        
        # B. Show the Proposed Trade (from State)
        approved_orders = snapshot.values.get("approved_orders", [])
        print_trade_deal_sheet(approved_orders)
        print("📋 PENDING ORDERS FOR APPROVAL:")
        if approved_orders:
            for o in approved_orders:
                print(f"   👉 {o['side']} {o['qty']} {o['symbol']} @ Market")
        else:
            print("   (No orders generated - Strategy matched HOLD)")

        print("\n" + "-"*30)
        # --- VISUALIZATION ENDS HERE ---

        # 3. Human Decision
        user_input = input("✅ Do you approve execution? (yes/no): ").lower()
        
        if user_input == "yes":
            # Resume execution
            print("⚡ EXECUTION APPROVED. RESUMING...")
            # We use Command(resume=None) just to unpause the graph
            # (Use 'None' unless you want to change the state values)
            from langgraph.types import Command # Ensure Command is imported
            
            # Note: For simple unpausing in LangGraph, you often just run it again
            # But the correct modern way is often passing the input as a Config or updating state.
            # However, since 'executor' doesn't take user input directly in our node definition,
            # we can simply continue the stream.
            
            # Simple Continue:
            for event in app.stream(None, thread):
                pass
        else:
            print("🛑 EXECUTION REJECTED. SYSTEM SHUTDOWN.")
