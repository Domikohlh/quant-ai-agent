# agents/supervisor.py
import os
from typing import Literal
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
import google.auth # Added for Vertex Auth

from core.state import AgentState

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_NAME = "gemini-3.0-pro-001" 
MEMBERS = ["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor"]

# ==========================================
# 2. OUTPUT STRUCTURE
# ==========================================
class RouteDecision(BaseModel):
    next: Literal["data_engineer", "sentiment_analyst", "quant_analyst", "risk_manager", "executor", "FINISH"] = Field(
        description="The specific agent to route the conversation to, or FINISH."
    )
    reasoning: str = Field(description="Brief explanation of choice.")

# ==========================================
# 3. SUPERVISOR LOGIC
# ==========================================
def supervisor_node(state: AgentState):
    
    # --- VERTEX AI AUTHENTICATION ---
    # This detects if you are on your Laptop (needs 'gcloud auth login') 
    # or on Cloud Run (uses the Service Account from Terraform).
    credentials, project_id = google.auth.default()

    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        location="us-central1",
        credentials=credentials,
        temperature=0
    )

    # Define the System Prompt
    system_prompt = (
        "You are the Supervisor of a high-frequency algorithmic trading system.\n"
        "Workers: {members}.\n\n"
        "RULES:\n"
        "1. No Market Data? -> data_engineer\n"
        "2. No Sentiment? -> sentiment_analyst\n"
        "3. Have Data & Sentiment? -> quant_analyst\n"
        "4. Have Proposal? -> risk_manager\n"
        "5. Risk Approved? -> executor\n"
        "6. Done? -> FINISH\n\n"
        "STATUS:\n"
        "- Market Data: {has_market_data}\n"
        "- Sentiment: {has_sentiment_data}\n"
        "- Proposal: {has_proposal}\n"
        "- Risk Check: {has_risk_check}\n"
    )

    # Dynamic State Inspection
    has_market_data = "YES" if state.get("market_data") else "NO"
    has_sentiment_data = "YES" if state.get("sentiment_data") else "NO"
    has_proposal = "YES" if state.get("trade_proposal") else "NO"
    has_risk_check = "YES" if state.get("risk_assessment") else "NO"

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("system", "Who acts next?")
    ])

    # Chain Construction
    chain = prompt | llm.with_structured_output(RouteDecision)

    response = chain.invoke({
        "members": ", ".join(MEMBERS),
        "messages": state["messages"],
        "has_market_data": has_market_data,
        "has_sentiment_data": has_sentiment_data,
        "has_proposal": has_proposal,
        "has_risk_check": has_risk_check
    })

    print(f"🕵️ SUPERVISOR DECISION: {response.next} ({response.reasoning})")

    return {"next_step": response.next}
