# agents/supervisor.py
import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from typing import Literal

from core.state import AgentState

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_NAME = "gemini-3-flash-preview"
MAX_RETRIES = 2

# ==========================================
# 2. OUTPUT SCHEMA
# ==========================================
class SupervisorDecision(BaseModel):
    next_step: Literal[
        "data_engineer",
        "sentiment_analyst",
        "quant_analyst",
        "risk_manager",
        "executor",
        "FINISH"
    ] = Field(description="The next agent to act.")
    reasoning: str = Field(description="Why this step was chosen.")

# ==========================================
# 3. AGENT LOGIC
# ==========================================
def supervisor_node(state: AgentState):
    """
    The Supervisor (Brain).
    Routes workflow based on Data Availability + System Mode (High/Low).
    """
    
    # --- 1. AUTHENTICATION ---
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        location = "global",
        temperature=0
    )

    # --- 2. STATE INSPECTION ---
    raw_market_data = state.get("market_data")
    market_data = raw_market_data if raw_market_data is not None else {}
    approved_orders = state.get("approved_orders")
    retry_count = state.get("retry_count", 0)
    
    # READ SYSTEM MODE (Injected by main.py)
    system_mode = state.get("system_mode", "HIGH_MODE")
    
    # Check Flags
    stocks_present = bool(market_data.get("stocks"))
    flag_market_data = "YES" if stocks_present else "NO"
    flag_sentiment = "YES" if state.get("sentiment_data") else "NO"
    flag_proposal = "YES" if state.get("trade_proposal") else "NO"
    flag_risk_checked = "YES" if approved_orders is not None else "NO"
    
    # --- 3. CHECK FOR ABNORMAL BEHAVIOR (WAKE UP TRIGGER) ---
    sentiment_data = state.get("sentiment_data", {})
    is_abnormal = False
    if sentiment_data:
        scores = sentiment_data.get("scores", {})
        # Trigger if any sentiment is extremely strong
        for score in scores.values():
            if abs(score) > 0.8:
                is_abnormal = True
                print("🚨 SUPERVISOR: Abnormal Sentiment Detected (>0.8). Waking Quant Analyst!")
                break

    # --- 4. THE OPTIMIZATION LOOP (RETRY LOGIC) ---
    if flag_risk_checked == "YES":
        active_buys = [o for o in approved_orders if o['side'] == "BUY"]
        
        if not active_buys:
            if retry_count < MAX_RETRIES:
                print(f"🔄 SUPERVISOR: No buy opportunities found. Retrying (Attempt {retry_count + 1}/{MAX_RETRIES})...")
                return {
                    "next_step": "data_engineer",
                    "retry_count": retry_count + 1,
                    "trade_proposal": [],
                    "approved_orders": None,
                    "sentiment_data": None,
                    "market_data": None
                }
            else:
                print("🛑 SUPERVISOR: Max retries reached. Finishing.")
                return {"next_step": "executor"}

    # --- 5. SMART ROUTING (LOW MODE LOGIC) ---
    # If we have Data + Sentiment but NO Proposal...
    if flag_market_data == "YES" and flag_sentiment == "NO":
        return {"next_step": "sentiment_analyst"}
        
    if flag_market_data == "YES" and flag_sentiment == "YES" and flag_proposal == "NO":
        
        # LOGIC FOR LOW MODE: Sleep if boring, Wake if exciting
        if system_mode == "LOW_MODE":
            if is_abnormal:
                return {"next_step": "quant_analyst"} # Wake up!
            else:
                print("🌙 SUPERVISOR (Low Mode): Market calm. Skipping Quant/Risk.")
                return {"next_step": "FINISH"} # Go back to sleep
        
        # LOGIC FOR HIGH MODE: Always run Quant
        return {"next_step": "quant_analyst"}

    # --- 6. STANDARD LLM ROUTING ---
    members = ["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor"]
    
    system_prompt = (
        "You are the Supervisor.\n"
        "workflow:\n"
        f"- Market Data: {flag_market_data}\n"
        f"- Sentiment: {flag_sentiment}\n"
        f"- Proposal: {flag_proposal}\n"
        f"- Risk Done: {flag_risk_checked}\n\n"
        "ROUTING:\n"
        "1. No Market Data -> 'data_engineer'\n"
        "2. Need Sentiment -> 'sentiment_analyst'\n"
        "3. Need Proposal -> 'quant_analyst'\n"
        "4. Need Risk Check -> 'risk_manager'\n"
        "5. Risk Done -> 'executor'\n"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", f"Who acts next? Select one of: {members} or FINISH.")
    ])

    chain = prompt | llm.with_structured_output(SupervisorDecision)

    try:
        response = chain.invoke(state)
        print(f"🕵️ SUPERVISOR DECISION: {response.next_step} ({response.reasoning})")
        return {"next_step": response.next_step}
    except Exception as e:
        print(f"⚠️ SUPERVISOR ERROR: {e}")
        return {"next_step": "FINISH"}
