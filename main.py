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
        print("\n⏸️  PAUSED FOR HUMAN APPROVAL")
        
        # Show what is pending
        current_values = snapshot.values
        orders = current_values.get("approved_orders", [])
        
        if not orders:
            print("No orders to execute. Process finished.")
            sys.exit(0)
            
        print(f"💰 PENDING ORDERS: {len(orders)}")
        for o in orders:
            print(f"   - {o['side']} {o['qty']} {o['symbol']}")
            
        # 3. Ask for Permission
        user_input = input("\n✅ Do you approve execution? (yes/no): ")
        
        if user_input.lower() == "yes":
            print("🚀 RESUMING EXECUTION...")
            # Resume the graph - passing None as input simply continues execution
            for event in app.stream(None, thread):
                print(f"   -> Node: {event}")
        else:
            print("🛑 EXECUTION ABORTED BY USER.")
