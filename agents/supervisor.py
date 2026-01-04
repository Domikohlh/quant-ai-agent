# agents/supervisor.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel
from typing import Literal

from core.state import AgentState

MODEL_NAME = "gemini-3-pro-preview"
MAX_RETRIES = 5
TARGET_PENDING_ORDERS = 5

class SupervisorDecision(BaseModel):
    next_step: Literal["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor", "FINISH"]
    reasoning: str

def supervisor_node(state: AgentState):
    """
    Supervisor Node with 'Batch Processing' Loop.
    """
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        location = 'global',
        temperature=0
    )

    # --- 1. STATE INSPECTION ---
    trade_proposal = state.get("trade_proposal")
    approved_orders = state.get("approved_orders") or []
    retry_count = state.get("retry_count", 0)
    system_mode = state.get("system_mode", "HIGH_MODE")
    
    # Load counts
    initial_pending_count = state.get("pending_count", 0)
    current_session_count = len(approved_orders)
    total_pending = initial_pending_count + current_session_count
    
    market_condition = state.get("market_condition", "CALM")

    # ============================================================
    # 🌙 LOW MODE GATEKEEPING
    # ============================================================
    if system_mode == "LOW_MODE":
        # If we have reached our target, we force sleep/monitor
        if total_pending >= TARGET_PENDING_ORDERS:
            if market_condition == "CALM":
                print(f"🌙 SUPERVISOR: Target Reached ({total_pending}/{TARGET_PENDING_ORDERS}). Sleeping.")
                return {"next_step": "FINISH"}
        
        # If Data Engineer says "CALM" and we aren't hunting, sleep.
        if market_condition == "CALM" and total_pending >= TARGET_PENDING_ORDERS:
             return {"next_step": "FINISH"}

    # ============================================================
    # 🔄 BATCH LOOP (The "Fill the Basket" Logic)
    # ============================================================
    # Logic: If Risk Manager has finished (flag_risk=YES), check if we need more orders.
    # We check if approved_orders has changed or if we are at the end of a flow.
    
    flag_risk = "YES" if state.get("approved_orders") is not None else "NO"
    
    # Check if we just finished a successful pass (Risk approved something or rejected it)
    # We differentiate "Risk Done" from "Just Started" by checking if trade_proposal is set.
    if flag_risk == "YES" and trade_proposal is not None:
        
        if total_pending < TARGET_PENDING_ORDERS:
            print(f"🔄 BATCHING: Basket not full ({total_pending}/{TARGET_PENDING_ORDERS}). Looping back...")
            return {
                "next_step": "data_engineer",
                "retry_count": 0,          # Reset retry for new hunt
                "trade_proposal": None,    # Reset Quant
                # We KEEP approved_orders to accumulate them (assuming state appends)
                # We KEEP analyzed_tickers so Data Engineer finds NEW stocks
            }

    # ============================================================
    # ⚡ FAST TRACK: SHORT-CIRCUIT RETRY (Quant Failed)
    # ============================================================
    if trade_proposal is not None and len(trade_proposal) == 0:
        if retry_count < MAX_RETRIES:
            print(f"⚡ FAST TRACK: Quant found 0 signals. Immediate Retry (Attempt {retry_count + 1})...")
            return {
                "next_step": "data_engineer",
                "retry_count": retry_count + 1,
                "trade_proposal": None,
            }
        else:
            print("🛑 SUPERVISOR: Max retries reached (Fast Track).")
            # If we failed to find anything, check if we should still loop or quit
            if total_pending < TARGET_PENDING_ORDERS and system_mode == "LOW_MODE":
                 # Optional: force sleep if we failed 5 times in a row to prevent infinite loop
                 return {"next_step": "FINISH"}
            return {"next_step": "executor"}

    # ============================================================
    # 🔄 STANDARD ROUTING
    # ============================================================
    market_data = state.get("market_data") or {}
    flag_data = "YES" if bool(market_data.get("stocks")) else "NO"
    flag_sent = "YES" if state.get("sentiment_data") is not None else "NO"
    flag_prop = "YES" if trade_proposal is not None else "NO"
    
    # A. Low Mode Logic
    if flag_data == "YES" and flag_sent == "YES" and flag_prop == "NO":
        if system_mode == "LOW_MODE":
            return {"next_step": "quant_analyst"}

    # B. LLM Routing
    members = ["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor"]
    
    system_prompt = (
        "You are the Supervisor.\n"
        f"STATE: Data={flag_data}, Sent={flag_sent}, Prop={flag_prop}, Risk={flag_risk}\n"
        "ROUTING RULES:\n"
        "1. No Data -> data_engineer\n"
        "2. No Sentiment -> sentiment_analyst\n"
        "3. No Proposal -> quant_analyst\n"
        "4. Risk Not Done -> risk_manager\n"
        "5. Risk Done -> executor"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", f"Next step? {members}")
    ])

    chain = prompt | llm.with_structured_output(SupervisorDecision)
    
    try:
        response = chain.invoke(state)
        decision = response.next_step
        
        if flag_prop == "YES" and flag_risk == "NO":
            decision = "risk_manager"
            
        print(f"🕵️ SUPERVISOR: {decision}")
        return {"next_step": decision}
    except:
        return {"next_step": "FINISH"}
