# agents/portfolio_manager.py
import os
import json
import google.auth
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from core.state import AgentState
from tools.portfolio_monitor import calculate_portfolio_metrics

MODEL_NAME = "gemini-2.5-pro"

def portfolio_manager_node(state: AgentState):
    """
    The Portfolio Manager.
    Role: Analyzes current holdings vs. targets.
    Output: Sets the 'strategy_mandate' for the Quant Analyst.
    """
    credentials, project_id = google.auth.default()
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials
    )
    
    # 1. Run the Monitor Tool
    metrics = calculate_portfolio_metrics()
    
    # --- FIX: SAFE JSON CONVERSION ---
    # Convert dict to string safely to avoid brace collision in PromptTemplate
    metrics_json = json.dumps(metrics, indent=2)
    
    # 2. Formulate Strategy
    # Note: We use {metrics_json} as a placeholder, NOT an f-string
    system_prompt = (
        "You are the Portfolio Manager.\n"
        "Your job is to direct the trading strategy based on Portfolio Health.\n\n"
        "CURRENT METRICS:\n"
        "{metrics_json}\n\n"
        "RULES:\n"
        "1. If HHI > 2500 -> Mandate 'REDUCE_CONCENTRATION' (Sell largest positions).\n"
        "2. If Beta > 1.3 -> Mandate 'LOWER_VOLATILITY' (Buy Defensive).\n"
        "3. If Cash Only or Safe -> Mandate 'BUILD_CORE_POSITIONS' (Equal weight Blue Chips).\n"
        "4. If Sector > 40% -> Mandate 'DIVERSIFY_SECTOR'.\n\n"
        "OUTPUT: A concise directive string for the Quant Analyst."
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "What is the trading mandate for today based on these metrics?")
    ])
    
    chain = prompt | llm
    
    # --- FIX: PASS DATA HERE ---
    response = chain.invoke({"metrics_json": metrics_json})
    
    mandate = response.content
    print(f"👔 PORTFOLIO MANAGER MANDATE: {mandate}")
    
    # 3. Update State
    return {
        "portfolio_data": metrics,
        "strategy_mandate": mandate,
        "messages": [AIMessage(content=f"Portfolio Analysis: {mandate}")]
    }
