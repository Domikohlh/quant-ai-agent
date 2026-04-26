import os
import numpy as np
import pandas as pd
from numba import njit
from google.cloud import bigquery, firestore
from fastmcp import FastMCP

mcp = FastMCP("QuantBacktestServer")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "quant-ai-agent-482111")
DATASET_ID = "market_data"

# 1. THE NUMBA COMPILED ENGINE (Lightning fast, deep forensics)
@njit
def fast_numba_backtest(prices, predictions, probabilities, conf_threshold, stop_loss_pct, take_profit_pct, max_hold, transaction_cost):
    """
    C-compiled trade simulator. 
    Tracks every exact entry, exit reason, and cost for deep forensics.
    """
    n = len(prices)
    
    # State tracking
    position = 0 
    entry_price = 0.0
    entry_idx = 0
    size_factor = 0.0
    
    # Metric Accumulators
    total_trades = 0
    winning_trades = 0
    long_trades = 0
    short_trades = 0
    long_wins = 0
    short_wins = 0
    
    # Exit Reason Counters
    time_exits = 0
    sl_exits = 0
    tp_exits = 0
    
    # Financials
    equity = 1000000.0
    total_costs = 0.0
    peak_equity = equity
    max_drawdown = 0.0
    
    for i in range(1, n):
        current_price = prices[i]
        
        # --- ACTIVE POSITION LOGIC ---
        if position != 0:
            hold_time = i - entry_idx
            unrealized_return = (current_price - entry_price) / entry_price if position == 1 else (entry_price - current_price) / entry_price
            
            exit_reason = 0 # 0=None, 1=Time, 2=SL, 3=TP
            
            # Check Exits
            if unrealized_return <= -stop_loss_pct:
                exit_reason = 2
                sl_exits += 1
            elif unrealized_return >= take_profit_pct:
                exit_reason = 3
                tp_exits += 1
            elif hold_time >= max_hold:
                exit_reason = 1
                time_exits += 1
                
            if exit_reason != 0:
                # Close Trade
                trade_return = unrealized_return - transaction_cost
                profit = equity * size_factor * trade_return
                equity += profit
                total_costs += (equity * size_factor * transaction_cost)
                
                # Update Forensics
                total_trades += 1
                if trade_return > 0: winning_trades += 1
                
                if position == 1:
                    long_trades += 1
                    if trade_return > 0: long_wins += 1
                else:
                    short_trades += 1
                    if trade_return > 0: short_wins += 1
                    
                position = 0 # Reset
                
        # --- ENTRY LOGIC ---
        if position == 0:
            prob = probabilities[i]
            if prob >= conf_threshold:
                position = predictions[i] # 1 or -1
                entry_price = current_price
                entry_idx = i
                # Simplified Sigmoid proxy for Numba
                size_factor = 0.25 + ((prob - 0.5) * 1.5) 
                if size_factor > 1.0: size_factor = 1.0
                
                # Charge entry fee
                fee = equity * size_factor * transaction_cost
                equity -= fee
                total_costs += fee

        # Track Drawdown
        if equity > peak_equity: peak_equity = equity
        dd = (peak_equity - equity) / peak_equity
        if dd > max_drawdown: max_drawdown = dd

    return equity, max_drawdown, total_trades, winning_trades, long_trades, short_trades, long_wins, short_wins, time_exits, sl_exits, tp_exits, total_costs

# 2. THE AGENT TOOL
@mcp.tool()
def run_strategy_backtest(target_ticker: str, confidence_threshold: float = 0.60) -> str:
    bq_client = bigquery.Client(project=PROJECT_ID)
    
    # ... (Run ML.PREDICT Query exactly as before, load into Pandas 'df') ...
    
    # Extract raw NumPy arrays for Numba
    prices = df['Close'].values
    predictions = df['predicted_target_5d'].values
    probabilities = df['probability'].values
    
    # Configuration
    initial_cap = 1000000.0
    sl_pct = 0.05 # 5% Stop Loss
    tp_pct = 0.10 # 10% Take profit
    max_hold = 5  # 5 Days
    t_cost = 0.00025
    
    # Run Numba Engine (Executes in < 50 milliseconds)
    results = fast_numba_backtest(prices, predictions, probabilities, confidence_threshold, sl_pct, tp_pct, max_hold, t_cost)
    
    (final_equity, max_dd, total_trades, wins, longs, shorts, l_wins, s_wins, 
     t_exits, sl_exits, tp_exits, t_costs) = results
     
    # Calculate percentages safely
    total_ret_pct = ((final_equity - initial_cap) / initial_cap) * 100
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    l_win_rate = (l_wins / longs * 100) if longs > 0 else 0
    s_win_rate = (s_wins / shorts * 100) if shorts > 0 else 0

    # 3. EXACT OUTPUT TEMPLATE REPLICATION
    summary = f"""
=======================================================================
PERFORMANCE SUMMARY - PRIME BQML MODEL ({target_ticker})
=======================================================================

Strategy Parameters:
- Target Ticker: {target_ticker}
- Confidence Threshold: {confidence_threshold * 100:.1f}%
- Max Hold Period: {max_hold} Days
- Stop Loss: Enabled ({sl_pct * 100:.1f}%)
- Take Profit: Enabled ({tp_pct * 100:.1f}%)
- Transaction Cost: {t_cost * 100:.3f}% per side

Performance Metrics:
- Initial Portfolio Value: ${initial_cap:,.2f}
- Final Portfolio Value: ${final_equity:,.2f}
- Total Return: {total_ret_pct:.2f}%
- Maximum Drawdown: {max_dd * 100:.2f}%

Trade Analysis:
- Number of Trades: {total_trades}
- Overall Win Rate: {win_rate:.2f}%
- Long Trades: {longs} (Win Rate: {l_win_rate:.1f}%)
- Short Trades: {shorts} (Win Rate: {s_win_rate:.1f}%)

Exit Analysis:
- Time Limit Exits (Hit {max_hold} Days): {t_exits} ({(t_exits/total_trades*100) if total_trades>0 else 0:.1f}%)
- Stop Loss Exits (Hit {sl_pct*100}% loss): {sl_exits} ({(sl_exits/total_trades*100) if total_trades>0 else 0:.1f}%)
- Take Profit Exits (Hit {tp_pct*100}% gain): {tp_exits} ({(tp_exits/total_trades*100) if total_trades>0 else 0:.1f}%)

Cost Analysis:
- Total Transaction Costs Paid: ${t_costs:,.2f}

=======================================================================
Instruction: Analyze this detailed forensic summary. Pay special attention to the Exit Analysis. If Stop-Loss exits dominate, warn the user the model has poor timing. If Long vs. Short win rates are highly skewed, warn the user of directional bias.
"""
    return summary