# main.py
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

# Load Env Vars
load_dotenv()

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from core.state import AgentState

# Import Tools
from tools.portfolio import print_portfolio_dashboard
from tools.time_manager import get_market_status, set_manual_mode

# Import Agents
from agents.supervisor import supervisor_node
from agents.data_engineer import data_engineer_node
from agents.sentiment_analyst import sentiment_analyst_node
from agents.quant_analyst import quant_analyst_node
from agents.risk_manager import risk_manager_node
from agents.executor import executor_node
from agents.portfolio_manager import portfolio_manager_node
from agents.gatekeeper import gatekeeper_node

# ==========================================
# 1. BUILD THE GRAPH
# ==========================================
def build_graph():
    workflow = StateGraph(AgentState)

    # A. Add Nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("data_engineer", data_engineer_node)
    workflow.add_node("gatekeeper", gatekeeper_node)
    workflow.add_node("portfolio_manager", portfolio_manager_node)
    workflow.add_node("sentiment_analyst", sentiment_analyst_node)
    workflow.add_node("quant_analyst", quant_analyst_node)
    workflow.add_node("risk_manager", risk_manager_node)
    workflow.add_node("executor", executor_node)

    # B. Define Edges
    workflow.set_entry_point("supervisor")
    
    conditional_map = {
        "data_engineer": "data_engineer",
        "sentiment_analyst": "sentiment_analyst",
        "quant_analyst": "quant_analyst",
        "risk_manager": "risk_manager",
        "executor": "executor",
        "FINISH": END
    }
    
    workflow.add_conditional_edges("supervisor", lambda x: x["next_step"], conditional_map)

    # C. Return Edges
    workflow.add_edge("data_engineer", "gatekeeper")
    workflow.add_edge("gatekeeper", "portfolio_manager")
    workflow.add_edge("portfolio_manager", "supervisor")
    workflow.add_edge("sentiment_analyst", "supervisor")
    workflow.add_edge("quant_analyst", "supervisor")
    workflow.add_edge("risk_manager", "supervisor")
    workflow.add_edge("executor", "supervisor")

    # D. Compile
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory, interrupt_before=["executor"])
    return app
    
def count_pending_orders():
    """Counts lines in the pending file to enforce the limit."""
    if not os.path.exists("pending_orders.txt"):
        return 0
    with open("pending_orders.txt", "r") as f:
        # Count lines that look like orders (contain '|')
        return sum(1 for line in f if "|" in line)
    
def print_trade_deal_sheet(approved_orders):
    if not approved_orders: return
    active_trades = [o for o in approved_orders if o['side'] in ["BUY", "SELL"]]
    holds = [o for o in approved_orders if o['side'] == "HOLD"]

    print("\n" + "="*60)
    print(f"📋 STRATEGIC TRADING PLAN")
    print("="*60)
    
    if active_trades:
        print(f"\n🚀 PROPOSED EXECUTION (Number of proposed trades: {len(active_trades)})")
        print("-" * 60)
        for i, o in enumerate(active_trades, 1):
            icon = "🟢" if o['side'] == "BUY" else "🔴"
            price = o.get('current_price', 0.0)
            print(f"{i}. {icon} {o['side']} {o['symbol']} @ ${price:,.2f}")
            print(f"   ├─ Qty:       {o['qty']}")
            print(f"   ├─ Rationale: {o.get('reasoning', 'N/A')}")
            print(f"   ├─ Return:    {o.get('expected_return', 'N/A')}")
            print(f"   └─ Risk:      {o.get('risk_analysis', 'N/A')}")
            print("-" * 60)

    if holds:
        print(f"\n💼 PORTFOLIO REVIEW (Number of current holdings: {len(holds)})")
        print("-" * 60)
        for i, o in enumerate(holds, 1):
            price = o.get('current_price', 0.0)
            print(f"{i}. 🟡 HOLD {o['symbol']} (Price: ${price:,.2f})")
            print(f"   ├─ Rationale: {o.get('reasoning', 'N/A')}")
            print(f"   └─ Verdict:   {o.get('risk_analysis', 'Stable')}")
            print("-" * 60)
    print("="*60 + "\n")

def save_to_pending_list(orders):
    if not orders: return
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open("pending_orders.txt", "a") as f:
        f.write(f"\n--- PENDING REVIEW ({timestamp}) ---\n")
        for o in orders:
            f.write(f"{o['side']} {o['symbol']} (Qty: {o['qty']}) | Reason: {o.get('reasoning')}\n")
    print(f"📝 {len(orders)} orders saved to 'pending_orders.txt'.")

