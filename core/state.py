# core/state.py
import operator
from typing import Annotated, List, Union, TypedDict, Optional

class AgentState(TypedDict):
    # 'messages' appends history; others overwrite
    messages: Annotated[List[dict], operator.add]
    
    # Core Data
    market_data: Optional[dict]
    sentiment_data: Optional[dict]
    trade_proposal: Optional[List[dict]]
    approved_orders: Optional[List[dict]]
    
    # --- NEW FIELD ---
    portfolio: Optional[dict]  # Stores Cash, Equity, Position
    
    # Rigorous Tracking Fields (Requested)
    risk_assessment: Optional[str]      # Stores the full text rationale from Risk Manager
    execution_result: Optional[dict]    # Stores the raw output from Executor
    next_step: Optional[str]            # Tracks the Supervisor's decision
