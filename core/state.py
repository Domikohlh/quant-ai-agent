# core/state.py
import operator
from typing import Annotated, List, Dict, Optional, Any
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    # The conversation history (Agent thoughts, tool outputs)
    messages: Annotated[List[BaseMessage], operator.add]
    
    # The specific agent who should act next (determined by Supervisor)
    next_step: Optional[str]
    
    # --- SHARED DATA CONTEXT ---
    
    # 1. Market Data (From Data Engineer)
    # Stores OHLCV, VIX, P/E, Macro data
    market_data: Optional[Dict[str, Any]]
    
    # 2. Sentiment Data (From Sentiment Analyst)
    # Stores raw headlines and a computed sentiment score (-1.0 to 1.0)
    sentiment_data: Optional[Dict[str, Any]]
    
    # 3. Quant Signals (From Quant Analyst)
    # Stores technical indicators (RSI, MACD) and the Trade Proposal
    trade_proposal: Optional[Dict[str, Any]]
    
    # 4. Risk Assessment (From Risk Manager)
    # Stores validation result (Approved/Rejected) and reasoning
    risk_assessment: Optional[Dict[str, Any]]
    
    # 5. Execution Status (From Executor)
    # Stores order IDs and fill status
    execution_result: Optional[Dict[str, Any]]
