import os
# CRITICAL GCP FIX: Forces Numba to write compiled binaries to the writable RAM disk in Cloud Run
os.environ['NUMBA_CACHE_DIR'] = '/tmp' 

from google.cloud import bigquery, firestore
from fastmcp import FastMCP

# Import the isolated math engines
from engines.crypto_engine import fast_crypto_backtest
from engines.traditional_engine import fast_traditional_backtest

mcp = FastMCP("QuantBacktestServer")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "quant-ai-agent-482111")
DATASET_ID = "market_data"

@mcp.tool()
def run_strategy_backtest(job_id: str, confidence_threshold: float = 0.60, top_k: int = 2) -> str:
    """
    Executes a high-speed backtest using a previously trained BQML model.
    Must provide the exact job_id returned by check_pipeline_logs.
    """
    bq_client = bigquery.Client(project=PROJECT_ID)
    fs_client = firestore.Client(project=PROJECT_ID)
    
    # 1. Retrieve ML State
    doc = fs_client.collection("ml_pipeline_logs").document(job_id).get()
    if not doc.exists: return f"❌ Error: Job ID {job_id} not found."
    data = doc.to_dict()
    
    if data.get("status") != "SUCCESS_PRIME":
        return "❌ Error: Cannot backtest. Model status is not SUCCESS_PRIME."
        
    model_id = f"{PROJECT_ID}.{DATASET_ID}.{data['model_name']}"
    oos_start = data['out_of_sample_start_date']
    market_mode = data['market_mode']
    target_ticker = data['target_ticker']
    
    # 2. Fetch OOS Predictions (Zero Lookahead Bias)
    query = f"""
        SELECT * FROM ML.PREDICT(
            MODEL `{model_id}`,
            (SELECT * FROM `{PROJECT_ID}.{DATASET_ID}.historical_data` 
             WHERE DATE(timestamp) >= '{oos_start}')
        )
        ORDER BY timestamp ASC
    """
    df = bq_client.query(query).to_dataframe()
    if df.empty: return "❌ Error: No out-of-sample data found."

    df['probability'] = df['predicted_target_5d_probs'].apply(lambda x: max([p['prob'] for p in x]))
    
    initial_cap = 1000000.0
    t_cost = 0.00025
    
    # 3. Route to Engine and Format Output
    if market_mode == "CRYPTO":
        sl_pct = 0.05
        tp_pct = 0.10
        max_hold = 144 # Hours
        
        res = fast_crypto_backtest(df['close'].values, df['predicted_target_5d'].values, df['probability'].values, confidence_threshold, sl_pct, tp_pct, max_hold, t_cost)
        (final_equity, max_dd, total_trades, wins, longs, shorts, l_wins, s_wins, t_exits, sl_exits, tp_exits, t_costs) = res
        
        total_ret_pct = ((final_equity - initial_cap) / initial_cap) * 100
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        l_win_rate = (l_wins / longs * 100) if longs > 0 else 0
        s_win_rate = (s_wins / shorts * 100) if shorts > 0 else 0
        
        summary = f"""
=======================================================================
PERFORMANCE SUMMARY - CRYPTO OOS BACKTEST ({target_ticker})
=======================================================================
Model Job ID: {job_id}
OOS Start Date: {oos_start}

Strategy Parameters:
- Mode: CRYPTO (Event-Driven)
- Target Asset: {target_ticker}
- Confidence Threshold: {confidence_threshold * 100:.1f}%
- Max Hold Period: {max_hold} Hours
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
- Time Limit Exits (Hit {max_hold} Hours): {t_exits} ({(t_exits/total_trades*100) if total_trades>0 else 0:.1f}%)
- Stop Loss Exits (Hit {sl_pct*100:.1f}% loss): {sl_exits} ({(sl_exits/total_trades*100) if total_trades>0 else 0:.1f}%)
- Take Profit Exits (Hit {tp_pct*100:.1f}% gain): {tp_exits} ({(tp_exits/total_trades*100) if total_trades>0 else 0:.1f}%)

Cost Analysis:
- Total Transaction Costs Paid: ${t_costs:,.2f}
=======================================================================
Instruction: Analyze this forensic summary. Pay special attention to the Exit Analysis. If Stop-Loss exits dominate, warn the user the model has poor timing. Provide your recommendation for live execution.
"""
    else: 
        # TRADITIONAL MARKET ROUTING
        res = fast_traditional_backtest(df, top_k=top_k, t_cost=t_cost)
        (final_equity, max_dd, total_trades, wins, t_costs) = res
        
        total_ret_pct = ((final_equity - initial_cap) / initial_cap) * 100
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        basket_size = len(df['ticker'].unique())

        summary = f"""
=======================================================================
PERFORMANCE SUMMARY - TRADITIONAL OOS BACKTEST
=======================================================================
Model Job ID: {job_id}
OOS Start Date: {oos_start}

Strategy Parameters:
- Mode: TRADITIONAL (Cross-Sectional Portfolio)
- Sector Basket Size: {basket_size} assets
- Allocation: Long Top {top_k}, Short Bottom {top_k}
- Minimum Confidence: {confidence_threshold * 100:.1f}%
- Transaction Cost: {t_cost * 100:.3f}% per side

Performance Metrics:
- Initial Portfolio Value: ${initial_cap:,.2f}
- Final Portfolio Value: ${final_equity:,.2f}
- Total Return: {total_ret_pct:.2f}%
- Maximum Drawdown: {max_dd * 100:.2f}%

Trade Analysis (Basket Level):
- Total Daily Rebalances: {total_trades}
- Profitable Days: {win_rate:.2f}%

Cost Analysis:
- Total Transaction Costs Paid: ${t_costs:,.2f}
=======================================================================
Instruction: Analyze this cross-sectional summary. Evaluate if the Sharpe/Drawdown profile justifies the transaction costs. Provide your recommendation for live execution.
"""

    return summary