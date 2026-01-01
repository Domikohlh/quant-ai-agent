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
# Using the stable 1.5 Pro model for better reasoning
MODEL_NAME = "gemini-2.5-pro"

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
    Decides which agent runs next based on the current state of data.
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

    # --- 2. SAFE STATE INSPECTION ---
    # Fix: Handle case where market_data might be None (initial state)
    raw_market_data = state.get("market_data")
    market_data = raw_market_data if raw_market_data is not None else {}
    
    trade_proposal = state.get("trade_proposal")
    approved_orders = state.get("approved_orders")
    
    # Debug Print (Optional but helpful)
    #print(f"DEBUG SUPERVISOR: approved_orders type: {type(approved_orders)} value: {approved_orders}")

    # --- FIX: ROBUST CHECK ---
    # We check if the key exists in the dictionary explicitly, not just the value
    risk_checked = "YES" if "approved_orders" in state and state["approved_orders"] is not None else "NO"
    
    # --- 3. DETERMINE FLAGS ---
    # Check if we actually have stock data (not just an empty dict)
    stocks_present = bool(market_data.get("stocks"))
    has_errors = "error" in market_data or "ERROR" in market_data.get("macro", {})

    if stocks_present and not has_errors:
        flag_market_data = "YES"
    elif has_errors:
        flag_market_data = "ERROR_RETRY"
    else:
        flag_market_data = "NO"

    flag_sentiment = "YES" if state.get("sentiment_data") else "NO"
    flag_proposal = "YES" if trade_proposal else "NO"
    
    # Fix: Critical check to stop looping. If approved_orders exists, Risk is done.
    flag_risk_checked = "YES" if approved_orders is not None else "NO"

    # --- 4. SYSTEM PROMPT ---
    members = ["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor"]
    
    system_prompt = (
        "You are the Supervisor of an AI Hedge Fund.\n"
        "Your goal is to manage the workflow strictly according to the data availability.\n\n"
        "### CURRENT STATE FLAGS:\n"
        f"- Market Data Ready: {flag_market_data}\n"
        f"- Sentiment Data Ready: {flag_sentiment}\n"
        f"- Trade Proposal Ready: {flag_proposal}\n"
        f"- Risk Check Complete: {flag_risk_checked}\n\n"
        "### ROUTING RULES (IN ORDER):\n"
        "1. If Market Data is 'NO' or 'ERROR_RETRY' -> Route to 'data_engineer'.\n"
        "2. If Sentiment is 'NO' -> Route to 'sentiment_analyst'.\n"
        "3. If Proposal is 'NO' -> Route to 'quant_analyst'.\n"
        "4. If Risk Check is 'NO' -> Route to 'risk_manager'.\n"
        "5. If Risk Check is 'YES' (even if 0 orders approved) -> Route to 'executor'.\n"
        "6. If Executor has finished (check message history) -> 'FINISH'.\n"
    )

    # --- 5. BUILD PROMPT ---
    # Fix: Ends with "human" message to satisfy Vertex AI requirements
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", f"Given the state above, who should act next? Select one of: {members} or FINISH.")
    ])

    # --- 6. EXECUTE CHAIN ---
    chain = prompt | llm.with_structured_output(SupervisorDecision)

    try:
        response = chain.invoke(state)
        print(f"🕵️ SUPERVISOR DECISION: {response.next_step} ({response.reasoning})")
        return {"next_step": response.next_step}
        
    except Exception as e:
        print(f"⚠️ SUPERVISOR ERROR: {e}")
        # Default fallback to prevent crash
        return {"next_step": "FINISH"}
