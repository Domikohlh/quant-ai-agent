# core/state.py
import operator
from typing import Annotated, List, Union, TypedDict, Optional

class AgentState(TypedDict):
    messages: Annotated[List[dict], operator.add]
    market_data: Optional[dict]
    sentiment_data: Optional[dict]
    trade_proposal: Optional[List[dict]]
    approved_orders: Optional[List[dict]]
    risk_assessment: Optional[str]
    execution_result: Optional[dict]
    next_step: Optional[str]
    
    # --- NEW FIELDS ---
    portfolio_data: Optional[dict]    # The HHI/Beta numbers
    strategy_mandate: Optional[str]

    retry_count: int              # How many loops have we done? (0, 1, 2)
    analyzed_tickers: List[str]   # List of symbols we already checked today

    market_condition: Optional[str] # "CALM", "VOLATILE", "OPPORTUNITY"
    pending_count: int  