# ==========================================
# 2. 24/7 DAEMON RUNTIME
# ==========================================
if __name__ == "__main__":
    app = build_graph()
    
    STRATEGIES = ["standard", "momentum", "undervalued"]
    cycle_index = 0
    recent_tickers_cache = []

    print("\n" + "="*50)
    print("🚀 QUANT AI AGENT: 24/7 SERVICE STARTED")
    print("   (Press Ctrl+C to Stop)")
    print("="*50 + "\n")
    
    if len(sys.argv) > 1:
        mode_arg = sys.argv[1].lower()
        if mode_arg in ["high", "low"]: set_manual_mode(mode_arg)
    
    while True:
        try:
            # 1. CHECK TIME & MODE
            market_status, mode, sleep_seconds = get_market_status()
            
            if os.path.exists("force_high.flag"): set_manual_mode("high")
            elif os.path.exists("force_low.flag"): set_manual_mode("low")
            
            print(f"\n⏰ CURRENT TIME: {datetime.now().strftime('%H:%M:%S')} | MARKET STATUS: {market_status} | SYSTEM MODE: {mode}")

            # 2. SLEEP MODE
            if mode == "SLEEP_MODE":
                print(f"💤 Market Closed. Sleeping for {sleep_seconds/3600:.1f} hours...")
                time.sleep(sleep_seconds)
                continue
            
            # 3. SELECT STRATEGY
            current_strategy = STRATEGIES[cycle_index % len(STRATEGIES)]
            cycle_index += 1
            
            print("\n" + "="*40)
            print(f"🔄 STARTING CYCLE {cycle_index}")
            print(f"🎯 CURRENT MISSION: Find '{current_strategy.upper()}' opportunities.")
            print("="*40)
            
            # 4. INITIALIZE STATE
            pending_count = count_pending_orders()
            
            initial_state = {
                "messages": [],
                "market_data": None,
                "sentiment_data": None,
                "trade_proposal": None,
                "approved_orders": None,
                "retry_count": 0,
                "forced_screener_mode": current_strategy,
                "analyzed_tickers": recent_tickers_cache[-50:],
                "pending_count": pending_count,
                "system_mode": mode
            }

            # 5. RUN AGENTS (WITH RECURSION FIX)
            run_config = {
                "configurable": {"thread_id": "live_agent_1"},
                "recursion_limit": 100
            }

            for event in app.stream(initial_state, run_config):
                pass

            # 6. POST-CYCLE CHECK
            snapshot = app.get_state(run_config)
            
            # SAFE ACCESS to prevent NoneType error
            approved_orders = snapshot.values.get("approved_orders") or []

            if snapshot.next and snapshot.next[0] == "executor":
                
                # Cache Updates
                newly_analyzed = snapshot.values.get("analyzed_tickers", [])
                recent_tickers_cache.extend(newly_analyzed)
                if len(recent_tickers_cache) > 100:
                    recent_tickers_cache = recent_tickers_cache[-100:]

                print("\n" + "░"*60)
                print("░░░                  CYCLE SUMMARY                  ░░░")
                print("░"*60)

                # Identify Active Trades vs Passive Holds
                active_trades = [o for o in approved_orders if o['side'] in ["BUY", "SELL"]]

                if mode == "LOW_MODE":
                    # FIX: Only save if there are ACTUAL TRADES (Ignore HOLDs)
                    if active_trades:
                        print("\n🌙 LOW MODE: Active Trading Opportunity Detected.")
                        save_to_pending_list(active_trades)
                        print("   (Sleeping... Execution skipped in Low Mode)")
                        # FIX: DO NOT RESUME. Just let the loop restart.
                    else:
                        print("\n🌙 LOW MODE: Market Calm. No Active Trades.")
                
                else:
                    # HIGH MODE (INTERACTIVE)
                    print_portfolio_dashboard()
                    print_trade_deal_sheet(approved_orders)
                    
                    if active_trades:
                        print("\n" + "!"*60)
                        user_input = input("✅ EXECUTE TRADES? (yes/no): ").lower()
                        print("!"*60)
                        
                        if user_input == "yes":
                            print("⚡ EXECUTING...")
                            for event in app.stream(None, run_config): pass
                        else:
                            print("🛑 CANCELLED.")
                    else:
                        print("\nℹ️ No active trades. Finishing cycle.")
                        for event in app.stream(None, run_config): pass

            # 7. SLEEP
            print("\n" + "="*40)
            print(f"⏳ CYCLE COMPLETE. Sleeping for {sleep_seconds} seconds...")
            print("="*40 + "\n")
            time.sleep(sleep_seconds)

        except KeyboardInterrupt:
            user_choice = input("\n🛑 STOPPED. Switch Mode? (high/low/auto/exit): ").lower()
            if user_choice in ["high", "low", "auto"]:
                if user_choice == "auto": set_manual_mode(None)
                else: set_manual_mode(user_choice)
                continue
            else:
                break
        except Exception as e:
            print(f"\n❌ CRITICAL LOOP ERROR: {e}")
            time.sleep(60)
