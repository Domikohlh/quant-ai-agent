import os
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from typing import Literal

from core.state import AgentState

MODEL_NAME = "gemini-3-flash-preview"
MAX_RETRIES = 5

class SupervisorDecision(BaseModel):
    next_step: Literal["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor", "FINISH"]
    reasoning: str

def supervisor_node(state: AgentState):
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        location = 'global',
        temperature=0
    )

    # --- 1. SAFE ACCESS (CRITICAL FIX) ---
    # Never allow None to crash the logic
    market_data = state.get("market_data") or {}
    stocks_present = bool(market_data.get("stocks"))
    
    approved_orders = state.get("approved_orders")
    retry_count = state.get("retry_count", 0)
    system_mode = state.get("system_mode", "HIGH_MODE")
    
    flag_risk_checked = "YES" if approved_orders is not None else "NO"

    # --- 2. RETRY LOGIC (LOOP PREVENTION) ---
    if flag_risk_checked == "YES":
        active_buys = [o for o in approved_orders if o['side'] == "BUY"]
        
        if not active_buys:
            if retry_count < MAX_RETRIES:
                print(f"🔄 SUPERVISOR: No buys. Retrying (Attempt {retry_count + 1})...")
                return {
                    "next_step": "data_engineer",
                    "retry_count": retry_count + 1,
                    # Clear proposals, but keep market data structure valid
                    "trade_proposal": [],
                    "approved_orders": None
                }
            else:
                print("🛑 SUPERVISOR: Max retries reached.")
                return {"next_step": "executor"}

    # --- 3. ABNORMAL SENTIMENT CHECK (MODE AWARE) ---
    sentiment_data = state.get("sentiment_data") or {}
    is_abnormal = False
    
    # Only check this if we are in LOW MODE (Sleeping)
    # If in HIGH MODE, we run Quant anyway, so no need to alarm.
    if system_mode == "LOW_MODE" and sentiment_data:
        for score in sentiment_data.get("scores", {}).values():
            if abs(score) > 0.8:
                is_abnormal = True
                print("🚨 SUPERVISOR: Abnormal Sentiment during Sleep!")
                break

    # --- 4. ROUTING LOGIC ---
    # Flags
    flag_data = "YES" if stocks_present else "NO"
    flag_sent = "YES" if state.get("sentiment_data") else "NO"
    flag_prop = "YES" if state.get("trade_proposal") else "NO"
    
    # A. Special Case: Low Mode Logic
    if flag_data == "YES" and flag_sent == "YES" and flag_prop == "NO":
        if system_mode == "LOW_MODE":
            if is_abnormal:
                return {"next_step": "quant_analyst"} # Wake up
            else:
                return {"next_step": "FINISH"} # Go back to sleep
        else:
            return {"next_step": "quant_analyst"} # Normal flow

    # B. Standard Routing
    members = ["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor"]
    
    system_prompt = (
        "You are the Supervisor.\n"
        f"STATE: Data={flag_data}, Sent={flag_sent}, Prop={flag_prop}, Risk={flag_risk_checked}\n"
        "RULES:\n"
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
        print(f"🕵️ SUPERVISOR: {response.next_step}")
        return {"next_step": response.next_step}
    except:
        return {"next_step": "FINISH"}
