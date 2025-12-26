# agents/data_engineer.py
import os
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import ToolMessage
from tools.market_data import data_tools
import google.auth

from core.state import AgentState

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Using Flash for speed/cost. It's great at calling tools.
MODEL_NAME = "gemini-2.0-flash" # Or "gemini-1.5-flash" depending on availability

# ==========================================
# 2. AGENT LOGIC
# ==========================================
def data_engineer_node(state: AgentState):
    """
    The Data Engineer.
    Role: Identify missing data -> Call Tools -> Update State.
    """
    
    # Auth
    credentials, project_id = google.auth.default()
    
    # Bind Tools to the LLM
    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        project=os.getenv("GCP_PROJECT_ID", project_id),
        credentials=credentials,
        temperature=0
    ).bind_tools(data_tools)

    # System Prompt
    system_prompt = (
        "You are the Data Engineer for a hedge fund.\n"
        "Your goal is to fetch perfect market data for the Quant Analyst.\n"
        "You have access to Alpaca (prices) and FRED (macro).\n\n"
        "TASK:\n"
        "1. Identify the 'Universe' of stocks we are trading (Default: AAPL, NVDA, TSLA, MSFT).\n"
        "2. Call `fetch_market_data` for these symbols.\n"
        "3. Call `fetch_macro_data` to get the VIX.\n"
        "4. Once data is retrieved, respond with 'DATA_READY'."
    )

    # ----------------------------------------------
    # INTERACTION LOOP (LLM -> Tool -> LLM)
    # ----------------------------------------------
    # In LangGraph, we often handle tool calls in a loop or let the graph handle it.
    # For simplicity, we manually invoke the tool if the LLM asks for it here,
    # or return the tool call for the runtime to execute.
    
    # Current best practice: Invoke LLM, if tool call, run it, then return result.
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("human", "Check the required data status and call tools if needed.")
    ])

    chain = prompt | llm
    
    # Get the LLM's thought process
    response = chain.invoke({"messages": state["messages"]})
    
    # Prepare updates to the state
    new_messages = [response]
    market_data_update = {}
    
    # CHECK FOR TOOL CALLS
    if response.tool_calls:
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            
            # Execute the tool (Simulated ToolNode execution)
            if tool_name == "fetch_market_data":
                data = data_tools[0](**tool_args) # Direct call for simplicity
                market_data_update["stocks"] = data
                content = "Market data fetched successfully."
                
            elif tool_name == "fetch_macro_data":
                data = data_tools[1](**tool_args)
                market_data_update["macro"] = data
                content = "Macro data fetched successfully."
            
            else:
                content = "Error: Tool not found."

            # Create the Tool Result Message
            tool_msg = ToolMessage(
                tool_call_id=tool_call["id"],
                content=str(content),
                name=tool_name
            )
            new_messages.append(tool_msg)
            
            print(f"📊 DATA ENGINEER ACTION: {tool_name}")

    # Return updated state
    # We update 'market_data' in the shared state so the Quant Analyst can read it later
    return {
        "messages": new_messages,
        "market_data": market_data_update if market_data_update else state.get("market_data"),
        # Note: The Supervisor will see 'market_data' is present next turn and route to Sentiment
    }
